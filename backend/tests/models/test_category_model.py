"""Tests for the category entity and its persistence.

Two halves. The first is about the entity's own rules: a name that is only
punctuation, a slug derived from a name, a rename that leaves the handle alone. The
second is about the rule the database enforces: a category name is unique inside one
business and free everywhere else.
"""

from __future__ import annotations

import os
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.errors import ConflictError, EntityInvariantError, NotFoundError
from ahia.crud import category_crud, tenant_crud
from ahia.models.entities.category_model import (
    MAXIMUM_DESCRIPTION_LENGTH,
    MAXIMUM_NAME_LENGTH,
    CategoryModel,
)
from ahia.models.entities.tenant_model import TenantModel

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)


def build_settings() -> Settings:
    return Settings(
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


def build_category(**overrides: object) -> CategoryModel:
    parameters: dict[str, object] = {
        "category_id": uuid4(),
        "tenant_id": uuid4(),
        "name": "Drinks",
        "now": NOW,
        "description": "Everything cold",
    }
    parameters.update(overrides)
    return CategoryModel.create(**parameters)  # type: ignore[arg-type]


@pytest.fixture
async def database() -> Any:
    instance = Database(build_settings())
    async with instance.engine.begin() as connection:
        # The whole schema, created from the models. A table's foreign keys require
        # the tables they reference to exist first, and creating everything in
        # dependency order is exactly what create_all does.
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(sync_connection, checkfirst=True)
        )
        await connection.execute(text("TRUNCATE TABLE categories CASCADE"))
    try:
        yield instance
    finally:
        await instance.dispose()


async def insert_tenant(database: Database, tenant_id: UUID) -> None:
    """Create the business a category row references."""
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


# ---------------------------------------------------------------------------
# The entity's own rules
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_category_derives_its_slug_from_its_name() -> None:
    category = build_category(name="Cold Drinks")

    assert category.name == "Cold Drinks"
    assert category.slug == "cold-drinks"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("name", "expected_slug"),
    [
        ("Drinks", "drinks"),
        ("  Drinks  ", "drinks"),
        ("DRINKS", "drinks"),
        ("Drinks & Beverages", "drinks-beverages"),
        ("TV", "tv"),
        ("A", "a"),
    ],
)
def test_the_slug_is_what_a_person_would_expect(name: str, expected_slug: str) -> None:
    assert build_category(name=name).slug == expected_slug


@pytest.mark.unit
def test_a_short_name_is_allowed_because_a_shop_sells_televisions() -> None:
    """The business slug minimum of three characters does not apply here."""
    assert build_category(name="TV").slug == "tv"


@pytest.mark.unit
def test_the_name_is_trimmed() -> None:
    assert build_category(name="  Drinks  ").name == "Drinks"


@pytest.mark.unit
@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_an_empty_name_is_rejected(name: str) -> None:
    with pytest.raises(EntityInvariantError, match="name is empty"):
        build_category(name=name)


@pytest.mark.unit
def test_a_name_of_only_punctuation_is_rejected() -> None:
    """It would produce an empty slug, which is a category with no handle at all."""
    with pytest.raises(EntityInvariantError, match="invalid slug"):
        build_category(name="!!!")


@pytest.mark.unit
def test_an_overlong_name_is_rejected() -> None:
    with pytest.raises(EntityInvariantError, match="exceeds"):
        build_category(name="x" * (MAXIMUM_NAME_LENGTH + 1))


@pytest.mark.unit
def test_an_overlong_description_is_rejected() -> None:
    with pytest.raises(EntityInvariantError, match="description exceeds"):
        build_category(description="x" * (MAXIMUM_DESCRIPTION_LENGTH + 1))


@pytest.mark.unit
def test_a_description_is_optional() -> None:
    assert build_category(description=None).description is None


@pytest.mark.unit
def test_an_empty_description_becomes_none_rather_than_an_empty_string() -> None:
    """One representation of "no description", so a reader never checks for both."""
    assert build_category(description="   ").description is None
    assert build_category(description="").description is None


