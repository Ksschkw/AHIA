"""Persistence for the financial ledger.

One table, one entity, one file, and **no update or delete function exists in this module**.
That absence is the design, exactly as it is for the stock ledger: a correction is another
entry, so this file offers `record` and readers. A test asserts the absence mechanically,
because a helper added later "just to fix a typo in a description" would quietly turn the
financial history into a table somebody can rewrite.

The database enforces the same rule
    A trigger refuses UPDATE and DELETE. The application having no such function is a
    convention; the trigger holds for a psql session, a migration, and a future service that
    has not read this docstring.

Every entry names what caused it
    `(reference_type, reference_id)` is required and indexed, which is what makes "what does
    this amount belong to" answerable. An entry that cannot be attributed is a number
    somebody has to explain from memory.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    case,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.models.entities.ledger_entry_model import (
    MAXIMUM_REFERENCE_TYPE_LENGTH,
    LedgerDirection,
    LedgerEntryModel,
    LedgerEntryType,
)

_TABLE_NAME: Final[str] = "ledger_entries"
_MONEY_PRECISION: Final[int] = 18
_MONEY_SCALE: Final[int] = 2
_ENTRY_TYPE_LENGTH: Final[int] = 32
_DIRECTION_LENGTH: Final[int] = 16


class LedgerEntryRecord(Base):
    """The persistence representation of one financial entry."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(_ENTRY_TYPE_LENGTH), nullable=False)
    direction: Mapped[str] = mapped_column(String(_DIRECTION_LENGTH), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(_MONEY_PRECISION, _MONEY_SCALE), nullable=False)
    reference_type: Mapped[str] = mapped_column(
        String(MAXIMUM_REFERENCE_TYPE_LENGTH), nullable=False
    )
    reference_id: Mapped[UUID] = mapped_column(nullable=False)
    # TEXT rather than a bounded VARCHAR: the entity is where the bound lives, and a
    # second, weaker bound on the column would only be a second answer.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # What happened recently, which is the report a business reads first.
        Index("ix_ledger_entries_tenant_occurred", "tenant_id", "occurred_at"),
        # What does this amount belong to.
        Index(
            "ix_ledger_entries_tenant_reference",
            "tenant_id",
            "reference_type",
            "reference_id",
        ),
        # Revenue and expenses for a period.
        Index("ix_ledger_entries_tenant_type_occurred", "tenant_id", "entry_type", "occurred_at"),
    )


def to_entity(record: LedgerEntryRecord) -> LedgerEntryModel:
    return LedgerEntryModel(
        id=record.id,
        tenant_id=record.tenant_id,
        entry_type=LedgerEntryType(record.entry_type),
        direction=LedgerDirection(record.direction),
        amount=record.amount,
        reference_type=record.reference_type,
        reference_id=record.reference_id,
        occurred_at=record.occurred_at,
        created_at=record.created_at,
        description=record.description,
    )


def apply_entity(record: LedgerEntryRecord, entity: LedgerEntryModel) -> None:
    record.tenant_id = entity.tenant_id
    record.entry_type = entity.entry_type.value
    record.direction = entity.direction.value
    record.amount = entity.amount
    record.reference_type = entity.reference_type
    record.reference_id = entity.reference_id
    record.description = entity.description
    record.occurred_at = entity.occurred_at
    record.created_at = entity.created_at


async def record(session: AsyncSession, entry: LedgerEntryModel) -> LedgerEntryModel:
    """Append one entry to the ledger.

    There is no `update` and no `delete` beside this function, and the table refuses both at
    the database level. The only way to correct the ledger is to append to it.
    """
    row = LedgerEntryRecord(id=entry.id)
    apply_entity(row, entry)
    session.add(row)
    await session.flush()
    return to_entity(row)


async def list_for_tenant(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    limit: int = 100,
) -> list[LedgerEntryModel]:
    """Return a business's most recent entries."""
    result = await session.execute(
        select(LedgerEntryRecord)
        .where(LedgerEntryRecord.tenant_id == tenant_id)
        .order_by(LedgerEntryRecord.occurred_at.desc(), LedgerEntryRecord.id.desc())
        .limit(limit)
    )
    return [to_entity(row) for row in result.scalars().all()]


async def list_for_reference(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    reference_type: str,
    reference_id: UUID,
) -> list[LedgerEntryModel]:
    """Return the entries a single transaction produced.

    A sale writes a revenue entry and, when it is cancelled, a refund; reading them together
    is how a cancellation is explained.
    """
    result = await session.execute(
        select(LedgerEntryRecord)
        .where(LedgerEntryRecord.tenant_id == tenant_id)
        .where(LedgerEntryRecord.reference_type == reference_type)
        .where(LedgerEntryRecord.reference_id == reference_id)
        .order_by(LedgerEntryRecord.occurred_at, LedgerEntryRecord.id)
    )
    return [to_entity(row) for row in result.scalars().all()]


async def total_signed_amount(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    since: datetime | None = None,
) -> Decimal:
    """Return the net effect of the ledger on the business's money.

    Credits less debits, computed in SQL so a report does not have to load every entry into
    memory. It is the one place the direction becomes a sign in a query, and the entity's
    own `signed_amount` is the reference for what that sign means.
    """
    statement = select(
        func.coalesce(
            func.sum(
                # The direction becomes a sign in exactly one query, and the entity's own
                # `signed_amount` is the reference for what that sign means.
                case(
                    (
                        LedgerEntryRecord.direction == LedgerDirection.CREDIT.value,
                        LedgerEntryRecord.amount,
                    ),
                    else_=-LedgerEntryRecord.amount,
                )
            ),
            0,
        )
    ).where(LedgerEntryRecord.tenant_id == tenant_id)
    if since is not None:
        statement = statement.where(LedgerEntryRecord.occurred_at >= since)

    total = (await session.execute(statement)).scalar_one()
    return Decimal(total)


async def count_for_tenant(session: AsyncSession, tenant_id: UUID) -> int:
    """Return how many entries a business's ledger holds."""
    result = await session.execute(
        select(func.count())
        .select_from(LedgerEntryRecord)
        .where(LedgerEntryRecord.tenant_id == tenant_id)
    )
    return int(result.scalar_one())
