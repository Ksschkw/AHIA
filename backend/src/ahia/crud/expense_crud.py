"""Persistence for the expense entity.

One table, one entity, one file. Four properties are worth stating.

There is no delete function, and its absence is the design
    An expense is financial history: the money left the business and a ledger entry recorded
    it. A mistaken expense is reversed, which stamps when and why and leaves the original
    row readable. A test asserts this module offers no way to remove a row, because a helper
    added later "to clean up a test entry" is exactly how a business ends up with spending
    reports that cannot be reconciled.

An offline operation is recorded once
    `UNIQUE(tenant_id, operation_id)` where the identifier is present. A phone that lost the
    response to an expense it queued will send it again; the constraint turns that second
    arrival into the original expense rather than a second one, so the business does not pay
    twice for one bag of cement.

The category is stored as a short string from a closed set
    The vocabulary lives in `expense_category` and is validated by the entity. The column is
    bounded by the same constant the vocabulary is checked against, so a category cannot be
    added in code that the database then refuses to store.

Reads are indexed by what a spending report asks
    "What did we spend in this period" is `(tenant_id, incurred_at)`; "what did we spend on
    this" is `(tenant_id, category, incurred_at)`. Both are declared here rather than
    discovered from a slow report later.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import NotFoundError
from ahia.crud.integrity_violations import constraint_name, translate_integrity_violation
from ahia.models.entities.expense_category import MAXIMUM_VALUE_LENGTH, ExpenseCategory
from ahia.models.entities.expense_model import (
    MAXIMUM_REVERSAL_REASON_LENGTH,
    ExpenseModel,
)
from ahia.models.entities.payment_model import PaymentMethod

_TABLE_NAME: Final[str] = "expenses"
_MONEY_PRECISION: Final[int] = 18
_MONEY_SCALE: Final[int] = 2
_PAYMENT_METHOD_LENGTH: Final[int] = 32

#: Why a write was refused, per constraint. The classification is shared; what each
#: constraint means is this table's business.
_CONFLICT_DETAILS: Final[dict[str, str]] = {
    "uq_expenses_tenant_id_operation_id": "this operation has already been recorded",
}

_MISSING_REFERENCE: Final[str] = (
    "the business, actor or device this expense references does not exist"
)


class ExpenseRecord(Base):
    """The persistence representation of one expense."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(MAXIMUM_VALUE_LENGTH), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(_MONEY_PRECISION, _MONEY_SCALE), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(_PAYMENT_METHOD_LENGTH), nullable=False)
    # TEXT rather than a bounded VARCHAR: the entity is where the bound lives, and a second,
    # weaker bound on the column would only be a second answer.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    incurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    # A device identifier is an opaque value taken from the authenticated context, so it is
    # a plain reference: the service cannot obtain one that belongs to another business.
    device_id: Mapped[UUID | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    operation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversal_reason: Mapped[str | None] = mapped_column(
        String(MAXIMUM_REVERSAL_REASON_LENGTH), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # The entity's amount rule, stated where neither an UPDATE nor a script can bypass
        # it: a spending report sums this column, and a negative row would silently reduce
        # the total it claims to report.
        CheckConstraint("amount > 0", name="expense_amount_is_positive"),
        # A reversal is a moment and a reason, together. One without the other is a row that
        # claims the money came back and cannot say why, or says why without saying when.
        CheckConstraint(
            "(reversed_at IS NULL) = (reversal_reason IS NULL)",
            name="expense_reversal_is_complete",
        ),
        # Idempotency: one expense per offline operation, per business.
        Index(
            "uq_expenses_tenant_id_operation_id",
            "tenant_id",
            "operation_id",
            unique=True,
            postgresql_where=text("operation_id IS NOT NULL"),
        ),
        Index("ix_expenses_tenant_incurred", "tenant_id", "incurred_at"),
        Index("ix_expenses_tenant_category_incurred", "tenant_id", "category", "incurred_at"),
    )


def to_entity(record: ExpenseRecord) -> ExpenseModel:
    return ExpenseModel(
        id=record.id,
        tenant_id=record.tenant_id,
        category=ExpenseCategory(record.category),
        amount=record.amount,
        payment_method=PaymentMethod(record.payment_method),
        incurred_at=record.incurred_at,
        actor_id=record.actor_id,
        created_at=record.created_at,
        device_id=record.device_id,
        operation_id=record.operation_id,
        description=record.description,
        reversed_at=record.reversed_at,
        reversal_reason=record.reversal_reason,
    )


def apply_entity(record: ExpenseRecord, entity: ExpenseModel) -> None:
    record.tenant_id = entity.tenant_id
    record.category = entity.category.value
    record.amount = entity.amount
    record.payment_method = entity.payment_method.value
    record.description = entity.description
    record.incurred_at = entity.incurred_at
    record.actor_id = entity.actor_id
    record.device_id = entity.device_id
    record.operation_id = entity.operation_id
    record.reversed_at = entity.reversed_at
    record.reversal_reason = entity.reversal_reason
    record.created_at = entity.created_at


def _conflict_detail(conflict: IntegrityError) -> str:
    name = constraint_name(conflict)
    return _CONFLICT_DETAILS.get(name, f"this expense collides with an existing one ({name})")


async def create(session: AsyncSession, expense: ExpenseModel) -> ExpenseModel:
    """Insert an expense, naming the rule that refused it when one does.

    Does not commit. The caller owns the transaction, because recording an expense also
    writes the ledger entry that accounts for the money, and the two must land together or
    neither must.
    """
    record = ExpenseRecord(id=expense.id)
    apply_entity(record, expense)
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise translate_integrity_violation(
            conflict,
            operation="record_expense",
            entity="expense",
            identifier=str(expense.id),
            conflict_detail=_conflict_detail(conflict),
            missing_detail=_MISSING_REFERENCE,
        ) from conflict
    return to_entity(record)


async def get_by_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    expense_id: UUID,
) -> ExpenseModel | None:
    """Return an expense by identifier, scoped to the business that recorded it."""
    result = await session.execute(
        select(ExpenseRecord)
        .where(ExpenseRecord.id == expense_id)
        .where(ExpenseRecord.tenant_id == tenant_id)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def require_by_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    expense_id: UUID,
) -> ExpenseModel:
    expense = await get_by_id(session, tenant_id=tenant_id, expense_id=expense_id)
    if expense is None:
        raise NotFoundError(
            operation="fetch_expense",
            entity="expense",
            identifier=str(expense_id),
            detail="no expense matched in this business",
        )
    return expense


