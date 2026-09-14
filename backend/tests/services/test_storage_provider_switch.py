"""Tests for provider switching and provider failure.

Two requirements, and they pull in opposite directions in a way worth stating.

Switching providers must change what the deployment writes to and nothing else: the same
service, the same schema, the same code path, and a different adapter chosen in one place.
And a row written *before* the switch must still resolve to the provider that holds its
bytes, because the alternative - signing an old key with the new provider - produces a
link that does not resolve, which a client can only report as a broken image.

Failure has the same shape. A provider that is down must produce a typed failure at the
boundary, never a silent success and never a row pointing at an object that does not
exist. The contract suite already proves that per adapter
(`tests/integrations/test_storage_contract.py`); what these tests add is the same
guarantee seen from the catalogue: the tenant is not charged, no row is written, and the
API answers with an error rather than a 200.
"""

from __future__ import annotations

import io
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import text

from ahia.bootstrap import build_application_container
from ahia.core.config import (
    AppEnvironment,
    MediaTargetFormat,
    Settings,
    StorageLimits,
    StorageProviderName,
)
from ahia.core.database import Base, Database
from ahia.core.errors import (
    ConfigurationError,
    StorageOperationError,
    StorageUnavailableError,
)
from ahia.core.permissions.permissions_registry import permission_codes_for_role
from ahia.core.ports.storage_port import StoredObject, compute_sha256
from ahia.core.tenant_context import TenantContext, build_tenant_context
from ahia.crud import product_crud, tenant_crud
from ahia.integrations.media.image_processor import PillowImageProcessor
from ahia.integrations.storage.storage_factory import (
    build_storage_adapters,
    build_storage_policy,
)
from ahia.models.entities.product_model import ProductModel
from ahia.models.entities.tenant_model import TenantModel
from ahia.services.audit_event_service import AuditEventService
from ahia.services.product_image_service import ProductImageService
from ahia.services.storage_quota_service import StorageQuotaService

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)
MEBIBYTE = 1024 * 1024


# ---------------------------------------------------------------------------
# Doubles: one object store per provider
# ---------------------------------------------------------------------------


class NamedStorage:
    """An in-memory object store that answers to one provider's name.

    `fail_uploads` models a provider that is down. Every method asserts the key is inside
    the tenant's prefix, as the real adapters do, so a service that built a key wrongly
    would fail here rather than silently succeeding.
    """

    def __init__(self, provider_name: str, *, fail_uploads: bool = False) -> None:
        self._provider_name = provider_name
        self._fail_uploads = fail_uploads
        self.objects: dict[str, bytes] = {}
        self.deleted_keys: list[str] = []

    @property
    def provider_name(self) -> str:
        return self._provider_name

    async def upload(self, request: Any) -> Any:
        assert request.key.startswith(f"tenants/{request.tenant_id}/")
        if self._fail_uploads:
            raise StorageOperationError(
                operation="storage_upload",
                entity="object",
                identifier=request.key,
                detail="the provider is unavailable",
            )
        self.objects[request.key] = request.content
        return StoredObject(
            provider=self._provider_name,
            key=request.key,
            mime_type=request.mime_type,
            size_bytes=len(request.content),
            checksum_sha256=compute_sha256(request.content),
            delivery_url=f"https://{self._provider_name}.example.test/{request.key}",
        )

    async def delete(self, *, key: str, tenant_id: str) -> None:
        assert key.startswith(f"tenants/{tenant_id}/")
        self.objects.pop(key, None)
        self.deleted_keys.append(key)

    async def exists(self, *, key: str, tenant_id: str) -> bool:
        return key in self.objects

    async def build_delivery_url(
        self,
        *,
        key: str,
        presentation_width: int | None = None,
        is_public: bool = False,
    ) -> str:
        return f"https://{self._provider_name}.example.test/{key}"

    async def close(self) -> None:
        return None


def build_limits(**overrides: Any) -> StorageLimits:
    baseline: dict[str, Any] = {
        "max_upload_bytes": 5 * MEBIBYTE,
        "max_product_image_bytes": 5 * MEBIBYTE,
        "max_image_width": 2000,
        "max_image_height": 2000,
        "max_images_per_product": 10,
        "max_tenant_storage_bytes": 500 * MEBIBYTE,
        "target_format": MediaTargetFormat.WEBP,
        "image_quality": 82,
        "strip_metadata": True,
        "allowed_content_types": ("image/jpeg", "image/png", "image/webp", "image/avif"),
    }
    baseline.update(overrides)
    return StorageLimits(**baseline)


