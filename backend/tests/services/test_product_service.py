"""Tests for the product use cases.

Integration tests against real PostgreSQL, because the rules worth testing are the
database's (per-tenant codes, the composite category reference) and the ones
authorization decides.

The authorization block at the end is the security part, and it calls the service
directly - the way a CLI command or a scheduled job would - rather than through HTTP,
where a router-level check could hide a missing one.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.errors import (
    AuthorizationError,
    ConflictError,
    EntityInvariantError,
    InvalidInputError,
    NotFoundError,
)
from ahia.core.permissions.permissions_registry import permission_codes_for_role
from ahia.core.security import TokenService
from ahia.core.tenant_context import TenantContext, build_tenant_context
from ahia.crud import audit_event_crud, category_crud, tenant_crud
from ahia.models.entities.category_model import CategoryModel
from ahia.models.entities.product_model import ProductModel
from ahia.models.entities.tenant_model import TenantModel
from ahia.services.audit_event_service import AuditEventService
from ahia.services.product_service import ProductService

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)


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


def build_token_service() -> TokenService:
    return TokenService(
        secret="test-signing-secret-value-0000000001",
        algorithm="HS256",
        issuer="ahia-api",
        audience="ahia-clients",
        access_token_ttl_minutes=15,
        refresh_token_pepper="test-refresh-pepper-value-00000000011",
        public_token_bytes=24,
    )


@pytest.fixture
def service(database: Database) -> ProductService:
    return ProductService(
        unit_of_work_factory=database.unit_of_work_factory(),
        token_service=build_token_service(),
        audit_event_service=AuditEventService(unit_of_work_factory=database.unit_of_work_factory()),
    )


async def insert_tenant(database: Database, tenant_id: UUID) -> None:
    async with database.transaction_scope() as unit_of_work:
        await tenant_crud.create(
            unit_of_work.session_handle,
            TenantModel.create(
                tenant_id=tenant_id,
                name=f"Tenant {tenant_id.hex[:6]}",
                slug=f"tenant-{tenant_id.hex[:8]}",
                now=datetime.now(UTC),
            ),
        )
        await unit_of_work.commit()


async def insert_category(database: Database, *, tenant_id: UUID, name: str = "Drinks") -> UUID:
    category = CategoryModel.create(
        category_id=uuid4(), tenant_id=tenant_id, name=name, now=UTC_NOW
    )
    async with database.transaction_scope() as unit_of_work:
        await category_crud.create(unit_of_work.session_handle, category)
        await unit_of_work.commit()
    return category.id


UTC_NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)


@pytest.fixture
async def tenant_id(database: Database) -> UUID:
    identifier = uuid4()
    await insert_tenant(database, identifier)
    return identifier


def context_for(tenant_id: UUID, role_name: str) -> TenantContext:
    return build_tenant_context(
        user_id=uuid4(),
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=permission_codes_for_role(role_name),
        role_name=role_name,
    )


def owner_context(tenant_id: UUID) -> TenantContext:
    return context_for(tenant_id, "OWNER")


def manager_context(tenant_id: UUID) -> TenantContext:
    return context_for(tenant_id, "MANAGER")


def sales_context(tenant_id: UUID) -> TenantContext:
    return context_for(tenant_id, "SALES")


async def create_one(
    service: ProductService,
    tenant_id: UUID,
    *,
    name: str = "Coca Cola 50cl",
    **overrides: Any,
) -> ProductModel:
    arguments: dict[str, Any] = {
        "name": name,
        "selling_price": Decimal("250.00"),
        "cost_price": Decimal("180.00"),
    }
    arguments.update(overrides)
    return await service.create_product(owner_context(tenant_id), **arguments)


# ---------------------------------------------------------------------------
# Creating
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_creating_a_product_derives_its_slug_and_starts_it_hidden(
    service: ProductService, tenant_id: UUID
) -> None:
    product = await create_one(service, tenant_id, name="Coca Cola 50cl", sku="cc-50")

    assert product.slug == "coca-cola-50cl"
    assert product.sku == "CC-50"
    assert product.tenant_id == tenant_id
    assert product.is_active is True
    assert product.is_published is False
    assert product.public_token is None
    assert product.low_stock_threshold == Decimal("0.000")


@pytest.mark.integration
async def test_a_category_from_this_business_is_accepted(
    database: Database, service: ProductService, tenant_id: UUID
) -> None:
    category_id = await insert_category(database, tenant_id=tenant_id)

    product = await create_one(service, tenant_id, category_id=category_id)

    assert product.category_id == category_id


@pytest.mark.integration
async def test_a_category_from_another_business_is_refused(
    database: Database, service: ProductService, tenant_id: UUID
) -> None:
    other_tenant = uuid4()
    await insert_tenant(database, other_tenant)
    foreign_category = await insert_category(database, tenant_id=other_tenant, name="Theirs")

    with pytest.raises(NotFoundError) as captured:
        await create_one(service, tenant_id, category_id=foreign_category)

    assert "no category matched" in (captured.value.context.detail or "")


@pytest.mark.integration
async def test_a_duplicate_name_is_a_conflict(service: ProductService, tenant_id: UUID) -> None:
    await create_one(service, tenant_id, name="Coca Cola 50cl")

    with pytest.raises(ConflictError) as captured:
        await create_one(service, tenant_id, name="  coca cola 50cl  ")

    assert "name already exists" in (captured.value.context.detail or "")


@pytest.mark.integration
async def test_two_businesses_may_each_sell_the_same_named_product(
    database: Database, service: ProductService, tenant_id: UUID
) -> None:
    other_tenant = uuid4()
    await insert_tenant(database, other_tenant)

    first = await create_one(service, tenant_id, name="Coca Cola 50cl")
    second = await create_one(service, other_tenant, name="Coca Cola 50cl")

    assert first.id != second.id
    assert first.slug == second.slug == "coca-cola-50cl"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_catalogue_is_ordered_by_name(service: ProductService, tenant_id: UUID) -> None:
    for name in ("Sugar", "Bread", "Apple"):
        await create_one(service, tenant_id, name=name)

    listed = await service.list_products(owner_context(tenant_id))

    assert [product.name for product in listed] == ["Apple", "Bread", "Sugar"]


@pytest.mark.integration
async def test_withdrawn_products_can_be_left_out(service: ProductService, tenant_id: UUID) -> None:
    kept = await create_one(service, tenant_id, name="Kept")
    retired = await create_one(service, tenant_id, name="Retired")
    await service.deactivate_product(owner_context(tenant_id), product_id=retired.id)

    everything = await service.list_products(owner_context(tenant_id))
    active_only = await service.list_products(owner_context(tenant_id), include_inactive=False)

    assert {product.id for product in everything} == {kept.id, retired.id}
    assert [product.id for product in active_only] == [kept.id]


@pytest.mark.integration
async def test_reading_a_product_from_another_business_is_a_not_found(
    database: Database, service: ProductService, tenant_id: UUID
) -> None:
    other_tenant = uuid4()
    await insert_tenant(database, other_tenant)
    elsewhere = await create_one(service, other_tenant, name="Theirs")

    with pytest.raises(NotFoundError):
        await service.get_product(owner_context(tenant_id), product_id=elsewhere.id)


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_rename_keeps_the_public_handle(service: ProductService, tenant_id: UUID) -> None:
    product = await create_one(service, tenant_id, name="Coca Cola 50cl")

    updated = await service.update_product(
        owner_context(tenant_id), product_id=product.id, changes={"name": "Coke 50cl"}
    )

    assert updated.name == "Coke 50cl"
    assert updated.slug == "coca-cola-50cl"


@pytest.mark.integration
async def test_editing_prices_identifiers_and_threshold(
    service: ProductService, tenant_id: UUID
) -> None:
    product = await create_one(service, tenant_id, sku="CC-50", barcode=None)

    updated = await service.update_product(
        owner_context(tenant_id),
        product_id=product.id,
        changes={
            "selling_price": Decimal("275.50"),
            "cost_price": None,
            "barcode": "5449000000996",
            "low_stock_threshold": Decimal("6.000"),
        },
    )

    assert updated.selling_price == Decimal("275.50")
    assert updated.cost_price is None
    assert updated.sku == "CC-50", "a field that was not sent is left alone"
    assert updated.barcode == "5449000000996"
    assert updated.low_stock_threshold == Decimal("6.000")


@pytest.mark.integration
async def test_a_description_and_a_category_can_be_set_and_cleared(
    database: Database, service: ProductService, tenant_id: UUID
) -> None:
    category_id = await insert_category(database, tenant_id=tenant_id)
    product = await create_one(service, tenant_id, category_id=category_id)

    described = await service.update_product(
        owner_context(tenant_id),
        product_id=product.id,
        changes={"description": "Chilled bottle", "category_id": None},
    )
    cleared = await service.update_product(
        owner_context(tenant_id),
        product_id=product.id,
        changes={"description": None},
    )

    assert described.description == "Chilled bottle"
    assert described.category_id is None
    assert cleared.description is None


@pytest.mark.integration
async def test_filing_a_product_under_another_businesss_category_is_refused(
    database: Database, service: ProductService, tenant_id: UUID
) -> None:
    other_tenant = uuid4()
    await insert_tenant(database, other_tenant)
    foreign_category = await insert_category(database, tenant_id=other_tenant, name="Theirs")
    product = await create_one(service, tenant_id)

    with pytest.raises(NotFoundError):
        await service.update_product(
            owner_context(tenant_id),
            product_id=product.id,
            changes={"category_id": foreign_category},
        )


@pytest.mark.integration
async def test_a_field_the_contract_does_not_own_is_refused(
    service: ProductService, tenant_id: UUID
) -> None:
    product = await create_one(service, tenant_id)

    for forbidden in ({"slug": "coke"}, {"is_published": True}, {"tenant_id": uuid4()}):
        with pytest.raises(InvalidInputError):
            await service.update_product(
                owner_context(tenant_id), product_id=product.id, changes=forbidden
            )


@pytest.mark.integration
async def test_a_value_of_the_wrong_type_is_a_bad_request(
    service: ProductService, tenant_id: UUID
) -> None:
    """The schema validates HTTP; this is what makes the annotation true for every caller."""
    product = await create_one(service, tenant_id)

    with pytest.raises(InvalidInputError, match="selling_price"):
        await service.update_product(
            owner_context(tenant_id),
            product_id=product.id,
            changes={"selling_price": "275.50"},
        )
    with pytest.raises(InvalidInputError, match="sku"):
        await service.update_product(
            owner_context(tenant_id), product_id=product.id, changes={"sku": 12345}
        )


@pytest.mark.integration
async def test_an_empty_change_set_leaves_the_product_untouched(
    service: ProductService, tenant_id: UUID
) -> None:
    product = await create_one(service, tenant_id)

    updated = await service.update_product(
        owner_context(tenant_id), product_id=product.id, changes={}
    )

    assert updated == product


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_publishing_issues_a_public_token(service: ProductService, tenant_id: UUID) -> None:
    product = await create_one(service, tenant_id)

    published = await service.publish_product(owner_context(tenant_id), product_id=product.id)

    assert published.is_published is True
    assert published.public_token
    assert len(published.public_token or "") >= 16
    assert published.is_visible_to_customers() is True


@pytest.mark.integration
async def test_publishing_twice_keeps_the_address_a_customer_already_has(
    service: ProductService, tenant_id: UUID
) -> None:
    product = await create_one(service, tenant_id)
    first = await service.publish_product(owner_context(tenant_id), product_id=product.id)

    second = await service.publish_product(owner_context(tenant_id), product_id=product.id)

    assert second.public_token == first.public_token
    assert second.updated_at == first.updated_at, "an idempotent publish writes nothing"


@pytest.mark.integration
async def test_unpublishing_hides_the_product_and_keeps_its_address(
    service: ProductService, tenant_id: UUID
) -> None:
    product = await create_one(service, tenant_id)
    published = await service.publish_product(owner_context(tenant_id), product_id=product.id)

    hidden = await service.unpublish_product(owner_context(tenant_id), product_id=product.id)

    assert hidden.is_published is False
    assert hidden.is_active is True, "it stays in the catalogue"
    assert hidden.public_token == published.public_token

    republished = await service.publish_product(owner_context(tenant_id), product_id=product.id)
    assert republished.public_token == published.public_token


@pytest.mark.integration
async def test_a_withdrawn_product_cannot_be_published(
    service: ProductService, tenant_id: UUID
) -> None:
    product = await create_one(service, tenant_id)
    await service.deactivate_product(owner_context(tenant_id), product_id=product.id)

    with pytest.raises(EntityInvariantError, match="not active"):
        await service.publish_product(owner_context(tenant_id), product_id=product.id)


@pytest.mark.integration
async def test_deactivating_also_unpublishes(service: ProductService, tenant_id: UUID) -> None:
    product = await create_one(service, tenant_id)
    await service.publish_product(owner_context(tenant_id), product_id=product.id)

    retired = await service.deactivate_product(owner_context(tenant_id), product_id=product.id)

    assert retired.is_active is False
    assert retired.is_published is False


@pytest.mark.integration
async def test_reactivating_returns_the_product_but_not_its_visibility(
    service: ProductService, tenant_id: UUID
) -> None:
    product = await create_one(service, tenant_id)
    await service.publish_product(owner_context(tenant_id), product_id=product.id)
    await service.deactivate_product(owner_context(tenant_id), product_id=product.id)

    revived = await service.activate_product(owner_context(tenant_id), product_id=product.id)

    assert revived.is_active is True
    assert revived.is_published is False


@pytest.mark.integration
async def test_two_products_never_share_a_public_token(
    service: ProductService, tenant_id: UUID
) -> None:
    first = await create_one(service, tenant_id, name="First")
    second = await create_one(service, tenant_id, name="Second")

    published_first = await service.publish_product(owner_context(tenant_id), product_id=first.id)
    published_second = await service.publish_product(owner_context(tenant_id), product_id=second.id)

    assert published_first.public_token != published_second.public_token


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_salesperson_may_read_the_catalogue(
    service: ProductService, tenant_id: UUID
) -> None:
    product = await create_one(service, tenant_id)

    listed = await service.list_products(sales_context(tenant_id))
    one = await service.get_product(sales_context(tenant_id), product_id=product.id)

    assert [entry.id for entry in listed] == [product.id]
    assert one.id == product.id


@pytest.mark.integration
async def test_a_salesperson_may_not_write_to_the_catalogue(
    service: ProductService, tenant_id: UUID
) -> None:
    product = await create_one(service, tenant_id)
    sales = sales_context(tenant_id)

    with pytest.raises(AuthorizationError):
        await service.create_product(sales, name="Snacks", selling_price=Decimal("100.00"))
    with pytest.raises(AuthorizationError):
        await service.update_product(sales, product_id=product.id, changes={"name": "New"})
    with pytest.raises(AuthorizationError):
        await service.publish_product(sales, product_id=product.id)
    with pytest.raises(AuthorizationError):
        await service.unpublish_product(sales, product_id=product.id)
    with pytest.raises(AuthorizationError):
        await service.activate_product(sales, product_id=product.id)


@pytest.mark.integration
async def test_a_manager_may_run_the_catalogue_but_may_not_withdraw_a_product(
    service: ProductService, tenant_id: UUID
) -> None:
    """MANAGER holds create and update, and not delete: withdrawing is the owner's call."""
    manager = manager_context(tenant_id)
    product = await service.create_product(
        manager, name="Coca Cola 50cl", selling_price=Decimal("250.00")
    )
    published = await service.publish_product(manager, product_id=product.id)
    hidden = await service.unpublish_product(manager, product_id=product.id)

    assert published.is_published is True
    assert hidden.is_published is False

    with pytest.raises(AuthorizationError):
        await service.deactivate_product(manager, product_id=product.id)


