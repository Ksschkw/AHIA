"""Persistence for the change feed.

One table, one entity, one file.

The sequence is the database's
    `change_sequence` is an identity column, so the server assigns it and an insert that tries to
    choose one fails. That is what makes the order total across devices: two writers cannot
    disagree about which change came first, because neither of them chose.

The feed is read one way, and that way is indexed
    Every read is "changes for this business after this sequence, in order", which is
    `(tenant_id, change_sequence)`. Declared here rather than discovered from a slow sync later.

There is no update and no delete
    A change is a fact about what the server did, and the feed is what lets a device catch up. A
    row that could be removed would make a client that has already advanced past it permanently
    wrong about a record it never saw. A test asserts the absence mechanically.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.models.entities.sync_change_model import (
    MAXIMUM_ENTITY_TYPE_LENGTH,
    ChangeType,
    SyncChangeModel,
)

_TABLE_NAME: Final[str] = "sync_changes"
_CHANGE_TYPE_LENGTH: Final[int] = 16


class SyncChangeRecord(Base):
    """The persistence representation of one change."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    # The server's order. `Identity(always=True)` refuses a caller-supplied value, which is the
    # point: a device must not be able to place its own change in another device's feed.
    change_sequence: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), nullable=False, unique=True
    )
    entity_type: Mapped[str] = mapped_column(String(MAXIMUM_ENTITY_TYPE_LENGTH), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(nullable=False)
    change_type: Mapped[str] = mapped_column(String(_CHANGE_TYPE_LENGTH), nullable=False)
    operation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_sync_changes_tenant_sequence", "tenant_id", "change_sequence"),)


def to_entity(record: SyncChangeRecord) -> SyncChangeModel:
    return SyncChangeModel(
        id=record.id,
        tenant_id=record.tenant_id,
        change_sequence=record.change_sequence,
        entity_type=record.entity_type,
        entity_id=record.entity_id,
        change_type=ChangeType(record.change_type),
        occurred_at=record.occurred_at,
        operation_id=record.operation_id,
    )


def apply_entity(record: SyncChangeRecord, entity: SyncChangeModel) -> None:
    record.tenant_id = entity.tenant_id
    record.entity_type = entity.entity_type
    record.entity_id = entity.entity_id
    record.change_type = entity.change_type.value
    record.operation_id = entity.operation_id
    record.occurred_at = entity.occurred_at


async def record(session: AsyncSession, change: SyncChangeModel) -> SyncChangeModel:
    """Append one change and return it with the sequence the database assigned.

    Does not commit: the caller owns the transaction, because a change that describes a write
    must land with that write. A feed entry for a rolled-back change would tell every device to
    fetch a record that does not exist.
    """
    row = SyncChangeRecord(id=change.id)
    apply_entity(row, change)
    session.add(row)
    # The sequence is a server default, so it is only knowable after the insert. Reading it back
    # here is what lets the entity validate it and the caller log it.
    await session.flush()
    await session.refresh(row, attribute_names=["change_sequence"])
    return to_entity(row)


async def changes_after(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    after_sequence: int,
    limit: int = 500,
) -> list[SyncChangeModel]:
    """Return the business's changes after a sequence, oldest first.

    Oldest first, because a client applies them in order and advances its cursor one change at a
    time. A page returned newest first would make a cursor meaningless: the client would have to
    know which of the page it had already seen.
    """
    result = await session.execute(
        select(SyncChangeRecord)
        .where(SyncChangeRecord.tenant_id == tenant_id)
        .where(SyncChangeRecord.change_sequence > after_sequence)
        .order_by(SyncChangeRecord.change_sequence)
        .limit(limit)
    )
    return [to_entity(row) for row in result.scalars().all()]


async def latest_sequence(session: AsyncSession, tenant_id: UUID) -> int:
    """Return the highest sequence this business's feed has reached, or zero.

    Zero for a business that has never changed anything, which is the same value a device that
    has never synchronized holds - so a new business and a new device agree without a special
    case.
    """
    result = await session.execute(
        select(SyncChangeRecord.change_sequence)
        .where(SyncChangeRecord.tenant_id == tenant_id)
        .order_by(SyncChangeRecord.change_sequence.desc())
        .limit(1)
    )
    highest = result.scalar_one_or_none()
    return int(highest) if highest is not None else 0


async def count_for_tenant(session: AsyncSession, tenant_id: UUID) -> int:
    """Return how many changes a business's feed holds."""
    result = await session.execute(
        select(func.count())
        .select_from(SyncChangeRecord)
        .where(SyncChangeRecord.tenant_id == tenant_id)
    )
    return int(result.scalar_one())
