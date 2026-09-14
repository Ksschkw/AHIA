"""Tests for expenses persistence.

Four properties are tested here that only the database can prove.

An offline operation is recorded once
    Two inserts carrying the same `operation_id` for one business end as one expense; the
    second is refused as a conflict rather than paying for the same bag of cement twice. The
    index is partial, so expenses recorded without an operation identifier are unaffected.

The amount rule holds for a writer that never touches this product's code
    A raw insert of a negative amount is refused by a check constraint, not by the entity.
    A spending report sums this column, so the rule has to hold in the database too.

A reversal is a moment and a reason, together
    The check constraint refuses either one alone, for the same reason.

There is no way to delete an expense
    Asserted mechanically against the source, because a helper added later "to clean up a test
    entry" is how financial history becomes editable. There is no delete function, and the
    only mutation this module offers is a reversal.
"""

from __future__ import annotations

import ast
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.errors import ConflictError, NotFoundError
from ahia.crud import expense_crud, tenant_crud, user_crud
from ahia.models.entities.expense_category import ExpenseCategory
from ahia.models.entities.expense_model import ExpenseModel
from ahia.models.entities.payment_model import PaymentMethod
from ahia.models.entities.tenant_model import TenantModel
from ahia.models.entities.user_model import UserModel

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 14, 9, 30, tzinfo=UTC)
LATER = NOW + timedelta(hours=2)

EXPENSE_CRUD_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "ahia" / "crud" / "expense_crud.py"
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
        # The whole schema, created from the models. A table's foreign keys require the
        # tables they reference to exist first, and creating everything in dependency order
        # is exactly what create_all does.
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(sync_connection, checkfirst=True)
        )
        await connection.execute(text("TRUNCATE TABLE expenses, tenants, users CASCADE"))
    try:
        yield instance
    finally:
        await instance.dispose()


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


@pytest.fixture
async def actor_id(database: Database) -> UUID:
    return await insert_user(database)


def build_expense(
    *,
    tenant_id: UUID,
    actor_id: UUID,
    amount: Decimal = Decimal("3500.00"),
    **overrides: object,
) -> ExpenseModel:
    parameters: dict[str, object] = {
        "expense_id": uuid4(),
        "tenant_id": tenant_id,
        "category": ExpenseCategory.TRANSPORT,
        "amount": amount,
        "payment_method": PaymentMethod.CASH,
        "actor_id": actor_id,
        "now": NOW,
        "description": "Keke to the market and back",
    }
    parameters.update(overrides)
    return ExpenseModel.record(**parameters)  # type: ignore[arg-type]


async def persist_expense(database: Database, expense: ExpenseModel) -> ExpenseModel:
    async with database.transaction_scope() as unit_of_work:
        stored = await expense_crud.create(unit_of_work.session_handle, expense)
        await unit_of_work.commit()
    return stored


