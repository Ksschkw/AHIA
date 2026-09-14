"""Expense use cases: recording what the business spent, and accounting for it.

**Recording an expense is two writes in one transaction, and the ledger is the second one.**
An expense with no ledger entry is money that left the business and was never accounted for;
a ledger entry with no expense is a number nobody can explain. So `record_expense` writes
both inside the same unit of work, and a failure in either leaves neither behind. The ledger
entry is derived from the expense, never supplied by a caller: nothing in this product writes
an entry by hand, and a client that could choose the amount would be able to disagree with
the row it just created.

**A correction is a reversal plus a compensating entry, never an edit or a delete.** The
money moved, so the record of it stays. `reverse_expense` stamps when and why and appends an
`ADJUSTMENT` that credits the money back. That is what makes "what did we spend this month"
answerable from the ledger alone: the expense is a debit and its reversal is a credit, and a
report that reads either one gets the same answer as a report that reads both.

**Who reversed it is not a column on the expense, and that is deliberate.** Cancelling a sale
sets a moment and a reason for the same reason: a financial record answers "what happened and
why", and the principal is recorded where principals always are - the authorization decision
is logged with the actor, the resource, the action and the outcome, and the audit trail
records the mutation. Adding a `reversed_by` column here would put the actor in one table and
every other mutation's actor in the audit trail.

**Reversal needs the same permission as recording, and expense permissions are held by owners
and managers only.** The specification declares two expense permissions, `expenses.read` and
`expenses.create`; a salesperson and an inventory worker hold neither, so the authority to
correct an expense is the authority to record one, and the correction names its actor in the
log line. Inventing a third permission would put a code in the product that the specification
does not have.

**Reading and reporting need `expenses.read`.** `spending_by_category` exists as a service
method rather than a router that sums a list, because "total spending" is a business answer:
reversed expenses must not be counted and the boundaries of the period must not be a caller's
arithmetic. The database does the summing and excludes reversed rows, so a report cannot
forget to.

**An offline expense is recorded once.** When a caller supplies `operation_id` - the same
identifier the sync endpoint will use - an arrival that has already been recorded returns the
original expense with `was_replayed` set, and writes no second ledger entry. Recording the
same money twice is the failure this prevents.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.errors import InvalidInputError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions.expense_permissions import EXPENSES_CREATE, EXPENSES_READ
from ahia.core.tenant_context import TenantContext
from ahia.crud import expense_crud, ledger_entry_crud
from ahia.models.entities.expense_category import ExpenseCategory
from ahia.models.entities.expense_model import ExpenseModel
from ahia.models.entities.ledger_entry_model import (
    LedgerDirection,
    LedgerEntryModel,
    LedgerEntryType,
)
from ahia.models.entities.payment_model import PaymentMethod

_EXPENSE_LOGGER_NAME: Final[str] = "ahia.services.expense"

#: The vocabulary a ledger entry uses to point at the expense that caused it.
EXPENSE_REFERENCE_TYPE: Final[str] = "expense"

#: A reimbursement is caused by an expense but is not the expense, and a reader summing
#: entries needs to tell the two apart. The reference identifier is the same expense.
EXPENSE_REVERSAL_REFERENCE_TYPE: Final[str] = "expense_reversal"

#: What the compensating entry says. The reason itself stays on the expense row: the ledger
#: description has its own length bound, and copying free text into a second table where it
#: can never be corrected would create a second version of the same explanation.
EXPENSE_REVERSAL_NOTE: Final[str] = "expense reversed"


@dataclass(frozen=True, slots=True)
class RecordedExpense:
    """An expense that was recorded, and the ledger entry that accounts for it.

    `ledger_entry` is None when nothing was written by this call: a replayed operation
    returns the original expense, and a second reversal returns the expense unchanged. Both
    cases set `was_replayed`, so a caller can tell "I wrote this" from "this already existed"
    without asking the database. When an entry was written it is always present.
    """

    expense: ExpenseModel
    ledger_entry: LedgerEntryModel | None = None
    was_replayed: bool = False


class ExpenseService:
    """Expense use cases."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._logger = (logger or get_logger(_EXPENSE_LOGGER_NAME)).bind(
            component="expense_service", layer="service"
        )

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def record_expense(
        self,
        tenant_context: TenantContext,
        *,
        category: ExpenseCategory,
        amount: Decimal,
        payment_method: PaymentMethod = PaymentMethod.CASH,
        description: str | None = None,
        incurred_at: datetime | None = None,
        operation_id: UUID | None = None,
    ) -> RecordedExpense:
        """Record what the business spent and account for it in the ledger.

        The actor and the device come from the authorized context, never from the arguments:
        a caller cannot claim to have been somebody else, or on another device, when they
        recorded an expense.
        """
        tenant_context.require_permission(
            EXPENSES_CREATE,
            operation="record_expense",
            resource_type="expense",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle

            if operation_id is not None:
                already_recorded = await expense_crud.get_by_operation_id(
                    session, tenant_id=tenant_context.tenant_id, operation_id=operation_id
                )
                if already_recorded is not None:
                    self._logger.info(
                        "expense_operation_replayed",
                        tenant_id=str(tenant_context.tenant_id),
                        actor_id=str(tenant_context.user_id),
                        expense_id=str(already_recorded.id),
                        operation_id=str(operation_id),
                    )
                    return RecordedExpense(expense=already_recorded, was_replayed=True)

            expense = ExpenseModel.record(
                expense_id=uuid4(),
                tenant_id=tenant_context.tenant_id,
                category=category,
                amount=amount,
                payment_method=payment_method,
                description=description,
                incurred_at=incurred_at,
                actor_id=tenant_context.user_id,
                device_id=tenant_context.device_id,
                operation_id=operation_id,
                now=now,
            )
            stored = await expense_crud.create(session, expense)
            ledger_entry = await self._account_for(session, expense=stored, now=now)
            await unit_of_work.commit()

        self._logger.info(
            "expense_recorded",
            tenant_id=str(stored.tenant_id),
            actor_id=str(tenant_context.user_id),
            expense_id=str(stored.id),
            category=stored.category.value,
            amount=str(stored.amount),
            payment_method=stored.payment_method.value,
            incurred_at=stored.incurred_at.isoformat(),
            ledger_entry_id=str(ledger_entry.id),
        )
        return RecordedExpense(expense=stored, ledger_entry=ledger_entry)

    async def reverse_expense(
        self,
        tenant_context: TenantContext,
        *,
        expense_id: UUID,
        reason: str,
    ) -> RecordedExpense:
        """Undo an expense the business did not really spend, and credit the money back.

        Idempotent: the first reversal is the one that credited the money, so a second one
        changes nothing and appends nothing. That matters because a client that retried a
        timeout must not be able to reimburse the business twice.
        """
        tenant_context.require_permission(
            EXPENSES_CREATE,
            operation="reverse_expense",
            resource_type="expense",
            resource_id=str(expense_id),
            logger=self._logger,
        )
        resolved_reason = _require_reason(reason)

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            expense = await expense_crud.require_by_id(
                session, tenant_id=tenant_context.tenant_id, expense_id=expense_id
            )

            if expense.has_been_reversed():
                self._logger.info(
                    "expense_reversal_replayed",
                    tenant_id=str(expense.tenant_id),
                    actor_id=str(tenant_context.user_id),
                    expense_id=str(expense.id),
                )
                return RecordedExpense(expense=expense, was_replayed=True)

            reversed_expense = await expense_crud.update(
                session, expense.reversed(at=now, reason=resolved_reason)
            )
            ledger_entry = await self._compensate_for(session, expense=reversed_expense, now=now)
            await unit_of_work.commit()

        # Logged at warning level, like a cancelled sale: money that was booked as spent is
        # now booked as returned, and that is an event somebody may have to explain.
        self._logger.warning(
            "expense_reversed",
            tenant_id=str(reversed_expense.tenant_id),
            actor_id=str(tenant_context.user_id),
            expense_id=str(reversed_expense.id),
            category=reversed_expense.category.value,
            amount=str(reversed_expense.amount),
            ledger_entry_id=str(ledger_entry.id),
            security_event="expense_reversed",
        )
        return RecordedExpense(expense=reversed_expense, ledger_entry=ledger_entry)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    async def get_expense(
        self,
        tenant_context: TenantContext,
        *,
        expense_id: UUID,
    ) -> ExpenseModel:
        """Return one expense, or refuse as if it did not exist."""
        tenant_context.require_permission(
            EXPENSES_READ,
            operation="get_expense",
            resource_type="expense",
            resource_id=str(expense_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await expense_crud.require_by_id(
                unit_of_work.session_handle,
                tenant_id=tenant_context.tenant_id,
                expense_id=expense_id,
            )

    async def list_expenses(
        self,
        tenant_context: TenantContext,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        category: ExpenseCategory | None = None,
        limit: int = 100,
    ) -> list[ExpenseModel]:
        """Return the business's expenses, most recently incurred first.

        Reversed expenses are included: the list is the record of what was entered, and a
        person looking for the expense they reversed has to be able to find it. The reported
        total is a different question, and `spending_by_category` answers that one.
        """
        tenant_context.require_permission(
            EXPENSES_READ,
            operation="list_expenses",
            resource_type="expense",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await expense_crud.list_for_tenant(
                unit_of_work.session_handle,
                tenant_context.tenant_id,
                since=since,
                until=until,
                category=category,
                limit=limit,
            )

    async def spending_by_category(
        self,
        tenant_context: TenantContext,
        *,
        since: datetime,
        until: datetime,
    ) -> dict[ExpenseCategory, Decimal]:
        """Return what the business spent per category in a period.

        Categories with no spending are absent rather than zero: a report that shows every
        category would be this service deciding what a display lists, and `OTHER` would never
        be visible as the category a business should stop using.
        """
        tenant_context.require_permission(
            EXPENSES_READ,
            operation="report_spending_by_category",
            resource_type="expense",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await expense_crud.sum_by_category(
                unit_of_work.session_handle,
                tenant_context.tenant_id,
                since=since,
                until=until,
            )

    # ------------------------------------------------------------------
    # The ledger
    # ------------------------------------------------------------------

    async def _account_for(
        self,
        session: object,
        *,
        expense: ExpenseModel,
        now: datetime,
    ) -> LedgerEntryModel:
        """Append the debit that accounts for the money that left the business."""
        return await ledger_entry_crud.record(
            session,  # type: ignore[arg-type]
            LedgerEntryModel.record(
                entry_id=uuid4(),
                tenant_id=expense.tenant_id,
                entry_type=LedgerEntryType.EXPENSE,
                amount=expense.amount,
                reference_type=EXPENSE_REFERENCE_TYPE,
                reference_id=expense.id,
                now=now,
            ),
        )

    async def _compensate_for(
        self,
        session: object,
        *,
        expense: ExpenseModel,
        now: datetime,
    ) -> LedgerEntryModel:
        """Append the credit that reverses a debit already in the ledger.

        An `ADJUSTMENT` rather than a second `EXPENSE`: the original entry stays exactly as
        it was written, and this one says the money came back. An `EXPENSE` entry is always a
        debit, so reusing it here would be refused by the entity - which is the point of the
        direction rule.
        """
        return await ledger_entry_crud.record(
            session,  # type: ignore[arg-type]
            LedgerEntryModel.record(
                entry_id=uuid4(),
                tenant_id=expense.tenant_id,
                entry_type=LedgerEntryType.ADJUSTMENT,
                direction=LedgerDirection.CREDIT,
                amount=expense.amount,
                reference_type=EXPENSE_REVERSAL_REFERENCE_TYPE,
                reference_id=expense.id,
                now=now,
                description=EXPENSE_REVERSAL_NOTE,
            ),
        )


def _require_reason(reason: object) -> str:
    """Return the reason, or refuse it before a transaction is opened."""
    if not isinstance(reason, str) or not reason.strip():
        raise InvalidInputError(
            operation="reverse_expense",
            entity="expense",
            detail="a reason is required: a reversal without one is an unexplained correction",
        )
    return reason.strip()
