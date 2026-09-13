"""Tests for product persistence.

Persistence tests live in `tests/crud/` because that is the layer under test, mirroring
`src/ahia/crud/product_crud.py`. (The device and category slices put their persistence
tests inside their model test modules; this is the arrangement the house layout
actually asks for, and the catalogue follows it from here.)

Most of what matters is enforced by the database rather than by the service: per-tenant
slug uniqueness, SKU and barcode uniqueness *only when a value is present*, and the
composite `(id, tenant_id)` pair a later cross-tenant foreign key will reference.
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

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.errors import ConflictError, NotFoundError
from ahia.crud import category_crud, product_crud, tenant_crud
from ahia.models.entities.category_model import CategoryModel
from ahia.models.entities.product_model import ProductModel
from ahia.models.entities.tenant_model import TenantModel

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)


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
        await connection.execute(text("TRUNCATE TABLE products, categories, tenants CASCADE"))
    try:
        yield instance
    finally:
        await instance.dispose()


def build_product(**overrides: object) -> ProductModel:
    parameters: dict[str, object] = {
        "product_id": uuid4(),
        "tenant_id": uuid4(),
        "name": "Coca Cola 50cl",
        "selling_price": Decimal("250.00"),
        "now": NOW,
        "sku": f"SKU-{uuid4().hex[:8].upper()}",
        "barcode": None,
        "cost_price": Decimal("180.00"),
    }
    parameters.update(overrides)
    return ProductModel.create(**parameters)  # type: ignore[arg-type]


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


async def insert_category(database: Database, *, tenant_id: UUID, name: str = "Drinks") -> UUID:
    category = CategoryModel.create(category_id=uuid4(), tenant_id=tenant_id, name=name, now=NOW)
    async with database.transaction_scope() as unit_of_work:
        await category_crud.create(unit_of_work.session_handle, category)
        await unit_of_work.commit()
    return category.id


@pytest.fixture
async def tenant_id(database: Database) -> UUID:
    identifier = uuid4()
    await insert_tenant(database, identifier)
    return identifier


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_product_round_trips_every_field(database: Database, tenant_id: UUID) -> None:
    category_id = await insert_category(database, tenant_id=tenant_id)
    product = build_product(
        tenant_id=tenant_id,
        category_id=category_id,
        name="Coca Cola 50cl",
        description="Chilled bottle",
        barcode="5449000000996",
        low_stock_threshold=Decimal("12.000"),
    )

    async with database.transaction_scope() as unit_of_work:
        created = await product_crud.create(unit_of_work.session_handle, product)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        stored = await product_crud.require_by_id(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=product.id
        )

    assert created == product
    assert stored == product


@pytest.mark.integration
async def test_prices_survive_the_database_as_decimals(database: Database, tenant_id: UUID) -> None:
    """A price read back is the price that was stored, to the kobo."""
    product = build_product(
        tenant_id=tenant_id,
        selling_price=Decimal("1234.56"),
        cost_price=Decimal("999.99"),
        low_stock_threshold=Decimal("0.500"),
    )

    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(unit_of_work.session_handle, product)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        stored = await product_crud.require_by_id(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=product.id
        )

    assert stored.selling_price == Decimal("1234.56")
    assert str(stored.selling_price) == "1234.56"
    assert stored.cost_price == Decimal("999.99")
    assert stored.low_stock_threshold == Decimal("0.500")
    assert isinstance(stored.selling_price, Decimal)


@pytest.mark.integration
async def test_a_null_cost_stays_null(database: Database, tenant_id: UUID) -> None:
    product = build_product(tenant_id=tenant_id, cost_price=None)

    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(unit_of_work.session_handle, product)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        stored = await product_crud.require_by_id(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=product.id
        )

    assert stored.cost_price is None


# ---------------------------------------------------------------------------
# Per-tenant uniqueness
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_same_name_twice_in_one_business_is_a_conflict(
    database: Database, tenant_id: UUID
) -> None:
    first = build_product(tenant_id=tenant_id, name="Coca Cola 50cl")

    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(unit_of_work.session_handle, first)
        await unit_of_work.commit()

    with pytest.raises(ConflictError) as captured:
        async with database.transaction_scope() as unit_of_work:
            await product_crud.create(
                unit_of_work.session_handle,
                build_product(tenant_id=tenant_id, name="  coca cola 50cl  "),
            )

    assert "name already exists" in (captured.value.context.detail or "")


@pytest.mark.integration
async def test_the_same_name_is_free_in_another_business(database: Database) -> None:
    first = build_product(name="Coca Cola 50cl")
    second = build_product(name="Coca Cola 50cl")
    await insert_tenant(database, first.tenant_id)
    await insert_tenant(database, second.tenant_id)

    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(unit_of_work.session_handle, first)
        await product_crud.create(unit_of_work.session_handle, second)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        listed = await product_crud.list_for_tenant(unit_of_work.session_handle, first.tenant_id)

    assert len(listed) == 1


@pytest.mark.integration
async def test_a_sku_can_be_reused_twice_in_one_business(
    database: Database, tenant_id: UUID
) -> None:
    """A business that does not use SKUs must be able to leave the column empty."""
    for _ in range(2):
        async with database.transaction_scope() as unit_of_work:
            await product_crud.create(
                unit_of_work.session_handle,
                build_product(tenant_id=tenant_id, name=f"Product {uuid4().hex[:6]}", sku=None),
            )
            await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        assert await product_crud.count_for_tenant(unit_of_work.session_handle, tenant_id) == 2


@pytest.mark.integration
async def test_a_duplicate_sku_in_one_business_names_the_sku(
    database: Database, tenant_id: UUID
) -> None:
    shared_sku = f"SKU-{uuid4().hex[:8].upper()}"
    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(
            unit_of_work.session_handle,
            build_product(tenant_id=tenant_id, name="First", sku=shared_sku),
        )
        await unit_of_work.commit()

    with pytest.raises(ConflictError) as captured:
        async with database.transaction_scope() as unit_of_work:
            await product_crud.create(
                unit_of_work.session_handle,
                build_product(tenant_id=tenant_id, name="Second", sku=shared_sku),
            )

    assert "SKU" in (captured.value.context.detail or "")


@pytest.mark.integration
async def test_a_barcode_is_unique_only_when_present(database: Database) -> None:
    first = build_product(barcode=None)
    second = build_product(barcode=None)
    await insert_tenant(database, first.tenant_id)
    await insert_tenant(database, second.tenant_id)

    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(unit_of_work.session_handle, first)
        await product_crud.create(unit_of_work.session_handle, second)
        await unit_of_work.commit()


@pytest.mark.integration
async def test_a_duplicate_barcode_in_one_business_names_the_barcode(
    database: Database, tenant_id: UUID
) -> None:
    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(
            unit_of_work.session_handle,
            build_product(tenant_id=tenant_id, name="First", barcode="5449000000996"),
        )
        await unit_of_work.commit()

    with pytest.raises(ConflictError) as captured:
        async with database.transaction_scope() as unit_of_work:
            await product_crud.create(
                unit_of_work.session_handle,
                build_product(tenant_id=tenant_id, name="Second", barcode="5449000000996"),
            )

    assert "barcode" in (captured.value.context.detail or "")


@pytest.mark.integration
async def test_the_same_barcode_is_free_in_another_business(database: Database) -> None:
    first = build_product(barcode="5449000000996")
    second = build_product(barcode="5449000000996")
    await insert_tenant(database, first.tenant_id)
    await insert_tenant(database, second.tenant_id)

    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(unit_of_work.session_handle, first)
        await product_crud.create(unit_of_work.session_handle, second)
        await unit_of_work.commit()


@pytest.mark.integration
async def test_a_public_token_cannot_be_shared_between_products(
    database: Database, tenant_id: UUID
) -> None:
    """Two published products may not answer to the same public link."""
    shared_token = f"tok_{uuid4().hex}"
    first = build_product(tenant_id=tenant_id, name="First").publish(
        public_token=shared_token, at=NOW
    )
    second = build_product(tenant_id=tenant_id, name="Second").publish(
        public_token=shared_token, at=NOW
    )

    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(unit_of_work.session_handle, first)
        await unit_of_work.commit()

    with pytest.raises(ConflictError) as captured:
        async with database.transaction_scope() as unit_of_work:
            await product_crud.create(unit_of_work.session_handle, second)

    assert "public token" in (captured.value.context.detail or "")


@pytest.mark.integration
async def test_unpublished_products_hold_no_token_at_all(
    database: Database, tenant_id: UUID
) -> None:
    """Nullable and unique: PostgreSQL allows many nulls, which is what makes it work."""
    for index in range(3):
        async with database.transaction_scope() as unit_of_work:
            await product_crud.create(
                unit_of_work.session_handle,
                build_product(tenant_id=tenant_id, name=f"Product {index}"),
            )
            await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        listed = await product_crud.list_for_tenant(unit_of_work.session_handle, tenant_id)

    assert [product.public_token for product in listed] == [None, None, None]


# ---------------------------------------------------------------------------
# The composite anchor
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_anchor_a_cross_tenant_key_references_exists(
    database: Database, tenant_id: UUID
) -> None:
    """The pair `(id, tenant_id)` must be declared unique, or no key can reference it.

    Checked against the catalogue rather than by inserting a duplicate row: a duplicate
    identifier violates the primary key first, so an insert cannot distinguish "the
    anchor is missing" from "the id is duplicated". The composite foreign key from
    products to categories is the anchor working in practice; this checks it is declared.
    """
    async with database.engine.begin() as connection:
        result = await connection.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'products'::regclass AND contype = 'u'"
            )
        )
        unique_constraints = {str(row[0]) for row in result.all()}

    assert "uq_products_id_tenant_id" in unique_constraints


@pytest.mark.integration
async def test_a_product_cannot_reference_another_businesss_category(
    database: Database, tenant_id: UUID
) -> None:
    """The database refuses the cross-tenant reference, not only the service.

    A plain foreign key on `category_id` would accept this: the category exists, so the
    reference is valid everywhere. The composite key on `(category_id, tenant_id)` is
    what makes it invalid, which is exactly why it exists.
    """
    other_tenant = uuid4()
    await insert_tenant(database, other_tenant)
    foreign_category = await insert_category(database, tenant_id=other_tenant, name="Theirs")

    with pytest.raises(NotFoundError) as captured:
        async with database.transaction_scope() as unit_of_work:
            await product_crud.create(
                unit_of_work.session_handle,
                build_product(tenant_id=tenant_id, category_id=foreign_category),
            )

    # The category exists in another business, so this is reported as a missing
    # reference: a caller learns nothing about another tenant's rows either way.
    assert "does not exist" in (captured.value.context.detail or "")


@pytest.mark.integration
async def test_a_product_for_an_unknown_business_is_refused(database: Database) -> None:
    with pytest.raises(NotFoundError):
        async with database.transaction_scope() as unit_of_work:
            await product_crud.create(unit_of_work.session_handle, build_product())


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_product_cannot_be_read_through_another_business(
    database: Database, tenant_id: UUID
) -> None:
    product = build_product(tenant_id=tenant_id)

    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(unit_of_work.session_handle, product)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        elsewhere = await product_crud.get_by_id(
            unit_of_work.session_handle, tenant_id=uuid4(), product_id=product.id
        )
        by_slug = await product_crud.get_by_slug(
            unit_of_work.session_handle, tenant_id=uuid4(), slug=product.slug
        )

    assert elsewhere is None
    assert by_slug is None


@pytest.mark.integration
async def test_lookup_by_slug_is_tenant_scoped(database: Database, tenant_id: UUID) -> None:
    product = build_product(tenant_id=tenant_id, name="Coca Cola 50cl")

    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(unit_of_work.session_handle, product)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        found = await product_crud.get_by_slug(
            unit_of_work.session_handle, tenant_id=tenant_id, slug="coca-cola-50cl"
        )

    assert found is not None and found.id == product.id


@pytest.mark.integration
async def test_a_public_token_finds_its_product_without_a_tenant(
    database: Database, tenant_id: UUID
) -> None:
    """A storefront link is the address; the visitor does not know the business."""
    token = f"tok_{uuid4().hex}"
    product = build_product(tenant_id=tenant_id).publish(public_token=token, at=NOW)

    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(unit_of_work.session_handle, product)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        found = await product_crud.get_by_public_token(unit_of_work.session_handle, token)
        missing = await product_crud.get_by_public_token(unit_of_work.session_handle, "nope")

    assert found is not None and found.id == product.id
    assert missing is None


@pytest.mark.integration
async def test_listing_is_ordered_by_name(database: Database, tenant_id: UUID) -> None:
    for name in ("Sugar", "Bread", "Apple"):
        async with database.transaction_scope() as unit_of_work:
            await product_crud.create(
                unit_of_work.session_handle, build_product(tenant_id=tenant_id, name=name)
            )
            await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        listed = await product_crud.list_for_tenant(unit_of_work.session_handle, tenant_id)

    assert [product.name for product in listed] == ["Apple", "Bread", "Sugar"]


@pytest.mark.integration
async def test_listing_can_leave_out_the_withdrawn_products(
    database: Database, tenant_id: UUID
) -> None:
    async with database.transaction_scope() as unit_of_work:
        for name in ("Kept", "Retired"):
            await product_crud.create(
                unit_of_work.session_handle, build_product(tenant_id=tenant_id, name=name)
            )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        stored = await product_crud.get_by_slug(
            unit_of_work.session_handle, tenant_id=tenant_id, slug="retired"
        )
        assert stored is not None
        await product_crud.update(unit_of_work.session_handle, stored.deactivate(at=NOW))
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        everything = await product_crud.list_for_tenant(unit_of_work.session_handle, tenant_id)
        active_only = await product_crud.list_for_tenant(
            unit_of_work.session_handle, tenant_id, include_inactive=False
        )

    assert [product.name for product in everything] == ["Kept", "Retired"]
    assert [product.name for product in active_only] == ["Kept"]


@pytest.mark.integration
async def test_the_storefront_listing_carries_only_visible_products(
    database: Database, tenant_id: UUID
) -> None:
    hidden = build_product(tenant_id=tenant_id, name="Hidden")
    published = build_product(tenant_id=tenant_id, name="Published").publish(
        public_token=f"tok_{uuid4().hex}", at=NOW
    )
    retired = (
        build_product(tenant_id=tenant_id, name="Retired")
        .publish(public_token=f"tok_{uuid4().hex}", at=NOW)
        .deactivate(at=NOW)
    )

    async with database.transaction_scope() as unit_of_work:
        for product in (hidden, published, retired):
            await product_crud.create(unit_of_work.session_handle, product)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        visible = await product_crud.list_published_for_tenant(
            unit_of_work.session_handle, tenant_id
        )

    assert [product.name for product in visible] == ["Published"]


# ---------------------------------------------------------------------------
# Updates
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_an_update_persists_prices_identifiers_and_the_lifecycle(
    database: Database, tenant_id: UUID
) -> None:
    product = build_product(tenant_id=tenant_id, name="Coca Cola 50cl")
    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(unit_of_work.session_handle, product)
        await unit_of_work.commit()

    later = NOW + timedelta(days=1)
    changed = (
        product.renamed(name="Coke 50cl", at=later)
        .repriced(selling_price=Decimal("275.00"), cost_price=None, at=later)
        .identified(sku=None, barcode="5449000000996", at=later)
        .publish(public_token=f"tok_{uuid4().hex}", at=later)
    )

    async with database.transaction_scope() as unit_of_work:
        stored = await product_crud.update(unit_of_work.session_handle, changed)
        await unit_of_work.commit()

    assert stored.name == "Coke 50cl"
    assert stored.slug == "coca-cola-50cl", "the public handle does not move with a rename"
    assert stored.selling_price == Decimal("275.00")
    assert stored.cost_price is None
    assert stored.sku is None
    assert stored.barcode == "5449000000996"
    assert stored.is_published is True

    async with database.transaction_scope() as unit_of_work:
        reread = await product_crud.require_by_id(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=product.id
        )

    assert reread == stored


@pytest.mark.integration
async def test_an_update_cannot_reach_another_businesss_product(
    database: Database, tenant_id: UUID
) -> None:
    product = build_product(tenant_id=tenant_id)
    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(unit_of_work.session_handle, product)
        await unit_of_work.commit()

    stranger = ProductModel(
        id=product.id,
        tenant_id=uuid4(),
        name="Mine now",
        slug="mine-now",
        selling_price=Decimal("1.00"),
        created_at=NOW,
        updated_at=NOW,
    )

    with pytest.raises(NotFoundError):
        async with database.transaction_scope() as unit_of_work:
            await product_crud.update(unit_of_work.session_handle, stranger)


@pytest.mark.integration
async def test_renaming_onto_a_taken_name_does_not_collide(
    database: Database, tenant_id: UUID
) -> None:
    """The slug is stable, so a rename cannot collide with another product's slug.

    This is the property that makes a rename safe at any time: the handle other things
    point at never moves, so the uniqueness rule is never consulted again. A business
    may end up with two products whose names read similarly, which is a naming decision
    rather than a database state.
    """
    async with database.transaction_scope() as unit_of_work:
        for name in ("Sugar", "Bread"):
            await product_crud.create(
                unit_of_work.session_handle, build_product(tenant_id=tenant_id, name=name)
            )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        bread = await product_crud.get_by_slug(
            unit_of_work.session_handle, tenant_id=tenant_id, slug="bread"
        )
        assert bread is not None
        renamed = await product_crud.update(
            unit_of_work.session_handle, bread.renamed(name="Sugar", at=NOW)
        )
        await unit_of_work.commit()

    assert renamed.name == "Sugar"
    assert renamed.slug == "bread"

    async with database.transaction_scope() as unit_of_work:
        assert await product_crud.count_for_tenant(unit_of_work.session_handle, tenant_id) == 2


@pytest.mark.integration
async def test_taking_another_products_sku_is_a_conflict(
    database: Database, tenant_id: UUID
) -> None:
    """The codes do move when edited, so the uniqueness rule is enforced on update too."""
    shared_sku = f"SKU-{uuid4().hex[:8].upper()}"
    async with database.transaction_scope() as unit_of_work:
        taken = await product_crud.create(
            unit_of_work.session_handle,
            build_product(tenant_id=tenant_id, name="First", sku=shared_sku),
        )
        await product_crud.create(
            unit_of_work.session_handle,
            build_product(tenant_id=tenant_id, name="Second", sku=None),
        )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        second = await product_crud.get_by_slug(
            unit_of_work.session_handle, tenant_id=tenant_id, slug="second"
        )
        assert second is not None
        assert taken.sku == shared_sku

        with pytest.raises(ConflictError) as captured:
            await product_crud.update(
                unit_of_work.session_handle,
                second.identified(sku=shared_sku, barcode=None, at=NOW),
            )

    assert "SKU" in (captured.value.context.detail or "")


@pytest.mark.integration
async def test_require_by_id_names_the_missing_product(database: Database, tenant_id: UUID) -> None:
    with pytest.raises(NotFoundError, match="no product matched"):
        async with database.transaction_scope() as unit_of_work:
            await product_crud.require_by_id(
                unit_of_work.session_handle, tenant_id=tenant_id, product_id=uuid4()
            )
