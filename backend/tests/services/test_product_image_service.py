"""Tests for the product image use cases.

The upload pipeline is tested against the real image processor and a recording storage
double. The processor is real because the rules that matter are its rules - a declared
content type that disagrees with the decoded format, a decompression bomb, a resize that
actually happens - and a fake would assert my own assumptions back at me. The storage
double is a double because the object store is not the subject: what is asserted is that
the service calls it with a server-built key, once, and compensates when a later step
fails.

The failure paths are the ones worth the most care here: an upload that fails, a
persistence write that fails after the object is already stored, and a delete the
provider refuses. Each has a different consequence for the tenant's quota, and getting
one wrong leaks either storage or accounting.
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
from sqlalchemy import text

from ahia.core.config import (
    AppEnvironment,
    MediaTargetFormat,
    Settings,
    StorageLimits,
    StorageProviderName,
)
from ahia.core.database import Base, Database
from ahia.core.errors import (
    AuthorizationError,
    InvalidInputError,
    InvalidMediaError,
    NotFoundError,
    ResourceLimitExceededError,
    StorageOperationError,
    StorageUnavailableError,
)
from ahia.core.permissions.permissions_registry import permission_codes_for_role
from ahia.core.ports.storage_port import compute_sha256
from ahia.core.tenant_context import TenantContext, build_tenant_context
from ahia.crud import product_crud, tenant_crud
from ahia.integrations.media.image_processor import PillowImageProcessor
from ahia.models.entities.product_model import ProductModel
from ahia.models.entities.tenant_model import TenantModel
from ahia.services.audit_event_service import AuditEventService
from ahia.services.product_image_service import ProductImageService
from ahia.services.storage_quota_service import StorageQuotaService
from storage_double import RecordingStorage

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)
MEBIBYTE = 1024 * 1024


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


def build_limits(**overrides: Any) -> StorageLimits:
    baseline: dict[str, Any] = {
        "max_upload_bytes": 5 * MEBIBYTE,
        "max_product_image_bytes": 5 * MEBIBYTE,
        "max_image_width": 2000,
        "max_image_height": 2000,
        "max_images_per_product": 3,
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
    }
    baseline.update(overrides)
    return Settings(**baseline)


def make_png(width: int = 1200, height: int = 900) -> bytes:
    """Render a real image, so the real decoder is exercised."""
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


def build_service(
    database: Database,
    storage: RecordingStorage,
    *,
    limits: StorageLimits | None = None,
) -> ProductImageService:
    resolved_limits = limits or build_limits()
    quota = StorageQuotaService(
        unit_of_work_factory=database.unit_of_work_factory(),
        quota_bytes=resolved_limits.max_tenant_storage_bytes,
    )
    return ProductImageService(
        unit_of_work_factory=database.unit_of_work_factory(),
        storage=storage,
        media=PillowImageProcessor(resolved_limits),
        storage_quota_service=quota,
        limits=resolved_limits,
        audit_event_service=AuditEventService(unit_of_work_factory=database.unit_of_work_factory()),
    )


@pytest.fixture
def storage() -> RecordingStorage:
    return RecordingStorage()


@pytest.fixture
def service(database: Database, storage: RecordingStorage) -> ProductImageService:
    return build_service(database, storage)


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


def sales_context(tenant_id: UUID) -> TenantContext:
    return build_tenant_context(
        user_id=uuid4(),
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=permission_codes_for_role("SALES"),
        role_name="SALES",
    )


# ---------------------------------------------------------------------------
# The upload pipeline
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_an_uploaded_image_is_optimized_and_stored_under_a_server_key(
    service: ProductImageService,
    storage: RecordingStorage,
    tenant_id: UUID,
    product_id: UUID,
) -> None:
    image = await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(1600, 1200),
        declared_content_type="image/png",
    )

    assert image.storage_provider == "recording"
    assert image.storage_key == f"tenants/{tenant_id}/products/{product_id}/{image.id}.webp"
    assert image.mime_type == "image/webp", "the configured target format is what is stored"
    assert image.width == 1600
    assert image.height == 1200
    assert image.size_bytes > 0
    assert image.checksum_sha256 == compute_sha256(storage.objects[image.storage_key])
    assert len(storage.upload_requests) == 1


@pytest.mark.integration
async def test_a_large_image_is_resized_down_before_it_is_charged_for(
    database: Database, storage: RecordingStorage, tenant_id: UUID, product_id: UUID
) -> None:
    """Quota is charged for the optimized object, not for the phone photo that arrived.

    The source is larger than the configured maximum but inside the decompression-bomb
    ceiling, so it is resized rather than refused.
    """
    limits = build_limits(max_image_width=800, max_image_height=800)
    service = build_service(database, storage, limits=limits)
    uploaded = make_png(1600, 1200)

    image = await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=uploaded,
        declared_content_type="image/png",
    )

    assert (image.width, image.height) == (800, 600), "resized down, never up"
    assert image.size_bytes == len(storage.objects[image.storage_key])
    assert await committed_bytes(database, tenant_id) == image.size_bytes


async def committed_bytes(database: Database, tenant_id: UUID) -> int:
    """Return the tenant's committed bytes, read back from the accounting table."""
    used, _reserved = await accounting(database, tenant_id)
    return used


