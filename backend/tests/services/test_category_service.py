"""Tests for the category use cases.

Integration tests against real PostgreSQL, because the rules worth testing are the
ones the database enforces and the ones authorization decides: a duplicate name inside
one business, the same name in another, and a caller who holds `products.read` but not
`products.create`.

The last group is the security part. Authorization lives in this layer on purpose, so
these tests call the service directly - the way a CLI command or a scheduled job would -
rather than going through HTTP, where a router-level check could hide a missing one.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.errors import AuthorizationError, ConflictError, InvalidInputError, NotFoundError
from ahia.core.permissions.permissions_registry import permission_codes_for_role
from ahia.core.tenant_context import TenantContext, build_tenant_context
from ahia.crud import tenant_crud
from ahia.models.entities.tenant_model import TenantModel
from ahia.services.audit_event_service import AuditEventService
from ahia.services.category_service import CategoryService

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
        await connection.execute(text("TRUNCATE TABLE categories, tenants CASCADE"))
    try:
        yield instance
    finally:
        await instance.dispose()


@pytest.fixture
def service(database: Database) -> CategoryService:
    return CategoryService(
        unit_of_work_factory=database.unit_of_work_factory(),
        audit_event_service=AuditEventService(unit_of_work_factory=database.unit_of_work_factory()),
    )


async def insert_tenant(database: Database, tenant_id: UUID) -> None:
    """Create the business a category will belong to."""
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


@pytest.fixture
async def tenant_id(database: Database) -> UUID:
    identifier = uuid4()
    await insert_tenant(database, identifier)
    return identifier


def owner_context(tenant_id: UUID) -> TenantContext:
    """An OWNER context: every tenant permission, resolved from the role bundle."""
    return build_tenant_context(
        user_id=uuid4(),
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=permission_codes_for_role("OWNER"),
        role_name="OWNER",
    )


def sales_context(tenant_id: UUID) -> TenantContext:
    """A SALES context: reads the catalogue, never changes it."""
    return build_tenant_context(
        user_id=uuid4(),
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=permission_codes_for_role("SALES"),
        role_name="SALES",
    )


# ---------------------------------------------------------------------------
# Creating
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_creating_a_category_derives_its_slug(
    service: CategoryService, tenant_id: UUID
) -> None:
    created = await service.create_category(
        owner_context(tenant_id), name="Cold Drinks", description="Everything chilled"
    )

    assert created.slug == "cold-drinks"
    assert created.tenant_id == tenant_id
    assert created.description == "Everything chilled"


@pytest.mark.integration
async def test_two_businesses_may_each_have_a_drinks_category(
    database: Database, service: CategoryService, tenant_id: UUID
) -> None:
    other_tenant = uuid4()
    await insert_tenant(database, other_tenant)

    first = await service.create_category(owner_context(tenant_id), name="Drinks")
    second = await service.create_category(owner_context(other_tenant), name="Drinks")

    assert first.id != second.id
    assert first.slug == second.slug == "drinks"


@pytest.mark.integration
async def test_the_same_name_twice_in_one_business_is_a_conflict(
    service: CategoryService, tenant_id: UUID
) -> None:
    """Two categories a person cannot tell apart is worse than a refusal."""
    await service.create_category(owner_context(tenant_id), name="Drinks")

    with pytest.raises(ConflictError) as captured:
        await service.create_category(owner_context(tenant_id), name="  drinks  ")

    detail = captured.value.context.detail or ""
    assert "already exists" in detail
    assert "uq_categories" in detail, "the internal detail names the constraint"


@pytest.mark.integration
async def test_a_category_for_a_business_that_does_not_exist_is_refused(
    service: CategoryService,
) -> None:
    with pytest.raises(NotFoundError):
        await service.create_category(owner_context(uuid4()), name="Drinks")


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_listing_is_ordered_by_name_and_scoped_to_the_business(
    database: Database, service: CategoryService, tenant_id: UUID
) -> None:
    other_tenant = uuid4()
    await insert_tenant(database, other_tenant)
    owner = owner_context(tenant_id)

    for name in ("Snacks", "Drinks", "Appliances"):
        await service.create_category(owner, name=name)
    await service.create_category(owner_context(other_tenant), name="Elsewhere")

    listed = await service.list_categories(owner)

    assert [category.name for category in listed] == ["Appliances", "Drinks", "Snacks"]


@pytest.mark.integration
async def test_reading_a_category_from_another_business_is_a_not_found(
    database: Database, service: CategoryService, tenant_id: UUID
) -> None:
    """A 404 rather than a 403: whether the category exists is not the caller's business."""
    other_tenant = uuid4()
    await insert_tenant(database, other_tenant)
    elsewhere = await service.create_category(owner_context(other_tenant), name="Drinks")

    with pytest.raises(NotFoundError) as captured:
        await service.get_category(owner_context(tenant_id), category_id=elsewhere.id)

    assert "no category matched in this business" in (captured.value.context.detail or "")


