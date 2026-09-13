"""Tests for customer persistence.

Two things are tested here that a service cannot be trusted to prove: that a phone number
is *not* unique - so two people in a household are both recordable - and that every lookup
takes a tenant, so a customer recorded by one business is invisible to another. The
version check is the third: it is what turns two offline edits into a conflict rather than
a lost edit.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.errors import ConflictError, NotFoundError
from ahia.crud import customer_crud, tenant_crud
from ahia.models.entities.customer_model import CustomerModel
from ahia.models.entities.tenant_model import TenantModel

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)


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
        await connection.execute(text("TRUNCATE TABLE customers, tenants CASCADE"))
    try:
        yield instance
    finally:
        await instance.dispose()


def build_customer(**overrides: object) -> CustomerModel:
    parameters: dict[str, object] = {
        "customer_id": uuid4(),
        "tenant_id": uuid4(),
        "name": "Ada Obi",
        "now": NOW,
        "phone": "+2348031234567",
        "email": "ada@example.com",
    }
    parameters.update(overrides)
    return CustomerModel.create(**parameters)  # type: ignore[arg-type]


async def insert_tenant(database: Database) -> UUID:
    identifier = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await tenant_crud.create(
            unit_of_work.session_handle,
            TenantModel.create(
                tenant_id=identifier,
                name="Obi Electronics",
                slug=f"obi-{identifier.hex[:8]}",
                now=NOW,
            ),
        )
        await unit_of_work.commit()
    return identifier


@pytest.fixture
async def tenant_id(database: Database) -> UUID:
    return await insert_tenant(database)


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_customer_round_trips_every_field(database: Database, tenant_id: UUID) -> None:
    customer = build_customer(
        tenant_id=tenant_id,
        name="Ada Obi",
        address="12 Awolowo Road, Ikeja",
        notes="Prefers delivery on Saturdays",
        marketing_opt_in=True,
    )

    async with database.transaction_scope() as unit_of_work:
        created = await customer_crud.create(unit_of_work.session_handle, customer)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        stored = await customer_crud.require_by_id(
            unit_of_work.session_handle, tenant_id=tenant_id, customer_id=customer.id
        )

    assert created == customer
    assert stored == customer
    assert stored.marketing_opt_in is True
    assert stored.version == 1


@pytest.mark.integration
async def test_a_customer_with_no_contact_details_round_trips(
    database: Database, tenant_id: UUID
) -> None:
    customer = build_customer(tenant_id=tenant_id, phone=None, email=None)

    async with database.transaction_scope() as unit_of_work:
        await customer_crud.create(unit_of_work.session_handle, customer)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        stored = await customer_crud.require_by_id(
            unit_of_work.session_handle, tenant_id=tenant_id, customer_id=customer.id
        )

    assert stored.phone is None
    assert stored.email is None
    assert stored.has_a_contact_detail() is False


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_customer_is_invisible_to_another_business(database: Database) -> None:
    """Customer data belongs to the tenant that recorded it."""
    first_tenant = await insert_tenant(database)
    second_tenant = await insert_tenant(database)
    customer = build_customer(tenant_id=first_tenant)

    async with database.transaction_scope() as unit_of_work:
        await customer_crud.create(unit_of_work.session_handle, customer)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        elsewhere = await customer_crud.get_by_id(
            unit_of_work.session_handle, tenant_id=second_tenant, customer_id=customer.id
        )
        listed = await customer_crud.list_for_tenant(unit_of_work.session_handle, second_tenant)
        counted = await customer_crud.count_for_tenant(unit_of_work.session_handle, second_tenant)

    assert elsewhere is None
    assert listed == []
    assert counted == 0


@pytest.mark.integration
async def test_a_customer_cannot_be_read_through_another_business_by_phone(
    database: Database,
) -> None:
    first_tenant = await insert_tenant(database)
    second_tenant = await insert_tenant(database)
    customer = build_customer(tenant_id=first_tenant, phone="+2348031234567")

    async with database.transaction_scope() as unit_of_work:
        await customer_crud.create(unit_of_work.session_handle, customer)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        theirs = await customer_crud.find_by_phone(
            unit_of_work.session_handle, tenant_id=second_tenant, phone="+2348031234567"
        )

    assert theirs == []


@pytest.mark.integration
async def test_a_customer_for_an_unknown_business_is_refused(database: Database) -> None:
    with pytest.raises(Exception) as captured:
        async with database.transaction_scope() as unit_of_work:
            await customer_crud.create(unit_of_work.session_handle, build_customer())
            await unit_of_work.commit()

    assert "fk_customers_tenant_id_tenants" in str(captured.value)


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_two_customers_may_share_a_phone_number(database: Database, tenant_id: UUID) -> None:
    """A household shares a number, and refusing the second entry would be wrong."""
    shared = "+2348031234567"

    async with database.transaction_scope() as unit_of_work:
        for name in ("Ada Obi", "Chidi Obi"):
            await customer_crud.create(
                unit_of_work.session_handle,
                build_customer(tenant_id=tenant_id, name=name, phone=shared),
            )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        found = await customer_crud.find_by_phone(
            unit_of_work.session_handle, tenant_id=tenant_id, phone=shared
        )

    assert len(found) == 2
    assert {customer.name for customer in found} == {"Ada Obi", "Chidi Obi"}


@pytest.mark.integration
async def test_detection_can_exclude_the_customer_being_edited(
    database: Database, tenant_id: UUID
) -> None:
    """Editing a name should not report the customer as their own duplicate."""
    shared = "+2348031234567"
    customer = build_customer(tenant_id=tenant_id, phone=shared)

    async with database.transaction_scope() as unit_of_work:
        await customer_crud.create(unit_of_work.session_handle, customer)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        found = await customer_crud.find_by_phone(
            unit_of_work.session_handle,
            tenant_id=tenant_id,
            phone=shared,
            excluding=customer.id,
        )

    assert found == []


@pytest.mark.integration
async def test_many_customers_may_have_no_phone_at_all(database: Database, tenant_id: UUID) -> None:
    """The partial index means the nulls do not collide."""
    async with database.transaction_scope() as unit_of_work:
        for index in range(3):
            await customer_crud.create(
                unit_of_work.session_handle,
                build_customer(tenant_id=tenant_id, name=f"Customer {index}", phone=None),
            )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        assert await customer_crud.count_for_tenant(unit_of_work.session_handle, tenant_id) == 3


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_listing_is_ordered_by_name_and_hides_the_inactive(
    database: Database, tenant_id: UUID
) -> None:
    for name in ("Chidi Obi", "Ada Obi", "Bola Ade"):
        async with database.transaction_scope() as unit_of_work:
            await customer_crud.create(
                unit_of_work.session_handle,
                build_customer(
                    tenant_id=tenant_id, name=name, phone=None, email=f"{name.split()[0]}@x.test"
                ),
            )
            await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        everyone = await customer_crud.list_for_tenant(
            unit_of_work.session_handle, tenant_id, include_inactive=True
        )
        retiring = next(customer for customer in everyone if customer.name == "Chidi Obi")
        await customer_crud.update(unit_of_work.session_handle, retiring.deactivated(at=LATER))
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        active_only = await customer_crud.list_for_tenant(unit_of_work.session_handle, tenant_id)
        everything = await customer_crud.list_for_tenant(
            unit_of_work.session_handle, tenant_id, include_inactive=True
        )

    assert [customer.name for customer in active_only] == ["Ada Obi", "Bola Ade"]
    assert len(everything) == 3


@pytest.mark.integration
async def test_counting_can_exclude_the_inactive(database: Database, tenant_id: UUID) -> None:
    customer = build_customer(tenant_id=tenant_id)

    async with database.transaction_scope() as unit_of_work:
        await customer_crud.create(unit_of_work.session_handle, customer)
        await customer_crud.update(unit_of_work.session_handle, customer.deactivated(at=LATER))
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        every = await customer_crud.count_for_tenant(unit_of_work.session_handle, tenant_id)
        active = await customer_crud.count_for_tenant(
            unit_of_work.session_handle, tenant_id, include_inactive=False
        )

    assert every == 1
    assert active == 0


# ---------------------------------------------------------------------------
# Version checking
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_an_update_persists_and_moves_the_version(
    database: Database, tenant_id: UUID
) -> None:
    customer = build_customer(tenant_id=tenant_id)

    async with database.transaction_scope() as unit_of_work:
        await customer_crud.create(unit_of_work.session_handle, customer)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        updated = await customer_crud.update(
            unit_of_work.session_handle, customer.noted(notes="Pays on delivery", at=LATER)
        )
        await unit_of_work.commit()

    assert updated.notes == "Pays on delivery"
    assert updated.version == 2

    async with database.transaction_scope() as unit_of_work:
        reread = await customer_crud.require_by_id(
            unit_of_work.session_handle, tenant_id=tenant_id, customer_id=customer.id
        )

    assert reread == updated


@pytest.mark.integration
async def test_an_update_from_a_stale_version_is_refused(
    database: Database, tenant_id: UUID
) -> None:
    """Two offline edits must not silently discard each other."""
    customer = build_customer(tenant_id=tenant_id)

    async with database.transaction_scope() as unit_of_work:
        await customer_crud.create(unit_of_work.session_handle, customer)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        await customer_crud.update(
            unit_of_work.session_handle, customer.noted(notes="Phone's edit", at=LATER)
        )
        await unit_of_work.commit()

    with pytest.raises(ConflictError) as captured:
        async with database.transaction_scope() as unit_of_work:
            await customer_crud.update(
                unit_of_work.session_handle,
                customer.noted(notes="The other phone's edit", at=LATER),
                expected_version=1,
            )

    detail = captured.value.context.detail or ""
    assert "expected version 1" in detail
    assert "stored version 2" in detail

    async with database.transaction_scope() as unit_of_work:
        reread = await customer_crud.require_by_id(
            unit_of_work.session_handle, tenant_id=tenant_id, customer_id=customer.id
        )

    assert reread.notes == "Phone's edit", "the first edit survives"


@pytest.mark.integration
async def test_an_update_with_the_current_version_succeeds(
    database: Database, tenant_id: UUID
) -> None:
    customer = build_customer(tenant_id=tenant_id)

    async with database.transaction_scope() as unit_of_work:
        await customer_crud.create(unit_of_work.session_handle, customer)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        updated = await customer_crud.update(
            unit_of_work.session_handle,
            customer.noted(notes="Edited with the version I had", at=LATER),
            expected_version=1,
        )
        await unit_of_work.commit()

    assert updated.version == 2


@pytest.mark.integration
async def test_an_update_without_a_version_is_last_writer_wins(
    database: Database, tenant_id: UUID
) -> None:
    """An online client has no version to send, and the specification allows this."""
    customer = build_customer(tenant_id=tenant_id)

    async with database.transaction_scope() as unit_of_work:
        await customer_crud.create(unit_of_work.session_handle, customer)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        first = await customer_crud.update(
            unit_of_work.session_handle, customer.noted(notes="First", at=LATER)
        )
        second = await customer_crud.update(
            unit_of_work.session_handle, first.noted(notes="Second", at=LATER)
        )
        await unit_of_work.commit()

    assert second.notes == "Second"
    assert second.version == 3


@pytest.mark.integration
async def test_an_update_cannot_reach_another_businesss_customer(
    database: Database,
) -> None:
    first_tenant = await insert_tenant(database)
    second_tenant = await insert_tenant(database)
    customer = build_customer(tenant_id=first_tenant)

    async with database.transaction_scope() as unit_of_work:
        await customer_crud.create(unit_of_work.session_handle, customer)
        await unit_of_work.commit()

    stranger = CustomerModel(
        id=customer.id,
        tenant_id=second_tenant,
        name="Mine now",
        created_at=NOW,
        updated_at=NOW,
    )

    with pytest.raises(NotFoundError):
        async with database.transaction_scope() as unit_of_work:
            await customer_crud.update(unit_of_work.session_handle, stranger)


@pytest.mark.integration
async def test_require_by_id_names_the_missing_customer(
    database: Database, tenant_id: UUID
) -> None:
    with pytest.raises(NotFoundError, match="no customer matched"):
        async with database.transaction_scope() as unit_of_work:
            await customer_crud.require_by_id(
                unit_of_work.session_handle, tenant_id=tenant_id, customer_id=uuid4()
            )
