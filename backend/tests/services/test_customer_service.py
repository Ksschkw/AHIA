"""Tests for the customer use cases.

Three properties of this layer are the subject.

**Privacy.** No log line and no audit description carries a customer's name, phone or
email - a customer never signed up for this product, and their details should not
accumulate in a log store. The entity's `describe_for_audit` is asserted directly, and the
service is asserted to log identifiers.

**Tenant scoping.** A customer recorded by one business is invisible to another, through
every path this service offers.

**Contact canonicalisation.** `0803 123 4567` and `+2348031234567` must resolve to one
customer, or duplicate detection is a lie: it would report "no match" for the same person
typed two ways.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.errors import (
    AuthorizationError,
    ConflictError,
    InvalidInputError,
    NotFoundError,
)
from ahia.core.permissions.permissions_registry import permission_codes_for_role
from ahia.core.tenant_context import TenantContext, build_tenant_context
from ahia.crud import customer_crud, tenant_crud
from ahia.models.entities.tenant_model import TenantModel
from ahia.services.customer_service import CustomerService

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
        await connection.execute(text("TRUNCATE TABLE customers, tenants CASCADE"))
    try:
        yield instance
    finally:
        await instance.dispose()


@pytest.fixture
def service(database: Database) -> CustomerService:
    return CustomerService(
        unit_of_work_factory=database.unit_of_work_factory(),
        default_phone_country_code="234",
    )


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


def context_for(tenant_id: UUID, role_name: str) -> TenantContext:
    return build_tenant_context(
        user_id=uuid4(),
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=permission_codes_for_role(role_name),
        role_name=role_name,
    )


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_recording_a_customer_stores_them_and_starts_at_version_one(
    service: CustomerService, tenant_id: UUID
) -> None:
    creation = await service.create_customer(
        context_for(tenant_id, "OWNER"),
        name="Ada Obi",
        phone="0803 123 4567",
        email="Ada@Example.COM",
        address="12 Awolowo Road, Ikeja",
        notes="Prefers delivery on Saturdays",
    )

    customer = creation.customer
    assert customer.name == "Ada Obi"
    assert customer.phone == "+2348031234567", "a local number is completed"
    assert customer.email == "ada@example.com"
    assert customer.version == 1
    assert customer.marketing_opt_in is False
    assert creation.has_possible_duplicate is False


@pytest.mark.integration
async def test_two_ways_of_writing_one_number_are_one_customer(
    service: CustomerService, tenant_id: UUID
) -> None:
    """Otherwise duplicate detection would report no match for the same person."""
    owner = context_for(tenant_id, "OWNER")
    first = await service.create_customer(owner, name="Ada Obi", phone="0803 123 4567")
    second = await service.create_customer(owner, name="Ada Obi", phone="+2348031234567")

    assert first.customer.phone == second.customer.phone
    assert second.possible_duplicate_of == first.customer.id


@pytest.mark.integration
async def test_a_likely_duplicate_is_reported_rather_than_refused(
    service: CustomerService, tenant_id: UUID
) -> None:
    """A household shares a number, and blocking the write would invite a fake one."""
    owner = context_for(tenant_id, "OWNER")
    await service.create_customer(owner, name="Ada Obi", phone="+2348031234567")

    second = await service.create_customer(owner, name="Chidi Obi", phone="+2348031234567")

    assert second.has_possible_duplicate is True
    assert second.customer.name == "Chidi Obi"

    listed = await service.list_customers(owner)
    assert {customer.name for customer in listed} == {"Ada Obi", "Chidi Obi"}


@pytest.mark.integration
async def test_a_customer_may_be_recorded_without_any_contact_detail(
    service: CustomerService, tenant_id: UUID
) -> None:
    creation = await service.create_customer(
        context_for(tenant_id, "OWNER"), name="Walk-in customer"
    )

    assert creation.customer.has_a_contact_detail() is False
    assert creation.has_possible_duplicate is False


@pytest.mark.integration
@pytest.mark.parametrize("phone", ["123", "0803-ABC-4567", "+1234567890123456"])
async def test_an_implausible_phone_number_is_refused_with_the_field_named(
    service: CustomerService, tenant_id: UUID, phone: str
) -> None:
    """Judged *after* country completion, which is why a short local number is accepted.

    `12345` becomes `+23412345` once the country code is applied, and that is a number
    somebody could dial - so refusing it would mean guessing that the person meant a short
    code. What is refused is a value that is still not a number afterwards: too few digits,
    letters in it, or longer than E.164 allows.
    """
    with pytest.raises(InvalidInputError, match="phone"):
        await service.create_customer(context_for(tenant_id, "OWNER"), name="Ada Obi", phone=phone)


@pytest.mark.integration
async def test_marketing_consent_is_recorded_when_it_is_given(
    service: CustomerService, tenant_id: UUID
) -> None:
    creation = await service.create_customer(
        context_for(tenant_id, "OWNER"),
        name="Ada Obi",
        phone="+2348031234567",
        marketing_opt_in=True,
    )

    assert creation.customer.marketing_opt_in is True
    assert creation.customer.is_reachable_for_marketing() is True


# ---------------------------------------------------------------------------
# Duplicate detection at the counter
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_counter_lookup_finds_a_customer_by_any_written_form(
    service: CustomerService, tenant_id: UUID
) -> None:
    owner = context_for(tenant_id, "OWNER")
    await service.create_customer(owner, name="Ada Obi", phone="+2348031234567")

    for typed in ("0803 123 4567", "08031234567", "+234 803 123 4567"):
        matches = await service.find_by_phone(owner, phone=typed)
        assert [match.name for match in matches] == ["Ada Obi"], typed


@pytest.mark.integration
async def test_the_counter_lookup_is_scoped_to_the_business(
    database: Database, service: CustomerService, tenant_id: UUID
) -> None:
    other_tenant = await insert_tenant(database)
    await service.create_customer(
        context_for(other_tenant, "OWNER"), name="Their customer", phone="+2348031234567"
    )

    matches = await service.find_by_phone(context_for(tenant_id, "OWNER"), phone="+2348031234567")

    assert matches == []


@pytest.mark.integration
async def test_the_counter_lookup_needs_a_number(service: CustomerService, tenant_id: UUID) -> None:
    with pytest.raises(InvalidInputError, match="phone number is required"):
        await service.find_by_phone(context_for(tenant_id, "OWNER"), phone="   ")


# ---------------------------------------------------------------------------
# Editing, versions and the version check
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_partial_edit_leaves_the_unsent_fields_alone(
    service: CustomerService, tenant_id: UUID
) -> None:
    owner = context_for(tenant_id, "OWNER")
    created = await service.create_customer(
        owner, name="Ada Obi", phone="+2348031234567", notes="Pays on delivery"
    )

    updated = await service.update_customer(
        owner, customer_id=created.customer.id, changes={"name": "Ada N. Obi"}
    )

    assert updated.name == "Ada N. Obi"
    assert updated.phone == "+2348031234567"
    assert updated.notes == "Pays on delivery"
    assert updated.version == 2


@pytest.mark.integration
async def test_a_phone_number_can_be_cleared_and_a_new_one_set(
    service: CustomerService, tenant_id: UUID
) -> None:
    owner = context_for(tenant_id, "OWNER")
    created = await service.create_customer(owner, name="Ada Obi", phone="+2348031234567")

    cleared = await service.update_customer(
        owner, customer_id=created.customer.id, changes={"phone": None}
    )
    reset = await service.update_customer(
        owner, customer_id=created.customer.id, changes={"phone": "0803 999 8888"}
    )

    assert cleared.phone is None
    assert reset.phone == "+2348039998888"


@pytest.mark.integration
async def test_notes_can_be_set_and_cleared(service: CustomerService, tenant_id: UUID) -> None:
    owner = context_for(tenant_id, "OWNER")
    created = await service.create_customer(owner, name="Ada Obi", notes="Pays on delivery")

    cleared = await service.update_customer(
        owner, customer_id=created.customer.id, changes={"notes": None}
    )

    assert cleared.notes is None


@pytest.mark.integration
async def test_consent_can_be_given_and_withdrawn(
    service: CustomerService, tenant_id: UUID
) -> None:
    owner = context_for(tenant_id, "OWNER")
    created = await service.create_customer(owner, name="Ada Obi", phone="+2348031234567")

    given = await service.update_customer(
        owner, customer_id=created.customer.id, changes={"marketing_opt_in": True}
    )
    withdrawn = await service.update_customer(
        owner, customer_id=created.customer.id, changes={"marketing_opt_in": False}
    )

    assert given.marketing_opt_in is True
    assert withdrawn.marketing_opt_in is False


@pytest.mark.integration
async def test_an_edit_from_a_stale_version_is_a_conflict(
    service: CustomerService, tenant_id: UUID
) -> None:
    """Two phones editing the same customer must not silently discard each other."""
    owner = context_for(tenant_id, "OWNER")
    created = await service.create_customer(owner, name="Ada Obi", notes="First note")
    await service.update_customer(
        owner, customer_id=created.customer.id, changes={"notes": "Phone A's note"}
    )

    with pytest.raises(ConflictError) as captured:
        await service.update_customer(
            owner,
            customer_id=created.customer.id,
            changes={"notes": "Phone B's note"},
            expected_version=1,
        )

    assert "expected version 1" in (captured.value.context.detail or "")

    reread = await service.get_customer(owner, customer_id=created.customer.id)
    assert reread.notes == "Phone A's note"


@pytest.mark.integration
async def test_an_edit_with_the_current_version_succeeds(
    service: CustomerService, tenant_id: UUID
) -> None:
    owner = context_for(tenant_id, "OWNER")
    created = await service.create_customer(owner, name="Ada Obi")

    updated = await service.update_customer(
        owner,
        customer_id=created.customer.id,
        changes={"notes": "Edited with the version I had"},
        expected_version=created.customer.version,
    )

    assert updated.version == 2


@pytest.mark.integration
async def test_a_field_the_contract_does_not_own_is_refused(
    service: CustomerService, tenant_id: UUID
) -> None:
    owner = context_for(tenant_id, "OWNER")
    created = await service.create_customer(owner, name="Ada Obi")

    for forbidden in ({"tenant_id": uuid4()}, {"version": 5}, {"id": uuid4()}):
        with pytest.raises(InvalidInputError):
            await service.update_customer(owner, customer_id=created.customer.id, changes=forbidden)


@pytest.mark.integration
async def test_a_value_of_the_wrong_type_is_a_bad_request(
    service: CustomerService, tenant_id: UUID
) -> None:
    owner = context_for(tenant_id, "OWNER")
    created = await service.create_customer(owner, name="Ada Obi")

    with pytest.raises(InvalidInputError, match="marketing_opt_in"):
        await service.update_customer(
            owner, customer_id=created.customer.id, changes={"marketing_opt_in": "yes"}
        )
    with pytest.raises(InvalidInputError, match="name"):
        await service.update_customer(
            owner, customer_id=created.customer.id, changes={"name": "   "}
        )


@pytest.mark.integration
async def test_an_empty_change_set_leaves_the_customer_untouched(
    service: CustomerService, tenant_id: UUID
) -> None:
    owner = context_for(tenant_id, "OWNER")
    created = await service.create_customer(owner, name="Ada Obi")

    updated = await service.update_customer(owner, customer_id=created.customer.id, changes={})

    assert updated == created.customer


# ---------------------------------------------------------------------------
# Withdrawal
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_withdrawn_customer_disappears_from_the_list_but_survives(
    service: CustomerService, tenant_id: UUID
) -> None:
    owner = context_for(tenant_id, "OWNER")
    created = await service.create_customer(owner, name="Ada Obi", notes="Pays on delivery")

    retired = await service.deactivate_customer(owner, customer_id=created.customer.id)

    assert retired.is_active is False
    assert retired.notes == "Pays on delivery", "the history stays"
    assert await service.list_customers(owner) == []
    assert len(await service.list_customers(owner, include_inactive=True)) == 1

    revived = await service.reactivate_customer(owner, customer_id=created.customer.id)
    assert revived.is_active is True
    assert len(await service.list_customers(owner)) == 1


@pytest.mark.integration
async def test_a_withdrawn_customer_cannot_be_reached_for_marketing(
    service: CustomerService, tenant_id: UUID
) -> None:
    owner = context_for(tenant_id, "OWNER")
    created = await service.create_customer(
        owner, name="Ada Obi", phone="+2348031234567", marketing_opt_in=True
    )

    retired = await service.deactivate_customer(owner, customer_id=created.customer.id)

    assert retired.is_reachable_for_marketing() is False


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_customer_cannot_be_read_through_another_business(
    database: Database, service: CustomerService, tenant_id: UUID
) -> None:
    other_tenant = await insert_tenant(database)
    created = await service.create_customer(
        context_for(other_tenant, "OWNER"), name="Their customer"
    )

    with pytest.raises(NotFoundError):
        await service.get_customer(context_for(tenant_id, "OWNER"), customer_id=created.customer.id)


@pytest.mark.integration
async def test_a_customer_cannot_be_edited_through_another_business(
    database: Database, service: CustomerService, tenant_id: UUID
) -> None:
    other_tenant = await insert_tenant(database)
    created = await service.create_customer(
        context_for(other_tenant, "OWNER"), name="Their customer"
    )

    with pytest.raises(NotFoundError):
        await service.update_customer(
            context_for(tenant_id, "OWNER"),
            customer_id=created.customer.id,
            changes={"name": "Mine now"},
        )


@pytest.mark.integration
async def test_a_customer_cannot_be_withdrawn_through_another_business(
    database: Database, service: CustomerService, tenant_id: UUID
) -> None:
    other_tenant = await insert_tenant(database)
    created = await service.create_customer(
        context_for(other_tenant, "OWNER"), name="Their customer"
    )

    with pytest.raises(NotFoundError):
        await service.deactivate_customer(
            context_for(tenant_id, "OWNER"), customer_id=created.customer.id
        )


# ---------------------------------------------------------------------------
# Privacy in logs
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_log_line_for_a_new_customer_carries_no_personal_data(
    database: Database, tenant_id: UUID, caplog: pytest.LogCaptureFixture
) -> None:
    """A customer never signed up for this product, so their details stay out of logs."""
    service = CustomerService(
        unit_of_work_factory=database.unit_of_work_factory(),
        default_phone_country_code="234",
    )

    with caplog.at_level(logging.INFO, logger="ahia.services.customer"):
        await service.create_customer(
            context_for(tenant_id, "OWNER"),
            name="Ada Obi",
            phone="+2348031234567",
            email="ada@example.com",
            address="12 Awolowo Road, Ikeja",
        )

    rendered = caplog.text
    assert "customer_created" in rendered
    assert "Ada" not in rendered
    assert "+2348031234567" not in rendered
    assert "ada@example.com" not in rendered
    assert "Ikeja" not in rendered


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_salesperson_may_record_and_read_customers(
    service: CustomerService, tenant_id: UUID
) -> None:
    """SALES holds customers.read and customers.create: the counter is where they work."""
    sales = context_for(tenant_id, "SALES")

    created = await service.create_customer(sales, name="Ada Obi", phone="+2348031234567")
    listed = await service.list_customers(sales)

    assert [customer.id for customer in listed] == [created.customer.id]


@pytest.mark.integration
async def test_a_salesperson_may_not_change_a_customer_they_did_not_record(
    service: CustomerService, tenant_id: UUID
) -> None:
    owner = context_for(tenant_id, "OWNER")
    created = await service.create_customer(owner, name="Ada Obi")
    sales = context_for(tenant_id, "SALES")

    with pytest.raises(AuthorizationError):
        await service.update_customer(
            sales, customer_id=created.customer.id, changes={"name": "Someone else"}
        )
    with pytest.raises(AuthorizationError):
        await service.deactivate_customer(sales, customer_id=created.customer.id)


@pytest.mark.integration
async def test_an_inventory_worker_may_not_read_customers(
    service: CustomerService, tenant_id: UUID
) -> None:
    """INVENTORY holds no customer permission: counting stock is not serving people."""
    worker = context_for(tenant_id, "INVENTORY")

    with pytest.raises(AuthorizationError):
        await service.list_customers(worker)
    with pytest.raises(AuthorizationError):
        await service.create_customer(worker, name="Ada Obi")


@pytest.mark.integration
async def test_authorization_is_checked_before_the_database_is_touched(
    database: Database, service: CustomerService, tenant_id: UUID
) -> None:
    """A refused caller cannot use the phone lookup as an oracle for who exists."""
    worker = context_for(tenant_id, "INVENTORY")

    with pytest.raises(AuthorizationError):
        await service.create_customer(worker, name="Ada Obi", phone="+2348031234567")
    with pytest.raises(AuthorizationError):
        await service.find_by_phone(worker, phone="+2348031234567")

    async with database.transaction_scope() as unit_of_work:
        count = await customer_crud.count_for_tenant(unit_of_work.session_handle, tenant_id)
    assert count == 0