@pytest.mark.integration
async def test_reading_an_unknown_category_is_a_not_found(
    service: CategoryService, tenant_id: UUID
) -> None:
    with pytest.raises(NotFoundError):
        await service.get_category(owner_context(tenant_id), category_id=uuid4())


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_renaming_leaves_the_slug_alone(service: CategoryService, tenant_id: UUID) -> None:
    owner = owner_context(tenant_id)
    created = await service.create_category(owner, name="Drinks")

    updated = await service.update_category(
        owner, category_id=created.id, changes={"name": "Cold Drinks"}
    )

    assert updated.name == "Cold Drinks"
    assert updated.slug == "drinks"
    assert updated.updated_at >= created.updated_at


@pytest.mark.integration
async def test_a_description_can_be_set_and_cleared(
    service: CategoryService, tenant_id: UUID
) -> None:
    owner = owner_context(tenant_id)
    created = await service.create_category(owner, name="Drinks")

    set_description = await service.update_category(
        owner, category_id=created.id, changes={"description": "Everything cold"}
    )
    cleared = await service.update_category(
        owner, category_id=created.id, changes={"description": None}
    )

    assert set_description.description == "Everything cold"
    assert cleared.description is None


@pytest.mark.integration
async def test_an_empty_change_set_leaves_the_category_untouched(
    service: CategoryService, tenant_id: UUID
) -> None:
    owner = owner_context(tenant_id)
    created = await service.create_category(owner, name="Drinks", description="Everything cold")

    updated = await service.update_category(owner, category_id=created.id, changes={})

    assert updated == created


@pytest.mark.integration
async def test_a_field_that_is_not_editable_is_refused(
    service: CategoryService, tenant_id: UUID
) -> None:
    """An allowlist, so a new column cannot become writable merely by existing."""
    owner = owner_context(tenant_id)
    created = await service.create_category(owner, name="Drinks")

    with pytest.raises(InvalidInputError) as captured:
        await service.update_category(
            owner, category_id=created.id, changes={"slug": "cold-drinks"}
        )

    assert "slug" in (captured.value.context.detail or "")


@pytest.mark.integration
async def test_editing_a_category_from_another_business_is_a_not_found(
    database: Database, service: CategoryService, tenant_id: UUID
) -> None:
    other_tenant = uuid4()
    await insert_tenant(database, other_tenant)
    elsewhere = await service.create_category(owner_context(other_tenant), name="Drinks")

    with pytest.raises(NotFoundError):
        await service.update_category(
            owner_context(tenant_id), category_id=elsewhere.id, changes={"name": "Mine now"}
        )


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_salesperson_may_read_the_catalogue(
    service: CategoryService, tenant_id: UUID
) -> None:
    """SALES holds products.read, which is what a catalogue listing needs."""
    owner = owner_context(tenant_id)
    await service.create_category(owner, name="Drinks")

    listed = await service.list_categories(sales_context(tenant_id))
    one = await service.get_category(sales_context(tenant_id), category_id=listed[0].id)

    assert [category.name for category in listed] == ["Drinks"]
    assert one.name == "Drinks"


@pytest.mark.integration
async def test_a_salesperson_may_not_create_a_category(
    service: CategoryService, tenant_id: UUID
) -> None:
    with pytest.raises(AuthorizationError):
        await service.create_category(sales_context(tenant_id), name="Drinks")


@pytest.mark.integration
async def test_a_salesperson_may_not_edit_a_category(
    service: CategoryService, tenant_id: UUID
) -> None:
    owner = owner_context(tenant_id)
    created = await service.create_category(owner, name="Drinks")

    with pytest.raises(AuthorizationError):
        await service.update_category(
            sales_context(tenant_id), category_id=created.id, changes={"name": "Cold Drinks"}
        )


@pytest.mark.integration
async def test_authorization_is_checked_before_the_database_is_touched(
    service: CategoryService, tenant_id: UUID
) -> None:
    """A denied caller must not be able to tell an existing name from a free one.

    The check runs first, so a refused create never reaches the uniqueness rule and
    cannot be used to probe which category names are taken.
    """
    owner = owner_context(tenant_id)
    await service.create_category(owner, name="Drinks")

    with pytest.raises(AuthorizationError):
        await service.create_category(sales_context(tenant_id), name="Drinks")
    with pytest.raises(AuthorizationError):
        await service.create_category(sales_context(tenant_id), name="A Name Nobody Used")
