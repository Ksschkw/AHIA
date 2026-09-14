"""Persistence for pushed operations.

One table, one entity, one file, and no update path. An operation's outcome is a fact about a
request that has already been answered: changing it would let a retry be answered differently
from the first attempt, which is the failure this table exists to prevent. A test asserts the
absence of any function that could change a row.

The primary key is the client's identifier, paired with the business
    `(tenant_id, id)`: the identifier is the device's, and two businesses can generate the same
    one because their phones have never met. Making `id` alone the key - the first version of this
    table - made that impossible, and the failure was a unique violation rather than a wrong
    answer, which is the good kind: it was found by a test that pushed the same identifier from
    two businesses.

Reading is by the five questions support asks
    "Has this operation been applied", "what did this device send", "what has this business
    rejected", "what happened to this record" and "how much is still failing". The first is the
    primary key, and the rest are indexed here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.models.entities.sync_operation_model import (
    MAXIMUM_OPERATION_TYPE_LENGTH,
    SyncOperationModel,
    SyncOperationStatus,
)

_TABLE_NAME: Final[str] = "sync_operations"
_MAXIMUM_ENTITY_TYPE_LENGTH: Final[int] = 64
_STATUS_LENGTH: Final[int] = 16


class SyncOperationRecord(Base):
    """The persistence representation of one pushed operation."""

    __tablename__ = _TABLE_NAME

    # Not a primary key on its own: the identifier is the device's, and two businesses may
    # generate the same one.
    id: Mapped[UUID] = mapped_column(nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    operation_type: Mapped[str] = mapped_column(
        String(MAXIMUM_OPERATION_TYPE_LENGTH), nullable=False
    )
    status: Mapped[str] = mapped_column(String(_STATUS_LENGTH), nullable=False)
    # Copied, not referenced: the actor and the device are what the request was authenticated as,
    # and the answer to a retry must not change because a device row was renamed later.
    actor_id: Mapped[UUID | None] = mapped_column(nullable=True)
    device_id: Mapped[UUID | None] = mapped_column(nullable=True)
    entity_type: Mapped[str | None] = mapped_column(
        String(_MAXIMUM_ENTITY_TYPE_LENGTH), nullable=True
    )
    entity_id: Mapped[UUID | None] = mapped_column(nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # The client's identifier inside one business. This is the constraint a retry meets, and
        # it is what makes the answer cheap.
        PrimaryKeyConstraint("tenant_id", "id", name="pk_sync_operations"),
        Index("ix_sync_operations_tenant_occurred", "tenant_id", "occurred_at"),
        Index("ix_sync_operations_tenant_device", "tenant_id", "device_id", "occurred_at"),
        Index("ix_sync_operations_tenant_status", "tenant_id", "status", "occurred_at"),
        Index("ix_sync_operations_tenant_entity", "tenant_id", "entity_type", "entity_id"),
    )


def to_entity(record: SyncOperationRecord) -> SyncOperationModel:
    return SyncOperationModel(
        id=record.id,
        tenant_id=record.tenant_id,
        operation_type=record.operation_type,
        status=SyncOperationStatus(record.status),
        occurred_at=record.occurred_at,
        actor_id=record.actor_id,
        device_id=record.device_id,
        entity_type=record.entity_type,
        entity_id=record.entity_id,
        detail=(
            {str(key): str(value) for key, value in record.detail.items()}
            if record.detail
            else None
        ),
    )


def apply_entity(record: SyncOperationRecord, entity: SyncOperationModel) -> None:
    record.tenant_id = entity.tenant_id
    record.operation_type = entity.operation_type
    record.status = entity.status.value
    record.actor_id = entity.actor_id
    record.device_id = entity.device_id
    record.entity_type = entity.entity_type
    record.entity_id = entity.entity_id
    record.detail = dict(entity.detail) if entity.detail else None
    record.occurred_at = entity.occurred_at


async def record_or_get(
    session: AsyncSession,
    operation: SyncOperationModel,
) -> tuple[SyncOperationModel, bool]:
    """Store an operation's outcome, or return the one already stored.

    Returns the stored record and whether this call created it. Two devices cannot race for the
    same identifier - it is generated per device - but two retries of the same request can arrive
    at once, so the insert is attempted and an existing row is returned rather than raised: the
    second arrival must get the first one's answer, and that is not an error.
    """
    existing = await get_by_id(session, tenant_id=operation.tenant_id, operation_id=operation.id)
    if existing is not None:
        return existing, False

    record = SyncOperationRecord(id=operation.id)
    apply_entity(record, operation)
    session.add(record)
    await session.flush()
    return to_entity(record), True


async def get_by_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    operation_id: UUID,
) -> SyncOperationModel | None:
    """Return the record of an operation, scoped to the business that sent it."""
    result = await session.execute(
        select(SyncOperationRecord)
        .where(SyncOperationRecord.tenant_id == tenant_id)
        .where(SyncOperationRecord.id == operation_id)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def list_for_device(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    device_id: UUID,
    limit: int = 100,
) -> list[SyncOperationModel]:
    """Return what one device sent, most recent first."""
    result = await session.execute(
        select(SyncOperationRecord)
        .where(SyncOperationRecord.tenant_id == tenant_id)
        .where(SyncOperationRecord.device_id == device_id)
        .order_by(SyncOperationRecord.occurred_at.desc(), SyncOperationRecord.id.desc())
        .limit(limit)
    )
    return [to_entity(record) for record in result.scalars().all()]


async def list_for_tenant(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    status: SyncOperationStatus | None = None,
    limit: int = 100,
) -> list[SyncOperationModel]:
    """Return a business's operations, most recent first, optionally by outcome."""
    statement = select(SyncOperationRecord).where(SyncOperationRecord.tenant_id == tenant_id)
    if status is not None:
        statement = statement.where(SyncOperationRecord.status == status.value)
    result = await session.execute(
        statement.order_by(
            SyncOperationRecord.occurred_at.desc(), SyncOperationRecord.id.desc()
        ).limit(limit)
    )
    return [to_entity(record) for record in result.scalars().all()]


async def count_for_device(session: AsyncSession, *, tenant_id: UUID, device_id: UUID) -> int:
    """Return how many operations a device has pushed to this business."""
    result = await session.execute(
        select(func.count())
        .select_from(SyncOperationRecord)
        .where(SyncOperationRecord.tenant_id == tenant_id)
        .where(SyncOperationRecord.device_id == device_id)
    )
    return int(result.scalar_one())