# ---------------------------------------------------------------------------
# Writing and reading back
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_an_expense_round_trips_through_storage(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    expense = build_expense(tenant_id=tenant_id, actor_id=actor_id)

    stored = await persist_expense(database, expense)

    async with database.transaction_scope() as unit_of_work:
        reread = await expense_crud.require_by_id(
            unit_of_work.session_handle, tenant_id=tenant_id, expense_id=expense.id
        )

    assert stored.id == expense.id
    assert reread.category is ExpenseCategory.TRANSPORT
    assert reread.amount == Decimal("3500.00")
    assert reread.payment_method is PaymentMethod.CASH
    assert reread.description == "Keke to the market and back"
    assert reread.incurred_at == NOW
    assert reread.created_at == NOW
    assert reread.has_been_reversed() is False


@pytest.mark.integration
async def test_expenses_of_two_businesses_do_not_see_each_other(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    other_tenant = await insert_tenant(database, name="Ada Provisions")
    expense = build_expense(tenant_id=tenant_id, actor_id=actor_id)
    await persist_expense(database, expense)

    async with database.transaction_scope() as unit_of_work:
        hidden = await expense_crud.get_by_id(
            unit_of_work.session_handle, tenant_id=other_tenant, expense_id=expense.id
        )
        listed = await expense_crud.list_for_tenant(unit_of_work.session_handle, other_tenant)

    assert hidden is None
    assert listed == []


@pytest.mark.integration
async def test_an_unknown_expense_is_reported_as_missing(
    database: Database, tenant_id: UUID
) -> None:
    with pytest.raises(NotFoundError) as raised:
        async with database.transaction_scope() as unit_of_work:
            await expense_crud.require_by_id(
                unit_of_work.session_handle, tenant_id=tenant_id, expense_id=uuid4()
            )

    assert "expense" in str(raised.value)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_an_offline_operation_is_recorded_once(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    operation_id = uuid4()
    first = build_expense(tenant_id=tenant_id, actor_id=actor_id, operation_id=operation_id)
    await persist_expense(database, first)

    async with database.transaction_scope() as unit_of_work:
        found = await expense_crud.get_by_operation_id(
            unit_of_work.session_handle, tenant_id=tenant_id, operation_id=operation_id
        )

    assert found is not None
    assert found.id == first.id


@pytest.mark.integration
async def test_replaying_an_operation_that_already_arrived_is_refused(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    operation_id = uuid4()
    await persist_expense(
        database,
        build_expense(tenant_id=tenant_id, actor_id=actor_id, operation_id=operation_id),
    )
    second = build_expense(tenant_id=tenant_id, actor_id=actor_id, operation_id=operation_id)

    with pytest.raises(ConflictError) as raised:
        await persist_expense(database, second)

    assert "already been recorded" in str(raised.value)


@pytest.mark.integration
async def test_two_businesses_may_use_the_same_operation_identifier(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    other_tenant = await insert_tenant(database, name="Ada Provisions")
    operation_id = uuid4()

    await persist_expense(
        database,
        build_expense(tenant_id=tenant_id, actor_id=actor_id, operation_id=operation_id),
    )
    stored = await persist_expense(
        database,
        build_expense(tenant_id=other_tenant, actor_id=actor_id, operation_id=operation_id),
    )

    assert stored.tenant_id == other_tenant


@pytest.mark.integration
async def test_expenses_recorded_without_an_operation_identifier_do_not_collide(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    first = await persist_expense(
        database, build_expense(tenant_id=tenant_id, actor_id=actor_id, operation_id=None)
    )
    second = await persist_expense(
        database, build_expense(tenant_id=tenant_id, actor_id=actor_id, operation_id=None)
    )

    assert first.id != second.id


# ---------------------------------------------------------------------------
# Constraints the database enforces
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_negative_amount_is_refused_by_the_database(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    with pytest.raises(DBAPIError) as raised:
        async with database.transaction_scope() as unit_of_work:
            await unit_of_work.session_handle.execute(
                text(
                    "INSERT INTO expenses (id, tenant_id, category, amount, payment_method, "
                    "incurred_at, actor_id, created_at) VALUES (:id, :tenant_id, 'TRANSPORT', "
                    "-100.00, 'CASH', :now, :actor_id, :now)"
                ),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "now": NOW,
                    "actor_id": actor_id,
                },
            )
            await unit_of_work.commit()

    assert "expense_amount_is_positive" in str(raised.value)


@pytest.mark.integration
async def test_a_reversal_reason_without_a_moment_is_refused_by_the_database(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    with pytest.raises(DBAPIError) as raised:
        async with database.transaction_scope() as unit_of_work:
            await unit_of_work.session_handle.execute(
                text(
                    "INSERT INTO expenses (id, tenant_id, category, amount, payment_method, "
                    "incurred_at, actor_id, reversal_reason, created_at) VALUES (:id, "
                    ":tenant_id, 'TRANSPORT', 100.00, 'CASH', :now, :actor_id, "
                    "'paid twice', :now)"
                ),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "now": NOW,
                    "actor_id": actor_id,
                },
            )
            await unit_of_work.commit()

    assert "expense_reversal_is_complete" in str(raised.value)


@pytest.mark.integration
async def test_an_expense_for_an_unknown_business_is_refused(
    database: Database, actor_id: UUID
) -> None:
    with pytest.raises(NotFoundError):
        await persist_expense(database, build_expense(tenant_id=uuid4(), actor_id=actor_id))


# ---------------------------------------------------------------------------
# Listing and reporting
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_listing_returns_the_most_recently_incurred_first(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    older = build_expense(
        tenant_id=tenant_id,
        actor_id=actor_id,
        incurred_at=NOW - timedelta(days=2),
        description="bag of cement",
    )
    newer = build_expense(
        tenant_id=tenant_id,
        actor_id=actor_id,
        incurred_at=NOW - timedelta(hours=1),
        description="generator fuel",
    )
    await persist_expense(database, older)
    await persist_expense(database, newer)

    async with database.transaction_scope() as unit_of_work:
        listed = await expense_crud.list_for_tenant(unit_of_work.session_handle, tenant_id)

    assert [expense.id for expense in listed] == [newer.id, older.id]


@pytest.mark.integration
async def test_a_period_excludes_the_moment_it_ends(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    inside = build_expense(tenant_id=tenant_id, actor_id=actor_id, incurred_at=NOW)
    on_the_boundary = build_expense(tenant_id=tenant_id, actor_id=actor_id, incurred_at=LATER)
    await persist_expense(database, inside)
    await persist_expense(database, on_the_boundary)

    async with database.transaction_scope() as unit_of_work:
        listed = await expense_crud.list_for_tenant(
            unit_of_work.session_handle, tenant_id, since=NOW, until=LATER
        )

    assert [expense.id for expense in listed] == [inside.id]


@pytest.mark.integration
async def test_listing_can_be_narrowed_to_one_category(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    transport = build_expense(tenant_id=tenant_id, actor_id=actor_id)
    rent = build_expense(
        tenant_id=tenant_id,
        actor_id=actor_id,
        category=ExpenseCategory.RENT,
        amount=Decimal("150000.00"),
    )
    await persist_expense(database, transport)
    await persist_expense(database, rent)

    async with database.transaction_scope() as unit_of_work:
        listed = await expense_crud.list_for_tenant(
            unit_of_work.session_handle, tenant_id, category=ExpenseCategory.RENT
        )

    assert [expense.id for expense in listed] == [rent.id]


@pytest.mark.integration
async def test_spending_is_summed_per_category_and_excludes_reversed_expenses(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    await persist_expense(
        database,
        build_expense(tenant_id=tenant_id, actor_id=actor_id, amount=Decimal("3500.00")),
    )
    await persist_expense(
        database,
        build_expense(tenant_id=tenant_id, actor_id=actor_id, amount=Decimal("1500.00")),
    )
    await persist_expense(
        database,
        build_expense(
            tenant_id=tenant_id,
            actor_id=actor_id,
            category=ExpenseCategory.RENT,
            amount=Decimal("150000.00"),
        ),
    )
    reversed_expense = build_expense(
        tenant_id=tenant_id,
        actor_id=actor_id,
        category=ExpenseCategory.MARKETING,
        amount=Decimal("9000.00"),
    )
    stored = await persist_expense(database, reversed_expense)
    async with database.transaction_scope() as unit_of_work:
        await expense_crud.update(
            unit_of_work.session_handle,
            stored.reversed(at=LATER, reason="the radio slot never ran"),
        )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        totals = await expense_crud.sum_by_category(
            unit_of_work.session_handle, tenant_id, since=NOW - timedelta(days=1), until=LATER
        )

    assert totals[ExpenseCategory.TRANSPORT] == Decimal("5000.00")
    assert totals[ExpenseCategory.RENT] == Decimal("150000.00")
    assert ExpenseCategory.MARKETING not in totals


@pytest.mark.integration
async def test_a_reversed_expense_keeps_its_row_and_the_reason(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    stored = await persist_expense(database, build_expense(tenant_id=tenant_id, actor_id=actor_id))

    async with database.transaction_scope() as unit_of_work:
        await expense_crud.update(
            unit_of_work.session_handle,
            stored.reversed(at=LATER, reason="the vendor cancelled the order"),
        )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        reread = await expense_crud.require_by_id(
            unit_of_work.session_handle, tenant_id=tenant_id, expense_id=stored.id
        )

    assert reread.has_been_reversed() is True
    assert reread.reversed_at == LATER
    assert reread.reversal_reason == "the vendor cancelled the order"
    assert reread.amount == Decimal("3500.00")
    assert reread.counted_amount() == Decimal("0.00")


@pytest.mark.integration
async def test_reversing_an_unknown_expense_is_reported_as_missing(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    expense = build_expense(tenant_id=tenant_id, actor_id=actor_id)
    expense = expense.reversed(at=LATER, reason="recorded twice")

    with pytest.raises(NotFoundError):
        async with database.transaction_scope() as unit_of_work:
            await expense_crud.update(unit_of_work.session_handle, expense)
            await unit_of_work.commit()


# ---------------------------------------------------------------------------
# What this module deliberately does not offer
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_expense_persistence_offers_no_way_to_delete_an_expense() -> None:
    tree = ast.parse(EXPENSE_CRUD_PATH.read_text(encoding="utf-8"))
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    forbidden = {
        name
        for name in defined
        if name in {"delete", "remove", "purge", "destroy"} or name.startswith("delete_")
    }
    assert not forbidden, f"expenses gained a delete path: {sorted(forbidden)}"


@pytest.mark.unit
def test_expense_persistence_has_no_function_that_edits_an_amount() -> None:
    tree = ast.parse(EXPENSE_CRUD_PATH.read_text(encoding="utf-8"))
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    forbidden = {name for name in defined if name.startswith(("update_amount", "edit", "amend"))}
    assert not forbidden, f"an expense amount gained an edit path: {sorted(forbidden)}"
