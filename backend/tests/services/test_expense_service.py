"""Tests for the expense use cases.

Four properties of this layer are the subject.

**The ledger is written with the expense, in one transaction.** An expense with no entry is
money that left the business unaccounted for, and an entry with no expense is a number
nobody can explain. The tests read the entry back by its reference, and assert that a write
that fails takes the other half with it.

**Reversal credits the money back rather than editing history.** The original debit stays
exactly as written and an `ADJUSTMENT` credits it, so the net effect on the business's money
for that expense is zero - asserted as a sum over the ledger, not as a flag on a row.

**Authorization is enforced here, not only in the router.** A salesperson holds neither
expense permission, and the refusal is asserted for every use case this service offers, with
a log line naming the principal, the resource and the outcome.

**A business's expenses are invisible to another business.** Through every path: reading one,
listing, reporting and reversing.
"""

from __future__ import annotations

import logging
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
from ahia.core.errors import (
    AuthorizationError,
    EntityInvariantError,
    InvalidInputError,
    NotFoundError,
    PersistenceError,
)
from ahia.core.permissions.expense_permissions import EXPENSES_CREATE
from ahia.core.permissions.permissions_registry import permission_codes_for_role
from ahia.core.tenant_context import TenantContext, build_tenant_context
from ahia.crud import device_crud, expense_crud, ledger_entry_crud, tenant_crud, user_crud
from ahia.models.entities.device_model import DeviceModel
from ahia.models.entities.expense_category import ExpenseCategory
from ahia.models.entities.ledger_entry_model import LedgerDirection, LedgerEntryType
from ahia.models.entities.payment_model import PaymentMethod
from ahia.models.entities.tenant_model import TenantModel
from ahia.models.entities.user_model import UserModel
from ahia.services.expense_service import (
    EXPENSE_REFERENCE_TYPE,
    EXPENSE_REVERSAL_REFERENCE_TYPE,
    ExpenseService,
)

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 14, 9, 30, tzinfo=UTC)
LATER = NOW + timedelta(hours=3)


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
        # The whole schema, created from the models. A table's foreign keys require the
        # tables they reference to exist first, and creating everything in dependency order
        # is exactly what create_all does.
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(sync_connection, checkfirst=True)
        )
        await connection.execute(
            text("TRUNCATE TABLE expenses, ledger_entries, devices, tenants, users CASCADE")
        )
    try:
        yield instance
    finally:
        await instance.dispose()


@pytest.fixture
def service(database: Database) -> ExpenseService:
    return ExpenseService(unit_of_work_factory=database.unit_of_work_factory())


async def insert_tenant(database: Database, *, name: str = "Obi Electronics") -> UUID:
    identifier = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await tenant_crud.create(
            unit_of_work.session_handle,
            TenantModel.create(
                tenant_id=identifier,
                name=name,
                slug=f"obi-{identifier.hex[:8]}",
                now=NOW,
            ),
        )
        await unit_of_work.commit()
    return identifier


async def insert_user(database: Database) -> UUID:
    identifier = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await user_crud.create(
            unit_of_work.session_handle,
            UserModel.create(
                user_id=identifier,
                first_name="Emeka",
                email=f"emeka.{identifier.hex[:8]}@example.com",
                now=NOW,
            ),
        )
        await unit_of_work.commit()
    return identifier


@pytest.fixture
async def tenant_id(database: Database) -> UUID:
    return await insert_tenant(database)


async def insert_device(database: Database, *, tenant_id: UUID, user_id: UUID) -> UUID:
    """Register a device the way the device use case does, so the foreign key holds."""
    identifier = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await device_crud.create(
            unit_of_work.session_handle,
            DeviceModel.register(
                device_id=identifier,
                tenant_id=tenant_id,
                user_id=user_id,
                device_identifier=f"device-{identifier.hex[:8]}",
                platform="android",
                now=NOW,
            ),
        )
        await unit_of_work.commit()
    return identifier