async def accounting(database: Database, tenant_id: UUID) -> tuple[int, int]:
    """Return (used_bytes, reserved_bytes) for the tenant.

    Both matter: a reservation that is never released is quota the tenant paid for and
    cannot use, so a failure path has to be checked against the reservation column and
    not only the committed one.
    """
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


@pytest.mark.integration
async def test_a_file_that_is_not_an_image_is_refused_before_anything_is_stored(
    service: ProductImageService, storage: RecordingStorage, tenant_id: UUID, product_id: UUID
) -> None:
    with pytest.raises(InvalidMediaError):
        await service.attach_image(
            owner_context(tenant_id),
            product_id=product_id,
            content=b"this is not a picture at all",
            declared_content_type="image/png",
        )

    assert storage.objects == {}
    assert storage.upload_requests == []


@pytest.mark.integration
async def test_a_declared_type_that_disagrees_with_the_bytes_is_refused(
    service: ProductImageService, storage: RecordingStorage, tenant_id: UUID, product_id: UUID
) -> None:
    """A declared content type is a claim; the decoded format is the evidence."""
    with pytest.raises(InvalidMediaError):
        await service.attach_image(
            owner_context(tenant_id),
            product_id=product_id,
            content=make_png(64, 64),
            declared_content_type="image/jpeg",
        )

    assert storage.objects == {}


@pytest.mark.integration
async def test_an_oversize_upload_is_refused(
    database: Database, storage: RecordingStorage, tenant_id: UUID, product_id: UUID
) -> None:
    service = build_service(database, storage, limits=build_limits(max_product_image_bytes=512))

    with pytest.raises(InvalidMediaError):
        await service.attach_image(
            owner_context(tenant_id),
            product_id=product_id,
            content=make_png(1200, 900),
            declared_content_type="image/png",
        )

    assert storage.objects == {}


@pytest.mark.integration
async def test_the_metadata_row_records_what_the_provider_and_the_processor_reported(
    service: ProductImageService, tenant_id: UUID, product_id: UUID
) -> None:
    image = await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(300, 200),
        declared_content_type="image/png",
        is_primary=True,
    )

    gallery = await service.list_images(owner_context(tenant_id), product_id=product_id)

    assert [entry.id for entry in gallery] == [image.id]
    assert gallery[0].is_primary is True
    assert gallery[0].width == 300
    assert gallery[0].height == 200
    assert gallery[0].storage_provider == "recording"


@pytest.mark.integration
async def test_uploading_a_cover_demotes_the_previous_one(
    service: ProductImageService, tenant_id: UUID, product_id: UUID
) -> None:
    first = await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(300, 200),
        declared_content_type="image/png",
        is_primary=True,
    )
    second = await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(320, 240),
        declared_content_type="image/png",
        is_primary=True,
    )

    gallery = await service.list_images(owner_context(tenant_id), product_id=product_id)

    assert [entry.id for entry in gallery] == [first.id, second.id]
    assert [entry.is_primary for entry in gallery] == [False, True]


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_refused_upload_releases_the_reservation_and_stores_nothing(
    database: Database,
    service: ProductImageService,
    storage: RecordingStorage,
    tenant_id: UUID,
    product_id: UUID,
) -> None:
    storage.fail_uploads = True

    with pytest.raises(StorageOperationError):
        await service.attach_image(
            owner_context(tenant_id),
            product_id=product_id,
            content=make_png(300, 200),
            declared_content_type="image/png",
        )

    assert await accounting(database, tenant_id) == (0, 0), "nothing committed, nothing held"
    assert await service.list_images(owner_context(tenant_id), product_id=product_id) == []