def build_settings(**overrides: Any) -> Settings:
    baseline: dict[str, Any] = {
        "_env_file": None,
        "app_env": AppEnvironment.TEST,
        "database_url": os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL),
        "jwt_secret": "test-signing-secret-value-0000000001",
        "refresh_token_pepper": "test-refresh-pepper-value-00000000011",
        "storage_provider": StorageProviderName.R2,
        "r2_endpoint": "https://account.r2.cloudflarestorage.com",
        "r2_access_key_id": "r2-access-key",
        "r2_secret_access_key": "r2-secret-key",
        "r2_bucket": "ahia-test",
        "cloudinary_cloud_name": "ahia-test-cloud",
        "cloudinary_api_key": "cloudinary-key",
        "cloudinary_api_secret": "cloudinary-secret",
    }
    baseline.update(overrides)
    return Settings(**baseline)


def make_png(width: int = 300, height: int = 200) -> bytes:
    image = Image.new("RGB", (width, height), (200, 30, 40))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    instance = Database(build_settings())
    async with instance.engine.begin() as connection:
        # The whole schema, created from the models. A table's foreign keys require
        # the tables they reference to exist first, and creating everything in
        # dependency order is exactly what create_all does.
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(sync_connection, checkfirst=True)
        )
        await connection.execute(
            text("TRUNCATE TABLE product_images, products, tenant_storage_usage, tenants CASCADE")
        )
    try:
        yield instance
    finally:
        await instance.dispose()


async def insert_tenant(database: Database, tenant_id: UUID) -> None:
    async with database.transaction_scope() as unit_of_work:
        await tenant_crud.create(
            unit_of_work.session_handle,
            TenantModel.create(
                tenant_id=tenant_id,
                name=f"Tenant {tenant_id.hex[:6]}",
                slug=f"tenant-{tenant_id.hex[:8]}",
                now=NOW,
            ),
        )
        await unit_of_work.commit()


@pytest.fixture
async def tenant_id(database: Database) -> UUID:
    identifier = uuid4()
    await insert_tenant(database, identifier)
    return identifier


@pytest.fixture
async def product_id(database: Database, tenant_id: UUID) -> UUID:
    product = ProductModel.create(
        product_id=uuid4(),
        tenant_id=tenant_id,
        name="Coca Cola 50cl",
        selling_price=Decimal("250.00"),
        now=NOW,
    )
    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(unit_of_work.session_handle, product)
        await unit_of_work.commit()
    return product.id


def owner_context(tenant_id: UUID) -> TenantContext:
    return build_tenant_context(
        user_id=uuid4(),
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=permission_codes_for_role("OWNER"),
        role_name="OWNER",
    )


def build_service(
    database: Database,
    *,
    active: NamedStorage,
    readers: dict[str, NamedStorage] | None = None,
    limits: StorageLimits | None = None,
) -> ProductImageService:
    resolved_limits = limits or build_limits()
    return ProductImageService(
        unit_of_work_factory=database.unit_of_work_factory(),
        storage=active,
        storage_readers=readers if readers is not None else {active.provider_name: active},
        media=PillowImageProcessor(resolved_limits),
        storage_quota_service=StorageQuotaService(
            unit_of_work_factory=database.unit_of_work_factory(),
            quota_bytes=resolved_limits.max_tenant_storage_bytes,
        ),
        limits=resolved_limits,
        audit_event_service=AuditEventService(unit_of_work_factory=database.unit_of_work_factory()),
    )


async def accounting(database: Database, tenant_id: UUID) -> tuple[int, int]:
    async with database.transaction_scope() as unit_of_work:
        result = await unit_of_work.session_handle.execute(
            text(
                "SELECT used_bytes, reserved_bytes FROM tenant_storage_usage "
                "WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": str(tenant_id)},
        )
        row = result.first()
    return (0, 0) if row is None else (int(row[0]), int(row[1]))


# ---------------------------------------------------------------------------
# Switching providers
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_write_goes_to_the_active_provider(
    database: Database, tenant_id: UUID, product_id: UUID
) -> None:
    alpha = NamedStorage("alpha")
    beta = NamedStorage("beta")
    service = build_service(database, active=beta, readers={"alpha": alpha, "beta": beta})

    image = await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(),
        declared_content_type="image/png",
    )

    assert image.storage_provider == "beta"
    assert image.storage_key in beta.objects
    assert alpha.objects == {}, "the provider that is no longer active stores nothing new"