@pytest.mark.integration
async def test_authorization_is_checked_before_the_database_is_touched(
    service: ProductService, tenant_id: UUID
) -> None:
    """A refused caller cannot use a duplicate name as an oracle for what exists."""
    await create_one(service, tenant_id, name="Coca Cola 50cl")

    with pytest.raises(AuthorizationError):
        await service.create_product(
            sales_context(tenant_id), name="Coca Cola 50cl", selling_price=Decimal("1.00")
        )
    with pytest.raises(AuthorizationError):
        await service.create_product(
            sales_context(tenant_id), name="A Name Nobody Used", selling_price=Decimal("1.00")
        )


# ---------------------------------------------------------------------------
# The trail
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_creating_a_product_is_in_the_audit_trail(
    database: Database, service: ProductService, tenant_id: UUID
) -> None:
    """M14.1.3: the catalogue use cases write their event with the change."""
    context = context_for(tenant_id, "OWNER")
    product = await service.create_product(
        context,
        name="Rice 50kg",
        selling_price=Decimal("45000.00"),
    )

    async with database.transaction_scope() as unit_of_work:
        events = await audit_event_crud.list_for_entity(
            unit_of_work.session_handle,
            tenant_id=tenant_id,
            entity_type="product",
            entity_id=product.id,
        )

    assert [event.action for event in events] == ["create_product"]
    assert events[0].actor_id == context.user_id
    assert events[0].detail["product_slug"] == product.slug