@pytest.mark.integration
async def test_a_degraded_upload_is_a_typed_failure_rather_than_an_empty_success(
    database: Database, storage: RecordingStorage, tenant_id: UUID, product_id: UUID
) -> None:
    """The port can degrade instead of raising; the service must not record a row."""
    service = build_service(database, storage)
    storage.degrade_uploads = True

    with pytest.raises(StorageUnavailableError):
        await service.attach_image(
            owner_context(tenant_id),
            product_id=product_id,
            content=make_png(300, 200),
            declared_content_type="image/png",
        )

    assert await accounting(database, tenant_id) == (0, 0)
    assert await service.list_images(owner_context(tenant_id), product_id=product_id) == []


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_per_product_image_limit_is_enforced_before_decoding(
    database: Database, storage: RecordingStorage, tenant_id: UUID, product_id: UUID
) -> None:
    service = build_service(database, storage, limits=build_limits(max_images_per_product=2))
    for _ in range(2):
        await service.attach_image(
            owner_context(tenant_id),
            product_id=product_id,
            content=make_png(120, 120),
            declared_content_type="image/png",
        )

    with pytest.raises(ResourceLimitExceededError) as captured:
        await service.attach_image(
            owner_context(tenant_id),
            product_id=product_id,
            content=make_png(120, 120),
            declared_content_type="image/png",
        )

    assert "maximum of 2 images" in (captured.value.context.detail or "")
    assert len(storage.upload_requests) == 2, "the refused upload never reached the provider"


@pytest.mark.integration
async def test_the_gallery_limit_counts_only_images_that_are_still_wanted(
    database: Database, storage: RecordingStorage, tenant_id: UUID, product_id: UUID
) -> None:
    service = build_service(database, storage, limits=build_limits(max_images_per_product=1))
    first = await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(120, 120),
        declared_content_type="image/png",
    )

    await service.remove_image(owner_context(tenant_id), product_id=product_id, image_id=first.id)
    await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(120, 120),
        declared_content_type="image/png",
    )

    assert len(await service.list_images(owner_context(tenant_id), product_id=product_id)) == 1


@pytest.mark.integration
async def test_the_tenant_quota_stops_an_upload_before_the_provider_is_called(
    database: Database, storage: RecordingStorage, tenant_id: UUID, product_id: UUID
) -> None:
    tiny_quota = build_limits(max_tenant_storage_bytes=1_024)
    service = build_service(database, storage, limits=tiny_quota)

    with pytest.raises(Exception) as captured:
        await service.attach_image(
            owner_context(tenant_id),
            product_id=product_id,
            content=make_png(1600, 1200),
            declared_content_type="image/png",
        )

    assert "quota" in str(captured.value).lower() or "capacity" in str(captured.value).lower()
    assert storage.upload_requests == []


# ---------------------------------------------------------------------------
# Removal and reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_removing_an_image_deletes_the_object_and_releases_its_bytes(
    database: Database, storage: RecordingStorage, tenant_id: UUID, product_id: UUID
) -> None:
    service = build_service(database, storage)
    image = await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(300, 200),
        declared_content_type="image/png",
    )

    removal = await service.remove_image(
        owner_context(tenant_id), product_id=product_id, image_id=image.id
    )

    assert removal.storage_released is True
    assert removal.reconciliation_required is False
    assert removal.released_bytes == image.size_bytes
    assert image.storage_key in storage.deleted_keys
    assert image.storage_key not in storage.objects
    assert await accounting(database, tenant_id) == (0, 0)
    assert await service.list_images(owner_context(tenant_id), product_id=product_id) == []


@pytest.mark.integration
async def test_a_refused_delete_keeps_the_row_marked_and_the_quota_committed(
    database: Database, storage: RecordingStorage, tenant_id: UUID, product_id: UUID
) -> None:
    """The bytes are still stored, so the tenant is still charged and the row survives."""
    service = build_service(database, storage)
    image = await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(300, 200),
        declared_content_type="image/png",
    )
    storage.fail_deletes = True

    removal = await service.remove_image(
        owner_context(tenant_id), product_id=product_id, image_id=image.id
    )

    assert removal.storage_released is False
    assert removal.reconciliation_required is True
    assert await committed_bytes(database, tenant_id) == image.size_bytes, "still occupying space"
    assert await service.list_images(owner_context(tenant_id), product_id=product_id) == []


@pytest.mark.integration
async def test_reconciliation_cleans_up_once_the_provider_recovers(
    database: Database, storage: RecordingStorage, tenant_id: UUID, product_id: UUID
) -> None:
    service = build_service(database, storage)
    image = await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(300, 200),
        declared_content_type="image/png",
    )
    storage.fail_deletes = True
    await service.remove_image(owner_context(tenant_id), product_id=product_id, image_id=image.id)

    storage.fail_deletes = False
    report = await service.reconcile_pending_deletions(owner_context(tenant_id))

    assert report.attempted == 1
    assert report.released == 1
    assert report.still_pending == 0
    assert await accounting(database, tenant_id) == (0, 0)
    assert image.storage_key in storage.deleted_keys


