"""Tests for product image persistence.

Persistence tests live in `tests/crud/`, mirroring the layer under test. Most of what
matters here is enforced by the database rather than by a service: the composite product
reference that keeps tenants apart, at most one primary image per product, the unique
object key, and the partial index that lets a removal be retried.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.errors import ConflictError, NotFoundError
from ahia.crud import product_crud, product_image_crud, tenant_crud
from ahia.models.entities.product_image_model import ProductImageModel
from ahia.models.entities.product_model import ProductModel
from ahia.models.entities.tenant_model import TenantModel

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)
CHECKSUM = "b" * 64


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
            text("TRUNCATE TABLE product_images, products, categories, tenants CASCADE")
        )
    try:
        yield instance
    finally:
        await instance.dispose()


def build_image(**overrides: object) -> ProductImageModel:
    tenant_id = overrides.get("tenant_id") or uuid4()
    product_id = overrides.get("product_id") or uuid4()
    image_id = overrides.get("image_id") or uuid4()
    parameters: dict[str, object] = {
        "image_id": image_id,
        "tenant_id": tenant_id,
        "product_id": product_id,
        "storage_provider": "r2",
        "storage_key": f"tenants/{tenant_id}/products/{product_id}/{image_id}",
        "mime_type": "image/webp",
        "size_bytes": 8_192,
        "width": 800,
        "height": 600,
        "checksum_sha256": CHECKSUM,
        "sort_order": 0,
        "now": NOW,
        "is_primary": False,
    }
    parameters.update(overrides)
    return ProductImageModel.create(**parameters)  # type: ignore[arg-type]


async def insert_product(
    database: Database, tenant_id: UUID, *, name: str = "Coca Cola 50cl"
) -> UUID:
    product = ProductModel.create(
        product_id=uuid4(),
        tenant_id=tenant_id,
        name=name,
        selling_price=Decimal("250.00"),
        now=NOW,
    )
    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(unit_of_work.session_handle, product)
        await unit_of_work.commit()
    return product.id


@pytest.fixture
async def tenant_id(database: Database) -> UUID:
    identifier = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await tenant_crud.create(
            unit_of_work.session_handle,
            TenantModel.create(
                tenant_id=identifier,
                name=f"Tenant {identifier.hex[:6]}",
                slug=f"tenant-{identifier.hex[:8]}",
                now=NOW,
            ),
        )
        await unit_of_work.commit()
    return identifier


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_an_image_round_trips_every_field(database: Database, tenant_id: UUID) -> None:
    product_id = await insert_product(database, tenant_id)
    image = build_image(
        tenant_id=tenant_id,
        product_id=product_id,
        storage_provider="cloudinary-ish",
        mime_type="image/avif",
        size_bytes=12_345,
        width=1_200,
        height=900,
        sort_order=3,
        is_primary=True,
    )

    async with database.transaction_scope() as unit_of_work:
        created = await product_image_crud.create(unit_of_work.session_handle, image)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        stored = await product_image_crud.require_by_id(
            unit_of_work.session_handle, tenant_id=tenant_id, image_id=image.id
        )

    assert created == image
    assert stored == image
    assert stored.storage_provider == "cloudinary-ish"
    assert stored.size_bytes == 12_345


@pytest.mark.integration
async def test_the_row_carries_the_provider_that_holds_the_bytes(
    database: Database, tenant_id: UUID
) -> None:
    """The provider is a value per row, which is what makes a switch safe."""
    product_id = await insert_product(database, tenant_id)
    first = build_image(tenant_id=tenant_id, product_id=product_id, storage_provider="alpha")
    second = build_image(
        tenant_id=tenant_id,
        product_id=product_id,
        storage_provider="beta",
        sort_order=1,
    )

    async with database.transaction_scope() as unit_of_work:
        await product_image_crud.create(unit_of_work.session_handle, first)
        await product_image_crud.create(unit_of_work.session_handle, second)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        gallery = await product_image_crud.list_for_product(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=product_id
        )

    assert {image.storage_provider for image in gallery} == {"alpha", "beta"}


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_an_image_cannot_belong_to_another_businesss_product(
    database: Database, tenant_id: UUID
) -> None:
    """The composite product reference refuses it, not only the service."""
    other_tenant = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await tenant_crud.create(
            unit_of_work.session_handle,
            TenantModel.create(
                tenant_id=other_tenant,
                name="Other",
                slug=f"tenant-{other_tenant.hex[:8]}",
                now=NOW,
            ),
        )
        await unit_of_work.commit()
    foreign_product = await insert_product(database, other_tenant, name="Theirs")

    with pytest.raises(NotFoundError) as captured:
        async with database.transaction_scope() as unit_of_work:
            await product_image_crud.create(
                unit_of_work.session_handle,
                build_image(tenant_id=tenant_id, product_id=foreign_product),
            )

    assert "does not exist" in (captured.value.context.detail or "")


@pytest.mark.integration
async def test_an_image_cannot_be_read_through_another_business(
    database: Database, tenant_id: UUID
) -> None:
    product_id = await insert_product(database, tenant_id)
    image = build_image(tenant_id=tenant_id, product_id=product_id)

    async with database.transaction_scope() as unit_of_work:
        await product_image_crud.create(unit_of_work.session_handle, image)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        elsewhere = await product_image_crud.get_by_id(
            unit_of_work.session_handle, tenant_id=uuid4(), image_id=image.id
        )

    assert elsewhere is None


# ---------------------------------------------------------------------------
# Primary image
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_product_cannot_have_two_primary_images(
    database: Database, tenant_id: UUID
) -> None:
    product_id = await insert_product(database, tenant_id)

    async with database.transaction_scope() as unit_of_work:
        await product_image_crud.create(
            unit_of_work.session_handle,
            build_image(tenant_id=tenant_id, product_id=product_id, is_primary=True),
        )
        await unit_of_work.commit()

    with pytest.raises(ConflictError) as captured:
        async with database.transaction_scope() as unit_of_work:
            await product_image_crud.create(
                unit_of_work.session_handle,
                build_image(
                    tenant_id=tenant_id, product_id=product_id, is_primary=True, sort_order=1
                ),
            )

    assert "primary image" in (captured.value.context.detail or "")


@pytest.mark.integration
async def test_a_removed_primary_image_does_not_block_a_new_one(
    database: Database, tenant_id: UUID
) -> None:
    """The index predicate excludes removed rows, so replacing the cover works."""
    product_id = await insert_product(database, tenant_id)
    first = build_image(tenant_id=tenant_id, product_id=product_id, is_primary=True)

    async with database.transaction_scope() as unit_of_work:
        stored = await product_image_crud.create(unit_of_work.session_handle, first)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        await product_image_crud.update(unit_of_work.session_handle, stored.removed(at=LATER))
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        replacement = await product_image_crud.create(
            unit_of_work.session_handle,
            build_image(tenant_id=tenant_id, product_id=product_id, is_primary=True),
        )
        await unit_of_work.commit()

    assert replacement.is_primary is True


@pytest.mark.integration
async def test_two_products_may_each_have_a_primary_image(
    database: Database, tenant_id: UUID
) -> None:
    first_product = await insert_product(database, tenant_id, name="First")
    second_product = await insert_product(database, tenant_id, name="Second")

    async with database.transaction_scope() as unit_of_work:
        await product_image_crud.create(
            unit_of_work.session_handle,
            build_image(tenant_id=tenant_id, product_id=first_product, is_primary=True),
        )
        await product_image_crud.create(
            unit_of_work.session_handle,
            build_image(tenant_id=tenant_id, product_id=second_product, is_primary=True),
        )
        await unit_of_work.commit()


@pytest.mark.integration
async def test_a_removed_image_cannot_be_made_primary_by_the_database(
    database: Database, tenant_id: UUID
) -> None:
    """The entity refuses it first; the partial index would also refuse it."""
    product_id = await insert_product(database, tenant_id)
    image = build_image(tenant_id=tenant_id, product_id=product_id)

    async with database.transaction_scope() as unit_of_work:
        stored = await product_image_crud.create(unit_of_work.session_handle, image)
        await unit_of_work.commit()

    with pytest.raises(IntegrityError) as captured:
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE product_images SET is_primary = true, removed_at = now() "
                    "WHERE id = :image_id"
                ),
                {"image_id": str(stored.id)},
            )

    # The entity's rule and the index predicate agree, which is the point: the check
    # has one meaning whether it is made in Python or in PostgreSQL.
    assert "uq_product_images_primary" in str(captured.value) or "removed_at" in str(captured.value)


# ---------------------------------------------------------------------------
# The stored object
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_two_rows_cannot_claim_the_same_stored_object(
    database: Database, tenant_id: UUID
) -> None:
    product_id = await insert_product(database, tenant_id)
    shared_key = f"tenants/{tenant_id}/products/{product_id}/shared"

    async with database.transaction_scope() as unit_of_work:
        await product_image_crud.create(
            unit_of_work.session_handle,
            build_image(tenant_id=tenant_id, product_id=product_id, storage_key=shared_key),
        )
        await unit_of_work.commit()

    with pytest.raises(ConflictError) as captured:
        async with database.transaction_scope() as unit_of_work:
            await product_image_crud.create(
                unit_of_work.session_handle,
                build_image(
                    tenant_id=tenant_id,
                    product_id=product_id,
                    storage_key=shared_key,
                    sort_order=1,
                ),
            )

    assert "stored object" in (captured.value.context.detail or "")


# ---------------------------------------------------------------------------
# Gallery listing
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_gallery_is_ordered_by_position(database: Database, tenant_id: UUID) -> None:
    product_id = await insert_product(database, tenant_id)

    async with database.transaction_scope() as unit_of_work:
        for position in (2, 0, 1):
            await product_image_crud.create(
                unit_of_work.session_handle,
                build_image(tenant_id=tenant_id, product_id=product_id, sort_order=position),
            )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        gallery = await product_image_crud.list_for_product(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=product_id
        )

    assert [image.sort_order for image in gallery] == [0, 1, 2]


@pytest.mark.integration
async def test_removed_images_leave_the_gallery_and_the_count(
    database: Database, tenant_id: UUID
) -> None:
    product_id = await insert_product(database, tenant_id)

    async with database.transaction_scope() as unit_of_work:
        kept = await product_image_crud.create(
            unit_of_work.session_handle,
            build_image(tenant_id=tenant_id, product_id=product_id, sort_order=0),
        )
        removed = await product_image_crud.create(
            unit_of_work.session_handle,
            build_image(tenant_id=tenant_id, product_id=product_id, sort_order=1),
        )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        await product_image_crud.update(unit_of_work.session_handle, removed.removed(at=LATER))
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        gallery = await product_image_crud.list_for_product(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=product_id
        )
        everything = await product_image_crud.list_for_product(
            unit_of_work.session_handle,
            tenant_id=tenant_id,
            product_id=product_id,
            include_removed=True,
        )
        count = await product_image_crud.count_for_product(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=product_id
        )

    assert [image.id for image in gallery] == [kept.id]
    assert len(everything) == 2
    assert count == 1


@pytest.mark.integration
async def test_a_failed_delete_is_findable_for_reconciliation(
    database: Database, tenant_id: UUID
) -> None:
    """A row marked for reconciliation is how a leaked object stays discoverable."""
    product_id = await insert_product(database, tenant_id)

    async with database.transaction_scope() as unit_of_work:
        image = await product_image_crud.create(
            unit_of_work.session_handle,
            build_image(tenant_id=tenant_id, product_id=product_id),
        )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        await product_image_crud.update(
            unit_of_work.session_handle,
            image.removed(at=LATER, reconciliation_reason="provider delete failed"),
        )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        pending = await product_image_crud.list_pending_reconciliation(
            unit_of_work.session_handle, tenant_id
        )

    assert [entry.id for entry in pending] == [image.id]
    assert pending[0].needs_reconciliation() is True


@pytest.mark.integration
async def test_reconciliation_is_scoped_to_the_business(
    database: Database, tenant_id: UUID
) -> None:
    product_id = await insert_product(database, tenant_id)

    async with database.transaction_scope() as unit_of_work:
        image = await product_image_crud.create(
            unit_of_work.session_handle,
            build_image(tenant_id=tenant_id, product_id=product_id),
        )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        await product_image_crud.update(
            unit_of_work.session_handle,
            image.removed(at=LATER, reconciliation_reason="provider delete failed"),
        )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        elsewhere = await product_image_crud.list_pending_reconciliation(
            unit_of_work.session_handle, uuid4()
        )

    assert elsewhere == []


@pytest.mark.integration
async def test_a_confirmed_deletion_removes_the_row(database: Database, tenant_id: UUID) -> None:
    product_id = await insert_product(database, tenant_id)

    async with database.transaction_scope() as unit_of_work:
        image = await product_image_crud.create(
            unit_of_work.session_handle,
            build_image(tenant_id=tenant_id, product_id=product_id),
        )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        await product_image_crud.delete_row(unit_of_work.session_handle, image)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        assert (
            await product_image_crud.get_by_id(
                unit_of_work.session_handle, tenant_id=tenant_id, image_id=image.id
            )
            is None
        )


@pytest.mark.integration
async def test_deleting_another_businesss_row_is_refused(
    database: Database, tenant_id: UUID
) -> None:
    product_id = await insert_product(database, tenant_id)

    async with database.transaction_scope() as unit_of_work:
        image = await product_image_crud.create(
            unit_of_work.session_handle,
            build_image(tenant_id=tenant_id, product_id=product_id),
        )
        await unit_of_work.commit()

    stranger = ProductImageModel(
        id=image.id,
        tenant_id=uuid4(),
        product_id=product_id,
        storage_provider=image.storage_provider,
        storage_key=image.storage_key,
        mime_type=image.mime_type,
        size_bytes=image.size_bytes,
        width=image.width,
        height=image.height,
        checksum_sha256=image.checksum_sha256,
        sort_order=image.sort_order,
        created_at=NOW,
    )

    with pytest.raises(NotFoundError):
        async with database.transaction_scope() as unit_of_work:
            await product_image_crud.delete_row(unit_of_work.session_handle, stranger)


@pytest.mark.integration
async def test_updating_a_missing_image_is_a_typed_not_found(
    database: Database, tenant_id: UUID
) -> None:
    with pytest.raises(NotFoundError, match="no image matched"):
        async with database.transaction_scope() as unit_of_work:
            await product_image_crud.update(
                unit_of_work.session_handle, build_image(tenant_id=tenant_id)
            )