@pytest.mark.unit
@pytest.mark.parametrize("field_name", ["created_at", "updated_at"])
def test_naive_timestamps_are_rejected(field_name: str) -> None:
    """A naive timestamp has no meaning across the clients this product serves."""
    category = build_category()
    timestamps: dict[str, datetime] = {
        "created_at": NOW,
        "updated_at": NOW,
    }
    timestamps[field_name] = datetime(2026, 9, 13, 9, 30)  # noqa: DTZ001 - under test

    with pytest.raises(EntityInvariantError, match="naive datetime"):
        CategoryModel(
            id=category.id,
            tenant_id=category.tenant_id,
            name=category.name,
            slug=category.slug,
            created_at=timestamps["created_at"],
            updated_at=timestamps["updated_at"],
        )


@pytest.mark.unit
def test_updated_at_cannot_precede_created_at() -> None:
    category = build_category()
    with pytest.raises(EntityInvariantError, match="earlier than created_at"):
        CategoryModel(
            id=category.id,
            tenant_id=category.tenant_id,
            name=category.name,
            slug=category.slug,
            created_at=NOW,
            updated_at=NOW - timedelta(seconds=1),
        )


@pytest.mark.unit
def test_the_entity_is_immutable() -> None:
    category = build_category()
    with pytest.raises(FrozenInstanceError):
        category.name = "Something else"  # type: ignore[misc]


@pytest.mark.unit
def test_the_audit_description_carries_identifiers_and_no_free_text() -> None:
    category = build_category(name="Drinks", description="Bought from Musa on credit")

    description = category.describe_for_audit()

    assert set(description) == {"category_id", "tenant_id", "category_slug"}
    assert "Musa" not in repr(description)


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_renaming_changes_the_name_and_leaves_the_slug_alone() -> None:
    """The slug is the handle other things point at; a rename changes what people read."""
    category = build_category(name="Drinks")
    renamed = category.renamed(name="Cold Drinks", at=NOW + timedelta(hours=1))

    assert renamed.name == "Cold Drinks"
    assert renamed.slug == "drinks"
    assert category.name == "Drinks", "the original is untouched"


@pytest.mark.unit
def test_renaming_stamps_the_update() -> None:
    later = NOW + timedelta(days=1)
    renamed = build_category().renamed(name="Cold Drinks", at=later)

    assert renamed.updated_at == later


@pytest.mark.unit
def test_describing_can_set_and_clear() -> None:
    category = build_category(description="Everything cold")

    described = category.described(description="Chilled and ambient", at=NOW)
    cleared = described.described(description=None, at=NOW)

    assert described.description == "Chilled and ambient"
    assert cleared.description is None
    assert category.description == "Everything cold"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_and_read_back(database: Database) -> None:
    category = build_category(name="Drinks")
    await insert_tenant(database, category.tenant_id)

    async with database.transaction_scope() as unit_of_work:
        created = await category_crud.create(unit_of_work.session_handle, category)
        await unit_of_work.commit()

    assert created == category

    async with database.transaction_scope() as unit_of_work:
        by_id = await category_crud.get_by_id(
            unit_of_work.session_handle,
            tenant_id=category.tenant_id,
            category_id=category.id,
        )
        by_slug = await category_crud.get_by_slug(
            unit_of_work.session_handle,
            tenant_id=category.tenant_id,
            slug=category.slug,
        )

    assert by_id == category
    assert by_slug == category


@pytest.mark.integration
async def test_the_same_name_cannot_appear_twice_in_one_business(database: Database) -> None:
    tenant_id = uuid4()
    await insert_tenant(database, tenant_id)
    first = build_category(tenant_id=tenant_id, name="Drinks")

    async with database.transaction_scope() as unit_of_work:
        await category_crud.create(unit_of_work.session_handle, first)
        await unit_of_work.commit()

    with pytest.raises(ConflictError):
        async with database.transaction_scope() as unit_of_work:
            await category_crud.create(
                unit_of_work.session_handle,
                build_category(tenant_id=tenant_id, name="  drinks  "),
            )