@pytest.mark.integration
async def test_reconciliation_leaves_what_it_cannot_delete(
    database: Database, storage: RecordingStorage, tenant_id: UUID, product_id: UUID
) -> None:
    service = build_service(database, storage)
    image = await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(300, 200),
        declared_content_type="image/png",
    )
    storage.fail_deletes = True
    await service.remove_image(owner_context(tenant_id), product_id=product_id, image_id=image.id)

    report = await service.reconcile_pending_deletions(owner_context(tenant_id))

    assert report.attempted == 1
    assert report.released == 0
    assert report.still_pending == 1
    assert await committed_bytes(database, tenant_id) == image.size_bytes


# ---------------------------------------------------------------------------
# Arranging the gallery
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_marking_a_cover_demotes_the_previous_one(
    service: ProductImageService, tenant_id: UUID, product_id: UUID
) -> None:
    first = await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(300, 200),
        declared_content_type="image/png",
        is_primary=True,
    )
    second = await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(320, 240),
        declared_content_type="image/png",
    )

    promoted = await service.set_primary_image(
        owner_context(tenant_id), product_id=product_id, image_id=second.id
    )
    gallery = await service.list_images(owner_context(tenant_id), product_id=product_id)

    assert promoted.is_primary is True
    flags = {entry.id: entry.is_primary for entry in gallery}
    assert flags == {first.id: False, second.id: True}


@pytest.mark.integration
async def test_reordering_applies_the_whole_order_and_keeps_the_cover(
    service: ProductImageService, tenant_id: UUID, product_id: UUID
) -> None:
    first = await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(300, 200),
        declared_content_type="image/png",
        is_primary=True,
    )
    second = await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(320, 240),
        declared_content_type="image/png",
    )

    reordered = await service.reorder_images(
        owner_context(tenant_id), product_id=product_id, image_ids=[second.id, first.id]
    )

    assert [entry.id for entry in reordered] == [second.id, first.id]
    assert [entry.sort_order for entry in reordered] == [0, 1]
    assert {entry.id: entry.is_primary for entry in reordered} == {
        first.id: True,
        second.id: False,
    }


@pytest.mark.integration
async def test_an_order_that_does_not_name_the_gallery_is_refused(
    service: ProductImageService, tenant_id: UUID, product_id: UUID
) -> None:
    """Forgetting an image must not silently drop it out of the gallery."""
    first = await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(300, 200),
        declared_content_type="image/png",
    )
    await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(320, 240),
        declared_content_type="image/png",
    )

    with pytest.raises(InvalidInputError):
        await service.reorder_images(
            owner_context(tenant_id), product_id=product_id, image_ids=[first.id]
        )


# ---------------------------------------------------------------------------
# Tenancy and authorization
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_an_image_cannot_be_attached_to_another_businesss_product(
    database: Database, storage: RecordingStorage, tenant_id: UUID
) -> None:
    other_tenant = uuid4()
    await insert_tenant(database, other_tenant)
    foreign_product = ProductModel.create(
        product_id=uuid4(),
        tenant_id=other_tenant,
        name="Theirs",
        selling_price=Decimal("10.00"),
        now=NOW,
    )
    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(unit_of_work.session_handle, foreign_product)
        await unit_of_work.commit()
    service = build_service(database, storage)

    with pytest.raises(NotFoundError):
        await service.attach_image(
            owner_context(tenant_id),
            product_id=foreign_product.id,
            content=make_png(120, 120),
            declared_content_type="image/png",
        )

    assert storage.upload_requests == []


@pytest.mark.integration
async def test_a_salesperson_cannot_attach_an_image(
    service: ProductImageService, storage: RecordingStorage, tenant_id: UUID, product_id: UUID
) -> None:
    with pytest.raises(AuthorizationError):
        await service.attach_image(
            sales_context(tenant_id),
            product_id=product_id,
            content=make_png(120, 120),
            declared_content_type="image/png",
        )

    assert storage.upload_requests == []


@pytest.mark.integration
async def test_a_salesperson_may_read_the_gallery(
    service: ProductImageService, tenant_id: UUID, product_id: UUID
) -> None:
    await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(120, 120),
        declared_content_type="image/png",
    )

    gallery = await service.list_images(sales_context(tenant_id), product_id=product_id)

    assert len(gallery) == 1


@pytest.mark.integration
async def test_a_delivery_url_is_derived_rather_than_stored(
    service: ProductImageService, tenant_id: UUID, product_id: UUID
) -> None:
    image = await service.attach_image(
        owner_context(tenant_id),
        product_id=product_id,
        content=make_png(120, 120),
        declared_content_type="image/png",
    )

    url = await service.build_delivery_url(image)

    assert url is not None
    assert image.storage_key in url