@pytest.mark.integration
async def test_a_row_written_before_a_switch_still_resolves_to_its_own_provider(
    database: Database, tenant_id: UUID, product_id: UUID
) -> None:
    """The requirement a switch has to satisfy: old links keep working."""
    alpha = NamedStorage("alpha")
    before = build_service(database, active=alpha)
    image = await before.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(),
        declared_content_type="image/png",
    )
    assert image.storage_provider == "alpha"

    # The switch: the same service, a different active adapter, both registered.
    beta = NamedStorage("beta")
    after = build_service(database, active=beta, readers={"alpha": alpha, "beta": beta})
    [stored] = await after.list_images(owner_context(tenant_id), product_id=product_id)

    url = await after.build_delivery_url(stored)

    assert url is not None
    assert url.startswith("https://alpha.example.test/"), (
        "the URL must come from the provider holding the bytes, not from the active one"
    )


@pytest.mark.integration
async def test_a_deletion_goes_to_the_provider_that_holds_the_object(
    database: Database, tenant_id: UUID, product_id: UUID
) -> None:
    alpha = NamedStorage("alpha")
    before = build_service(database, active=alpha)
    image = await before.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(),
        declared_content_type="image/png",
    )

    beta = NamedStorage("beta")
    after = build_service(database, active=beta, readers={"alpha": alpha, "beta": beta})
    removal = await after.remove_image(
        owner_context(tenant_id), product_id=product_id, image_id=image.id
    )

    assert removal.storage_released is True
    assert image.storage_key in alpha.deleted_keys
    assert beta.deleted_keys == []
    assert await accounting(database, tenant_id) == (0, 0)


@pytest.mark.integration
async def test_a_row_whose_provider_is_no_longer_configured_reports_no_url(
    database: Database, tenant_id: UUID, product_id: UUID
) -> None:
    """A missing link is honest; a mis-signed one looks like a deleted picture."""
    alpha = NamedStorage("alpha")
    before = build_service(database, active=alpha)
    image = await before.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(),
        declared_content_type="image/png",
    )

    beta = NamedStorage("beta")
    after = build_service(database, active=beta, readers={"beta": beta})

    assert await after.build_delivery_url(image) is None


@pytest.mark.integration
async def test_a_row_whose_provider_is_gone_cannot_be_deleted_and_stays_marked(
    database: Database, tenant_id: UUID, product_id: UUID
) -> None:
    """The bytes cannot be reached, so the row survives with a reason rather than lying."""
    alpha = NamedStorage("alpha")
    before = build_service(database, active=alpha)
    image = await before.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(),
        declared_content_type="image/png",
    )

    beta = NamedStorage("beta")
    after = build_service(database, active=beta, readers={"beta": beta})
    removal = await after.remove_image(
        owner_context(tenant_id), product_id=product_id, image_id=image.id
    )

    assert removal.storage_released is False
    assert removal.reconciliation_required is True
    assert await accounting(database, tenant_id) == (image.size_bytes, 0), (
        "the bytes still exist somewhere, so the tenant is still charged"
    )


@pytest.mark.integration
async def test_the_same_service_code_path_serves_both_providers(
    database: Database, tenant_id: UUID, product_id: UUID
) -> None:
    """Switching providers changes the adapter, not the pipeline."""
    for provider_name in ("alpha", "beta"):
        store = NamedStorage(provider_name)
        service = build_service(database, active=store)

        image = await service.attach_image(
            owner_context(tenant_id),
            product_id=product_id,
            content=make_png(),
            declared_content_type="image/png",
        )

        assert image.storage_provider == provider_name
        assert image.storage_key.startswith(f"tenants/{tenant_id}/products/{product_id}/")
        assert image.mime_type == "image/webp"


# ---------------------------------------------------------------------------
# Provider failure
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("provider_name", ["r2", "cloudinary"])
async def test_an_unavailable_provider_fails_typed_and_charges_nothing(
    database: Database, tenant_id: UUID, product_id: UUID, provider_name: str
) -> None:
    """Run for both provider names, because the failure must not depend on which one.

    The same service instance, the same pipeline, the same assertions: a deployment
    notices a provider outage in exactly the same way whichever provider is active.
    """
    store = NamedStorage(provider_name, fail_uploads=True)
    service = build_service(database, active=store)

    with pytest.raises(StorageOperationError):
        await service.attach_image(
            owner_context(tenant_id),
            product_id=product_id,
            content=make_png(),
            declared_content_type="image/png",
        )

    assert await accounting(database, tenant_id) == (0, 0), "no bytes, no reservation"
    assert await service.list_images(owner_context(tenant_id), product_id=product_id) == []