@pytest.mark.integration
async def test_the_same_name_is_free_in_another_business(database: Database) -> None:
    """A category is a business's own word for what it sells, so it is not global."""
    first = build_category(name="Drinks")
    second = build_category(name="Drinks")
    await insert_tenant(database, first.tenant_id)
    await insert_tenant(database, second.tenant_id)

    async with database.transaction_scope() as unit_of_work:
        await category_crud.create(unit_of_work.session_handle, first)
        await category_crud.create(unit_of_work.session_handle, second)
        await unit_of_work.commit()

        counted = await category_crud.count_for_tenant(unit_of_work.session_handle, first.tenant_id)

    assert counted == 1


@pytest.mark.integration
async def test_a_category_cannot_be_read_through_another_business(database: Database) -> None:
    category = build_category(name="Drinks")
    await insert_tenant(database, category.tenant_id)

    async with database.transaction_scope() as unit_of_work:
        await category_crud.create(unit_of_work.session_handle, category)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        elsewhere = await category_crud.get_by_id(
            unit_of_work.session_handle,
            tenant_id=uuid4(),
            category_id=category.id,
        )

    assert elsewhere is None


@pytest.mark.integration
async def test_listing_is_scoped_and_ordered_by_name(database: Database) -> None:
    tenant_id = uuid4()
    await insert_tenant(database, tenant_id)
    other = build_category(name="Elsewhere")
    await insert_tenant(database, other.tenant_id)

    async with database.transaction_scope() as unit_of_work:
        for name in ("Snacks", "Drinks", "Appliances"):
            await category_crud.create(
                unit_of_work.session_handle, build_category(tenant_id=tenant_id, name=name)
            )
        await category_crud.create(unit_of_work.session_handle, other)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        listed = await category_crud.list_for_tenant(unit_of_work.session_handle, tenant_id)

    assert [category.name for category in listed] == ["Appliances", "Drinks", "Snacks"]


@pytest.mark.integration
async def test_update_persists_the_rename_and_the_cleared_description(
    database: Database,
) -> None:
    category = build_category(name="Drinks", description="Everything cold")
    await insert_tenant(database, category.tenant_id)

    async with database.transaction_scope() as unit_of_work:
        await category_crud.create(unit_of_work.session_handle, category)
        await unit_of_work.commit()

    later = NOW + timedelta(days=1)
    async with database.transaction_scope() as unit_of_work:
        updated = await category_crud.update(
            unit_of_work.session_handle,
            category.renamed(name="Cold Drinks", at=later).described(description=None, at=later),
        )
        await unit_of_work.commit()

    assert updated.name == "Cold Drinks"
    assert updated.description is None
    assert updated.updated_at == later

    async with database.transaction_scope() as unit_of_work:
        stored = await category_crud.get_by_id(
            unit_of_work.session_handle,
            tenant_id=category.tenant_id,
            category_id=category.id,
        )

    assert stored == updated


@pytest.mark.integration
async def test_update_refuses_a_category_from_another_business(database: Database) -> None:
    category = build_category()
    await insert_tenant(database, category.tenant_id)

    async with database.transaction_scope() as unit_of_work:
        await category_crud.create(unit_of_work.session_handle, category)
        await unit_of_work.commit()

    stranger = CategoryModel(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Drinks",
        slug="drinks",
        created_at=NOW,
        updated_at=NOW,
    )

    with pytest.raises(NotFoundError):
        async with database.transaction_scope() as unit_of_work:
            await category_crud.update(unit_of_work.session_handle, stranger)


@pytest.mark.integration
async def test_require_by_id_reports_a_typed_not_found(database: Database) -> None:
    with pytest.raises(NotFoundError, match="no category matched"):
        async with database.transaction_scope() as unit_of_work:
            await category_crud.require_by_id(
                unit_of_work.session_handle,
                tenant_id=uuid4(),
                category_id=uuid4(),
            )


@pytest.mark.integration
async def test_a_category_for_an_unknown_business_is_refused_by_the_database(
    database: Database,
) -> None:
    """The foreign key is the guarantee; the service does not have to be trusted for it."""
    category = build_category()

    with pytest.raises(NotFoundError, match="does not exist"):
        async with database.transaction_scope() as unit_of_work:
            await category_crud.create(unit_of_work.session_handle, category)
