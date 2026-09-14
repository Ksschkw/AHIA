"""Per-business receipt numbering.

A receipt number is what a customer quotes when they come back, so it has to be unique
within a business and it has to be issued once. Two tills selling at the same second must
not produce the same number, and the business must not discover the collision later while
looking for a sale that seems to be missing.

**How the guarantee is made.** One counter row per business, incremented under a row lock
inside the same transaction that writes the sale:

    INSERT ... ON CONFLICT (tenant_id) DO UPDATE SET last_receipt_number = ... + 1
    RETURNING last_receipt_number

PostgreSQL serialises the two concurrent updates on the row, so the second till waits and
then receives the next number. Reading `MAX(receipt_number) + 1` instead would let both
tills read the same maximum and write the same number - the mistake arrives as a unique
violation on one of them, after the sale has been rung up.

**Where the reading rules live.** Rendering a number and sanitising a prefix are domain
vocabulary, so they live on `ReceiptCounterModel`; this module is only the claim.

**Why the counter is a table rather than a sequence.** A PostgreSQL sequence belongs to the
schema, not to a tenant: `nextval` cannot be scoped, so every business would share one
counter and a customer would see their receipts jump by the number of sales other businesses
made. A row per business is the smallest thing that can be scoped, locked and rolled back
with the sale.

**What happens when a sale is rolled back.** The counter increment rolls back with it, so
the number is reused by the next sale. That is correct: a number that was never printed is
not a number anybody holds, and leaving gaps would make a business think receipts were lost.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import PersistenceError
from ahia.models.entities.receipt_counter_model import (
    MAXIMUM_PREFIX_LENGTH,
    ReceiptCounterModel,
    clean_receipt_prefix,
    render_receipt_number,
)

_TABLE_NAME: Final[str] = "receipt_counters"


class ReceiptCounterRecord(Base):
    """The next receipt number for one business."""

    __tablename__ = _TABLE_NAME

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id"), primary_key=True, nullable=False
    )
    # The highest number issued so far. Starts at zero, so the first receipt is 1.
    last_receipt_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Set when the counter is created, from the business's slug, and kept afterwards so a
    # reprinted receipt matches the one that was handed over.
    receipt_prefix: Mapped[str] = mapped_column(String(MAXIMUM_PREFIX_LENGTH), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def to_entity(record: ReceiptCounterRecord) -> ReceiptCounterModel:
    return ReceiptCounterModel(
        tenant_id=record.tenant_id,
        last_receipt_number=record.last_receipt_number,
        receipt_prefix=record.receipt_prefix,
        updated_at=record.updated_at,
    )


async def allocate_receipt_number(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    prefix: str,
    now: datetime,
) -> str:
    """Claim the next receipt number for a business, and return it rendered.

    Must be called inside the transaction that writes the sale: the claim and the sale
    commit or roll back together, so a rolled-back sale does not consume a number and a
    committed one cannot lose its claim.
    """
    resolved_prefix = clean_receipt_prefix(prefix)
    statement = (
        postgresql_insert(ReceiptCounterRecord)
        .values(
            tenant_id=tenant_id,
            # The first sale inserts the row with 1, not 0: `last_receipt_number` holds the
            # highest number issued, and an INSERT means none has been.
            last_receipt_number=1,
            receipt_prefix=resolved_prefix,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=[ReceiptCounterRecord.tenant_id],
            set_={
                "last_receipt_number": ReceiptCounterRecord.last_receipt_number + 1,
                "updated_at": now,
            },
        )
        .returning(ReceiptCounterRecord.last_receipt_number)
    )
    result = await session.execute(statement)
    number = result.scalar_one_or_none()
    if number is None:  # pragma: no cover - RETURNING always yields a row here
        raise PersistenceError(
            operation="allocate_receipt_number",
            entity="receipt_counter",
            identifier=str(tenant_id),
            detail="the counter did not return a number",
        )
    return render_receipt_number(prefix=resolved_prefix, number=int(number))


async def claim_next_number(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    prefix: str,
    now: datetime,
) -> ReceiptCounterModel:
    """Claim the next number and return the counter as it now stands.

    The entity is returned rather than a rendered string so the caller can log the number
    without re-deriving the prefix, and so the rendering rule stays in one place.
    """
    rendered = await allocate_receipt_number(session, tenant_id=tenant_id, prefix=prefix, now=now)
    number = int(rendered.rsplit("-", 1)[1])
    return ReceiptCounterModel(
        tenant_id=tenant_id,
        last_receipt_number=number,
        receipt_prefix=clean_receipt_prefix(prefix),
        updated_at=now,
    )


async def current_number(session: AsyncSession, tenant_id: UUID) -> int:
    """Return the highest number issued, or zero when none has been."""
    result = await session.execute(
        select(ReceiptCounterRecord.last_receipt_number).where(
            ReceiptCounterRecord.tenant_id == tenant_id
        )
    )
    value = result.scalar_one_or_none()
    return 0 if value is None else int(value)