@pytest.fixture
async def actor_id(database: Database) -> UUID:
    """The user who records the expenses in these tests.

    A required fixture rather than a random identifier, because `expenses.actor_id` is a
    foreign key to `users`: an expense is recorded by somebody who exists.
    """
    return await insert_user(database)


def context_for(
    tenant_id: UUID,
    role_name: str,
    *,
    actor_id: UUID,
    device_id: UUID | None = None,
) -> TenantContext:
    return build_tenant_context(
        user_id=actor_id,
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=permission_codes_for_role(role_name),
        role_name=role_name,
        device_id=device_id,
    )


async def ledger_entries_for(database: Database, *, tenant_id: UUID, expense_id: UUID) -> list[Any]:
    """Return every entry that points at one expense, whichever reference type it used."""
    entries = []
    for reference_type in (EXPENSE_REFERENCE_TYPE, EXPENSE_REVERSAL_REFERENCE_TYPE):
        async with database.transaction_scope() as unit_of_work:
            entries.extend(
                await ledger_entry_crud.list_for_reference(
                    unit_of_work.session_handle,
                    tenant_id=tenant_id,
                    reference_type=reference_type,
                    reference_id=expense_id,
                )
            )
    return entries


async def net_ledger_amount(database: Database, tenant_id: UUID) -> Decimal:
    async with database.transaction_scope() as unit_of_work:
        return await ledger_entry_crud.total_signed_amount(unit_of_work.session_handle, tenant_id)


