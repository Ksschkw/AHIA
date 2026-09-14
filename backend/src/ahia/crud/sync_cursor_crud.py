"""Persistence for synchronisation cursors.

One table, one entity, one file, and one row per device.

One row per device, enforced by the database
    `UNIQUE(tenant_id, device_id)`. Two rows for one device would mean two positions in the feed,
    and a device that wrote the wrong one would either re-apply changes or skip them. The unique
    constraint makes the second row impossible rather than unlikely - which matters because the
    two writers would be two concurrent requests from the same phone.

Reading a business's cursors is a support question
    "Which phones are behind" is `(tenant_id, last_server_sequence)`: an operator diagnosing a
    device that has not caught up needs the ones with the lowest sequences, not all of them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.models.entities.sync_cursor_model import SyncCursorModel

_TABLE_NAME: Final[str] = "sync_cursors"


class SyncCursorRecord(Base):
    """The persistence representation of one device's position in the feed."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id"), nullable=False)
    last_server_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "device_id", name="uq_sync_cursors_tenant_id_device_id"),
        Index("ix_sync_cursors_tenant_sequence", "tenant_id", "last_server_sequence"),
    )


def to_entity(record: SyncCursorRecord) -> SyncCursorModel:
    return SyncCursorModel(
        id=record.id,
        tenant_id=record.tenant_id,
        device_id=record.device_id,
        last_server_sequence=record.last_server_sequence,
        updated_at=record.updated_at,
    )


def apply_entity(record: SyncCursorRecord, entity: SyncCursorModel) -> None:
    record.tenant_id = entity.tenant_id
    record.device_id = entity.device_id
    record.last_server_sequence = entity.last_server_sequence
    record.updated_at = entity.updated_at


async def get_for_device(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    device_id: UUID,
) -> SyncCursorModel | None:
    """Return the device's cursor, or None when it has never synchronized."""
    result = await session.execute(
        select(SyncCursorRecord)
        .where(SyncCursorRecord.tenant_id == tenant_id)
        .where(SyncCursorRecord.device_id == device_id)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def save(session: AsyncSession, cursor: SyncCursorModel) -> SyncCursorModel:
    """Insert or move a device's cursor, scoped to its business.

    An upsert rather than a create-then-update, because the first read of a new device and the
    advance of an existing one arrive at the same function and the caller should not have to know
    which it is holding. The sequence is only ever moved forward by the entity.
    """
    existing = await get_for_device(session, tenant_id=cursor.tenant_id, device_id=cursor.device_id)
    if existing is None:
        record = SyncCursorRecord(id=cursor.id)
        apply_entity(record, cursor)
        session.add(record)
        await session.flush()
        return to_entity(record)

    result = await session.execute(
        select(SyncCursorRecord)
        .where(SyncCursorRecord.tenant_id == cursor.tenant_id)
        .where(SyncCursorRecord.device_id == cursor.device_id)
    )
    stored = result.scalar_one()
    stored.last_server_sequence = cursor.last_server_sequence
    stored.updated_at = cursor.updated_at
    await session.flush()
    return to_entity(stored)


async def list_for_tenant(
    session: AsyncSession,
    tenant_id: UUID,
) -> list[SyncCursorModel]:
    """Return every device's cursor, the ones furthest behind first."""
    result = await session.execute(
        select(SyncCursorRecord)
        .where(SyncCursorRecord.tenant_id == tenant_id)
        .order_by(SyncCursorRecord.last_server_sequence, SyncCursorRecord.updated_at)
    )
    return [to_entity(record) for record in result.scalars().all()]
