"""Persistence for tenant storage accounting.

One table, one entity, one file. The only subtlety is the lock: quota accounting
is read-modify-write, so every mutation takes the tenant's row with
``SELECT ... FOR UPDATE`` before reading it. Without that lock, two concurrent
uploads read the same starting value, both decide they fit, and both write,
over-allocating the tenant by exactly the amount the check was supposed to stop.

The lock is held only for the accounting transaction, never across the provider
call, because holding a row lock while waiting on a network call couples the
database's concurrency to a third party's latency.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import PersistenceError
from ahia.models.entities.tenant_storage_usage_model import TenantStorageUsage

_TABLE_NAME: Final[str] = "tenant_storage_usage"


class TenantStorageUsageRecord(Base):
    """The persistence representation of one tenant's storage accounting.

    A representation, not the domain entity: the entity is the source of truth
    and this class is how PostgreSQL happens to store it.
    """

    __tablename__ = _TABLE_NAME

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def to_entity(record: TenantStorageUsageRecord) -> TenantStorageUsage:
    """Map a row to the domain entity."""
    return TenantStorageUsage(
        tenant_id=record.tenant_id,
        used_bytes=record.used_bytes,
        reserved_bytes=record.reserved_bytes,
        version=record.version,
        updated_at=record.updated_at,
    )


def apply_entity(record: TenantStorageUsageRecord, entity: TenantStorageUsage) -> None:
    """Copy entity state onto a row."""
    record.used_bytes = entity.used_bytes
    record.reserved_bytes = entity.reserved_bytes
    record.version = entity.version
    record.updated_at = entity.updated_at


async def get_for_tenant(session: AsyncSession, tenant_id: UUID) -> TenantStorageUsage | None:
    """Return the tenant's usage, or None when the tenant has never uploaded."""
    result = await session.execute(
        select(TenantStorageUsageRecord).where(TenantStorageUsageRecord.tenant_id == tenant_id)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def lock_for_tenant(session: AsyncSession, tenant_id: UUID) -> TenantStorageUsage:
    """Return the tenant's usage with the row locked for update.

    Creates the row on first use. The insert is `ON CONFLICT DO NOTHING`
    followed by a locking select, so two concurrent first-time uploads cannot
    both insert and one of them cannot fail on a unique violation.
    """
    await _ensure_row_exists(session, tenant_id)

    result = await session.execute(
        select(TenantStorageUsageRecord)
        .where(TenantStorageUsageRecord.tenant_id == tenant_id)
        # The whole point of this module. Everything that mutates accounting goes
        # through here, so the read-modify-write sequence is serialized per
        # tenant.
        .with_for_update()
    )
    record = result.scalar_one_or_none()
    if record is None:  # pragma: no cover - the insert above guarantees a row
        raise PersistenceError(
            operation="lock_tenant_storage_usage",
            entity="tenant_storage_usage",
            identifier=str(tenant_id),
            detail="row missing immediately after ensure-row-exists",
        )
    return to_entity(record)


async def save(session: AsyncSession, entity: TenantStorageUsage) -> TenantStorageUsage:
    """Persist an entity that was read through `lock_for_tenant`.

    No lock is taken here; the caller already holds it, and taking it twice in
    one transaction would be pointless.
    """
    result = await session.execute(
        select(TenantStorageUsageRecord).where(
            TenantStorageUsageRecord.tenant_id == entity.tenant_id
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise PersistenceError(
            operation="save_tenant_storage_usage",
            entity="tenant_storage_usage",
            identifier=str(entity.tenant_id),
            detail="no row to update; accounting must be created through lock_for_tenant",
        )
    apply_entity(record, entity)
    await session.flush()
    return to_entity(record)


async def list_total_used_bytes(session: AsyncSession, tenant_id: UUID) -> int:
    """Return the stored byte total, or zero when there is no row.

    The reconciliation path uses this to compare the accounting against the sum
    of the metadata rows that actually exist.
    """
    usage = await get_for_tenant(session, tenant_id)
    return 0 if usage is None else usage.used_bytes


async def _ensure_row_exists(session: AsyncSession, tenant_id: UUID) -> None:
    statement = (
        postgresql_insert(TenantStorageUsageRecord)
        .values(
            tenant_id=tenant_id,
            used_bytes=0,
            reserved_bytes=0,
            version=0,
            updated_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=[TenantStorageUsageRecord.tenant_id])
    )
    await session.execute(statement)