@pytest.mark.integration
@pytest.mark.parametrize("provider_name", ["r2", "cloudinary"])
async def test_a_degraded_result_is_never_recorded_as_an_image(
    database: Database, tenant_id: UUID, product_id: UUID, provider_name: str
) -> None:
    """The port's other failure shape: a typed degraded object instead of an exception."""

    class DegradingStorage(NamedStorage):
        async def upload(self, request: Any) -> Any:
            return StoredObject.degraded(
                provider=self.provider_name,
                key=request.key,
                mime_type=request.mime_type,
                size_bytes=len(request.content),
                checksum_sha256=compute_sha256(request.content),
                reason="provider unavailable",
            )

    service = build_service(database, active=DegradingStorage(provider_name))

    with pytest.raises(StorageUnavailableError):
        await service.attach_image(
            owner_context(tenant_id),
            product_id=product_id,
            content=make_png(),
            declared_content_type="image/png",
        )

    assert await accounting(database, tenant_id) == (0, 0)
    assert await service.list_images(owner_context(tenant_id), product_id=product_id) == []


# ---------------------------------------------------------------------------
# The composition root's registry
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_registry_holds_every_provider_that_has_credentials() -> None:
    """Both adapters exist when both are configured, so a switch needs no redeploy."""
    settings = build_settings(storage_provider=StorageProviderName.CLOUDINARY)

    adapters = build_storage_adapters(settings)

    assert sorted(adapters) == ["cloudinary", "r2"]


@pytest.mark.unit
def test_the_registry_holds_only_the_configured_provider_when_one_is_missing() -> None:
    """A deployment that has only ever used one provider is normal, not a fault."""
    settings = Settings(
        _env_file=None,
        app_env=AppEnvironment.TEST,
        database_url=os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL),
        jwt_secret="test-signing-secret-value-0000000001",
        refresh_token_pepper="test-refresh-pepper-value-00000000011",
        storage_provider=StorageProviderName.R2,
        r2_endpoint="https://account.r2.cloudflarestorage.com",
        r2_access_key_id="r2-access-key",
        r2_secret_access_key="r2-secret-key",
        r2_bucket="ahia-test",
    )

    adapters = build_storage_adapters(settings)

    assert sorted(adapters) == ["r2"]


@pytest.mark.unit
def test_each_provider_gets_its_own_resilience_policy() -> None:
    """One breaker per dependency: an unhealthy endpoint must not trip the other."""
    settings = build_settings()

    r2_policy = build_storage_policy(settings, provider=StorageProviderName.R2)
    cloudinary_policy = build_storage_policy(settings, provider=StorageProviderName.CLOUDINARY)

    assert r2_policy.describe()["dependency"] != cloudinary_policy.describe()["dependency"]
    assert r2_policy.describe()["dependency"] == "r2"
    assert cloudinary_policy.describe()["dependency"] == "cloudinary"


@pytest.mark.unit
def test_an_active_provider_without_credentials_is_refused_when_settings_are_built() -> None:
    """The first line of defence, and the one a deployment actually meets.

    Selecting a provider whose credentials are absent is refused while the settings
    object is being built, so the process does not reach a factory at all. The message
    names the variables, because the person reading it is holding a deployment.
    """
    with pytest.raises(ValidationError, match="CLOUDINARY_CLOUD_NAME"):
        Settings(
            _env_file=None,
            app_env=AppEnvironment.TEST,
            database_url=os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL),
            jwt_secret="test-signing-secret-value-0000000001",
            refresh_token_pepper="test-refresh-pepper-value-00000000011",
            storage_provider=StorageProviderName.CLOUDINARY,
        )


@pytest.mark.unit
def test_the_registry_refuses_an_active_provider_it_cannot_build() -> None:
    """The second line of defence, for a settings object that bypassed validation.

    `model_construct` builds one without running the validators, which is exactly the
    shape a future code path could produce - an enum member added for a provider whose
    adapter is not implemented yet. The registry must refuse rather than start with no
    way to store anything.
    """
    bypassed = Settings.model_construct(
        storage_provider=StorageProviderName.CLOUDINARY,
    )

    with pytest.raises(ConfigurationError, match="no complete configuration"):
        build_storage_adapters(bypassed)


@pytest.mark.integration
async def test_the_container_carries_both_adapters_and_one_active_one() -> None:
    container = build_application_container(
        build_settings(storage_provider=StorageProviderName.CLOUDINARY)
    )

    try:
        assert container.storage.provider_name == "cloudinary"
        assert sorted(container.storage_readers) == ["cloudinary", "r2"]
        assert container.product_image_service is not None
    finally:
        await container.storage.close()
        for adapter in container.storage_readers.values():
            await adapter.close()
        await container.database.dispose()