# ---------------------------------------------------------------------------
# Recording, and the ledger entry that goes with it
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_recording_an_expense_writes_it_and_debits_the_ledger(
    service: ExpenseService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    recorded = await service.record_expense(
        context_for(tenant_id, "OWNER", actor_id=actor_id),
        category=ExpenseCategory.STOCK_PURCHASE,
        amount=Decimal("120000.00"),
        payment_method=PaymentMethod.BANK_TRANSFER,
        description="Two bags of rice from Alhaji",
    )

    assert recorded.was_replayed is False
    assert recorded.expense.actor_id == actor_id
    assert recorded.expense.category is ExpenseCategory.STOCK_PURCHASE
    assert recorded.ledger_entry is not None
    assert recorded.ledger_entry.entry_type is LedgerEntryType.EXPENSE
    assert recorded.ledger_entry.direction is LedgerDirection.DEBIT
    assert recorded.ledger_entry.amount == Decimal("120000.00")
    assert recorded.ledger_entry.reference_type == EXPENSE_REFERENCE_TYPE
    assert recorded.ledger_entry.reference_id == recorded.expense.id

    stored = await ledger_entries_for(database, tenant_id=tenant_id, expense_id=recorded.expense.id)
    assert len(stored) == 1
    assert await net_ledger_amount(database, tenant_id) == Decimal("-120000.00")


@pytest.mark.integration
async def test_the_actor_and_device_come_from_the_authorized_context(
    service: ExpenseService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    device_id = await insert_device(database, tenant_id=tenant_id, user_id=actor_id)

    recorded = await service.record_expense(
        context_for(tenant_id, "OWNER", actor_id=actor_id, device_id=device_id),
        category=ExpenseCategory.TRANSPORT,
        amount=Decimal("2500.00"),
    )

    assert recorded.expense.actor_id == actor_id
    assert recorded.expense.device_id == device_id


@pytest.mark.integration
async def test_a_back_dated_expense_keeps_the_day_it_was_paid(
    service: ExpenseService,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    paid_on = datetime(2026, 9, 1, 8, 30, tzinfo=UTC)

    recorded = await service.record_expense(
        context_for(tenant_id, "MANAGER", actor_id=actor_id),
        category=ExpenseCategory.RENT,
        amount=Decimal("150000.00"),
        incurred_at=paid_on,
    )

    assert recorded.expense.incurred_at == paid_on


@pytest.mark.integration
async def test_a_negative_amount_is_refused_before_anything_is_written(
    service: ExpenseService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    with pytest.raises(EntityInvariantError):
        await service.record_expense(
            context_for(tenant_id, "OWNER", actor_id=actor_id),
            category=ExpenseCategory.OTHER,
            amount=Decimal("-100.00"),
        )

    assert await net_ledger_amount(database, tenant_id) == Decimal("0")


@pytest.mark.integration
async def test_a_ledger_failure_rolls_the_expense_back(
    service: ExpenseService,
    database: Database,
    tenant_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
    actor_id: UUID,
) -> None:
    """The expense and its entry land together or not at all.

    The failure is injected at the ledger boundary because that is the write that can fail
    after the expense row has been flushed. If the unit of work did not own both writes, the
    business would be left with money spent that the ledger never saw.
    """

    async def refuse_to_record(*args: object, **kwargs: object) -> Any:
        raise PersistenceError(
            operation="record_expense",
            entity="ledger_entry",
            detail="the ledger refused the entry",
        )

    monkeypatch.setattr(ledger_entry_crud, "record", refuse_to_record)

    with pytest.raises(PersistenceError):
        await service.record_expense(
            context_for(tenant_id, "OWNER", actor_id=actor_id),
            category=ExpenseCategory.UTILITIES,
            amount=Decimal("8000.00"),
        )

    async with database.transaction_scope() as unit_of_work:
        stored = await expense_crud.list_for_tenant(unit_of_work.session_handle, tenant_id)

    assert stored == [], "the expense must not survive a ledger write that failed"


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_replaying_an_operation_returns_the_original_and_writes_nothing(
    service: ExpenseService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    operation_id = uuid4()
    context = context_for(tenant_id, "OWNER", actor_id=actor_id)
    first = await service.record_expense(
        context,
        category=ExpenseCategory.PACKAGING,
        amount=Decimal("15000.00"),
        operation_id=operation_id,
    )

    replayed = await service.record_expense(
        context,
        category=ExpenseCategory.PACKAGING,
        amount=Decimal("15000.00"),
        operation_id=operation_id,
    )

    assert replayed.was_replayed is True
    assert replayed.expense.id == first.expense.id
    assert replayed.ledger_entry is None
    entries = await ledger_entries_for(database, tenant_id=tenant_id, expense_id=first.expense.id)
    assert len(entries) == 1
    assert await net_ledger_amount(database, tenant_id) == Decimal("-15000.00")


# ---------------------------------------------------------------------------
# Reversal
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_reversing_an_expense_credits_the_money_back(
    service: ExpenseService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    recorded = await service.record_expense(
        context_for(tenant_id, "OWNER", actor_id=actor_id),
        category=ExpenseCategory.MARKETING,
        amount=Decimal("9000.00"),
    )

    reversed_expense = await service.reverse_expense(
        context_for(tenant_id, "OWNER", actor_id=actor_id),
        expense_id=recorded.expense.id,
        reason="the radio slot never ran",
    )

    assert reversed_expense.was_replayed is False
    assert reversed_expense.expense.has_been_reversed() is True
    assert reversed_expense.ledger_entry is not None
    assert reversed_expense.ledger_entry.entry_type is LedgerEntryType.ADJUSTMENT
    assert reversed_expense.ledger_entry.direction is LedgerDirection.CREDIT
    assert reversed_expense.ledger_entry.amount == Decimal("9000.00")
    assert reversed_expense.ledger_entry.reference_type == EXPENSE_REVERSAL_REFERENCE_TYPE

    entries = await ledger_entries_for(
        database, tenant_id=tenant_id, expense_id=recorded.expense.id
    )
    assert len(entries) == 2, "the debit stays and the credit is appended beside it"
    assert await net_ledger_amount(database, tenant_id) == Decimal("0.00")


@pytest.mark.integration
async def test_reversing_twice_keeps_one_compensating_entry(
    service: ExpenseService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    context = context_for(tenant_id, "OWNER", actor_id=actor_id)
    recorded = await service.record_expense(
        context, category=ExpenseCategory.MAINTENANCE, amount=Decimal("12000.00")
    )
    await service.reverse_expense(
        context, expense_id=recorded.expense.id, reason="the vendor cancelled the order"
    )

    again = await service.reverse_expense(
        context, expense_id=recorded.expense.id, reason="something else entirely"
    )

    assert again.was_replayed is True
    assert again.ledger_entry is None
    assert again.expense.reversal_reason == "the vendor cancelled the order"
    entries = await ledger_entries_for(
        database, tenant_id=tenant_id, expense_id=recorded.expense.id
    )
    assert len(entries) == 2
    assert await net_ledger_amount(database, tenant_id) == Decimal("0.00")


@pytest.mark.integration
async def test_a_reversal_without_a_reason_is_refused(
    service: ExpenseService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    context = context_for(tenant_id, "OWNER", actor_id=actor_id)
    recorded = await service.record_expense(
        context, category=ExpenseCategory.OTHER, amount=Decimal("500.00")
    )

    with pytest.raises(InvalidInputError):
        await service.reverse_expense(context, expense_id=recorded.expense.id, reason="   ")

    async with database.transaction_scope() as unit_of_work:
        unchanged = await expense_crud.require_by_id(
            unit_of_work.session_handle, tenant_id=tenant_id, expense_id=recorded.expense.id
        )
    assert unchanged.has_been_reversed() is False


@pytest.mark.integration
async def test_reversing_an_unknown_expense_is_reported_as_missing(
    service: ExpenseService,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    with pytest.raises(NotFoundError):
        await service.reverse_expense(
            context_for(tenant_id, "OWNER", actor_id=actor_id),
            expense_id=uuid4(),
            reason="recorded twice",
        )


# ---------------------------------------------------------------------------
# Reading and reporting
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_reading_an_expense_returns_it(
    service: ExpenseService,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    context = context_for(tenant_id, "MANAGER", actor_id=actor_id)
    recorded = await service.record_expense(
        context, category=ExpenseCategory.SALARIES, amount=Decimal("60000.00")
    )

    fetched = await service.get_expense(context, expense_id=recorded.expense.id)

    assert fetched.id == recorded.expense.id


@pytest.mark.integration
async def test_listing_includes_a_reversed_expense(
    service: ExpenseService,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    context = context_for(tenant_id, "OWNER", actor_id=actor_id)
    recorded = await service.record_expense(
        context, category=ExpenseCategory.FEES_AND_LEVIES, amount=Decimal("2000.00")
    )
    await service.reverse_expense(
        context, expense_id=recorded.expense.id, reason="the charge was reversed by the bank"
    )

    listed = await service.list_expenses(context)

    assert [expense.id for expense in listed] == [recorded.expense.id]


@pytest.mark.integration
async def test_spending_per_category_excludes_reversed_expenses(
    service: ExpenseService,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    context = context_for(tenant_id, "OWNER", actor_id=actor_id)
    await service.record_expense(
        context, category=ExpenseCategory.TRANSPORT, amount=Decimal("3500.00")
    )
    to_reverse = await service.record_expense(
        context, category=ExpenseCategory.MARKETING, amount=Decimal("9000.00")
    )
    await service.reverse_expense(
        context, expense_id=to_reverse.expense.id, reason="the post was never published"
    )

    totals = await service.spending_by_category(context, since=NOW - timedelta(days=1), until=LATER)

    assert totals == {ExpenseCategory.TRANSPORT: Decimal("3500.00")}


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_salesperson_cannot_record_an_expense(
    service: ExpenseService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    with pytest.raises(AuthorizationError):
        await service.record_expense(
            context_for(tenant_id, "SALES", actor_id=actor_id),
            category=ExpenseCategory.TRANSPORT,
            amount=Decimal("1000.00"),
        )

    assert await net_ledger_amount(database, tenant_id) == Decimal("0")


@pytest.mark.integration
async def test_an_inventory_worker_cannot_read_expenses(
    service: ExpenseService,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    with pytest.raises(AuthorizationError):
        await service.list_expenses(context_for(tenant_id, "INVENTORY", actor_id=actor_id))

    with pytest.raises(AuthorizationError):
        await service.get_expense(
            context_for(tenant_id, "INVENTORY", actor_id=actor_id), expense_id=uuid4()
        )

    with pytest.raises(AuthorizationError):
        await service.spending_by_category(
            context_for(tenant_id, "INVENTORY", actor_id=actor_id), since=NOW, until=LATER
        )


@pytest.mark.integration
async def test_a_salesperson_cannot_reverse_an_expense(
    service: ExpenseService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    recorded = await service.record_expense(
        context_for(tenant_id, "OWNER", actor_id=actor_id),
        category=ExpenseCategory.RENT,
        amount=Decimal("150000.00"),
    )

    with pytest.raises(AuthorizationError):
        await service.reverse_expense(
            context_for(tenant_id, "SALES", actor_id=actor_id),
            expense_id=recorded.expense.id,
            reason="I would like the money back",
        )

    assert await net_ledger_amount(database, tenant_id) == Decimal("-150000.00")


@pytest.mark.integration
async def test_a_denied_decision_is_logged_with_the_principal_and_the_resource(
    service: ExpenseService,
    tenant_id: UUID,
    actor_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A refusal names who asked, for what, and where it was refused.

    This is the one place where logging the denial matters as much as the allow: a
    permission that fails silently is a permission nobody can audit.
    """
    context = context_for(tenant_id, "SALES", actor_id=actor_id)

    with (
        caplog.at_level(logging.WARNING, logger="ahia.services.expense"),
        pytest.raises(AuthorizationError),
    ):
        await service.record_expense(
            context,
            category=ExpenseCategory.OTHER,
            amount=Decimal("100.00"),
        )

    denied = next(
        record for record in caplog.records if record.getMessage() == "authorization_denied"
    )
    assert denied.decision == "denied"
    assert denied.reason == "permission_absent"
    assert denied.actor_id == str(context.user_id)
    assert denied.tenant_id == str(tenant_id)
    assert denied.action == EXPENSES_CREATE
    assert denied.operation == "record_expense"
    assert denied.resource_type == "expense"


# ---------------------------------------------------------------------------
# Tenant scoping
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_another_business_cannot_read_list_or_reverse_an_expense(
    service: ExpenseService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    other_tenant = await insert_tenant(database, name="Ada Provisions")
    recorded = await service.record_expense(
        context_for(tenant_id, "OWNER", actor_id=actor_id),
        category=ExpenseCategory.TRANSPORT,
        amount=Decimal("3500.00"),
    )
    intruder = context_for(other_tenant, "OWNER", actor_id=actor_id)

    with pytest.raises(NotFoundError):
        await service.get_expense(intruder, expense_id=recorded.expense.id)

    with pytest.raises(NotFoundError):
        await service.reverse_expense(
            intruder, expense_id=recorded.expense.id, reason="not mine to reverse"
        )

    assert await service.list_expenses(intruder) == []
    assert (
        await service.spending_by_category(intruder, since=NOW - timedelta(days=1), until=LATER)
        == {}
    )


@pytest.mark.integration
async def test_another_business_cannot_replay_an_operation_identifier(
    service: ExpenseService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    other_tenant = await insert_tenant(database, name="Ada Provisions")
    operation_id = uuid4()
    first = await service.record_expense(
        context_for(tenant_id, "OWNER", actor_id=actor_id),
        category=ExpenseCategory.OTHER,
        amount=Decimal("1000.00"),
        operation_id=operation_id,
    )

    second = await service.record_expense(
        context_for(other_tenant, "OWNER", actor_id=actor_id),
        category=ExpenseCategory.OTHER,
        amount=Decimal("1000.00"),
        operation_id=operation_id,
    )

    assert second.was_replayed is False
    assert second.expense.id != first.expense.id