async def get_by_operation_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    operation_id: UUID,
) -> ExpenseModel | None:
    """Return the expense an offline operation already produced, if it arrived before.

    This is what makes a replayed operation idempotent: the same identifier is recognised and
    the original expense is returned instead of a second one being written.
    """
    result = await session.execute(
        select(ExpenseRecord)
        .where(ExpenseRecord.tenant_id == tenant_id)
        .where(ExpenseRecord.operation_id == operation_id)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def list_for_tenant(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    limit: int = 100,
    since: datetime | None = None,
    until: datetime | None = None,
    category: ExpenseCategory | None = None,
) -> list[ExpenseModel]:
    """Return a business's expenses, most recently incurred first.

    The period boundaries are inclusive at the start and exclusive at the end, so
    consecutive periods tile without counting the same expense in both.
    """
    statement = select(ExpenseRecord).where(ExpenseRecord.tenant_id == tenant_id)
    if since is not None:
        statement = statement.where(ExpenseRecord.incurred_at >= since)
    if until is not None:
        statement = statement.where(ExpenseRecord.incurred_at < until)
    if category is not None:
        statement = statement.where(ExpenseRecord.category == category.value)
    result = await session.execute(
        statement.order_by(ExpenseRecord.incurred_at.desc(), ExpenseRecord.id.desc()).limit(limit)
    )
    return [to_entity(record) for record in result.scalars().all()]


async def sum_by_category(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    since: datetime,
    until: datetime,
) -> dict[ExpenseCategory, Decimal]:
    """Return what the business spent per category in a period.

    Reversed expenses are excluded in the database rather than filtered by a caller, because
    a report that forgot to filter would overstate spending and look perfectly plausible.
    Categories with no spending are absent from the result rather than present as zero: the
    caller knows the vocabulary, and inventing rows here would be this module deciding what a
    report displays.
    """
    result = await session.execute(
        select(ExpenseRecord.category, func.sum(ExpenseRecord.amount))
        .where(ExpenseRecord.tenant_id == tenant_id)
        .where(ExpenseRecord.incurred_at >= since)
        .where(ExpenseRecord.incurred_at < until)
        .where(ExpenseRecord.reversed_at.is_(None))
        .group_by(ExpenseRecord.category)
    )
    return {ExpenseCategory(row[0]): row[1] for row in result.all()}


async def update(session: AsyncSession, expense: ExpenseModel) -> ExpenseModel:
    """Persist a change to an existing expense, scoped to its business.

    The only legitimate change to an expense is its reversal. There is deliberately no
    function that edits the amount or the category after the fact: the amount that was spent
    is what was spent, and a correction is a reversal plus a new expense.
    """
    result = await session.execute(
        select(ExpenseRecord)
        .where(ExpenseRecord.id == expense.id)
        .where(ExpenseRecord.tenant_id == expense.tenant_id)
    )
    stored = result.scalar_one_or_none()
    if stored is None:
        raise NotFoundError(
            operation="reverse_expense",
            entity="expense",
            identifier=str(expense.id),
            detail="no expense matched in this business",
        )
    apply_entity(stored, expense)
    await session.flush()
    return to_entity(stored)
