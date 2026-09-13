"""Persistence for devices.

One table, one entity. The uniqueness rule is per tenant: a client installation is
identified by a string it generates, and the same string in two businesses is two
devices, because two businesses are two worlds.

The lookup that security depends on is by identifier within a tenant, because that
is how a returning client is recognised as itself rather than as a new device.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import NotFoundError
from ahia.crud.integrity_violations import translate_integrity_violation
from ahia.models.entities.device_model import DeviceModel

_TABLE_NAME: Final[str] = "devices"
_IDENTIFIER_LENGTH: Final[int] = 128
_NAME_LENGTH: Final[int] = 100
_PLATFORM_LENGTH: Final[int] = 32
_APP_VERSION_LENGTH: Final[int] = 32


class DeviceRecord(Base):
    """The persistence representation of one client installation."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    device_identifier: Mapped[str] = mapped_column(String(_IDENTIFIER_LENGTH), nullable=False)
    device_name: Mapped[str | None] = mapped_column(String(_NAME_LENGTH), nullable=True)
    platform: Mapped[str] = mapped_column(String(_PLATFORM_LENGTH), nullable=False)
    app_version: Mapped[str | None] = mapped_column(String(_APP_VERSION_LENGTH), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # One installation per business. The identifier is opaque to the server, so
        # uniqueness is scoped to the tenant that received it.
        Index("uq_devices_tenant_identifier", "tenant_id", "device_identifier", unique=True),
    )


def to_entity(record: DeviceRecord) -> DeviceModel:
    return DeviceModel(
        id=record.id,
        tenant_id=record.tenant_id,
        user_id=record.user_id,
        device_identifier=record.device_identifier,
        device_name=record.device_name,
        platform=record.platform,
        app_version=record.app_version,
        last_seen_at=record.last_seen_at,
        revoked_at=record.revoked_at,
        created_at=record.created_at,
    )


def apply_entity(record: DeviceRecord, entity: DeviceModel) -> None:
    record.tenant_id = entity.tenant_id
    record.user_id = entity.user_id
    record.device_identifier = entity.device_identifier
    record.device_name = entity.device_name
    record.platform = entity.platform
    record.app_version = entity.app_version
    record.last_seen_at = entity.last_seen_at
    record.revoked_at = entity.revoked_at
    record.created_at = entity.created_at


async def create(session: AsyncSession, device: DeviceModel) -> DeviceModel:
    record = DeviceRecord(id=device.id)
    apply_entity(record, device)
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise translate_integrity_violation(
            conflict,
            operation="create_device",
            entity="device",
            identifier=str(device.id),
            conflict_detail="this installation is already registered",
            missing_detail="the business or person this device belongs to does not exist",
        ) from conflict
    return to_entity(record)


async def get_by_id(session: AsyncSession, device_id: UUID) -> DeviceModel | None:
    record = await session.get(DeviceRecord, device_id)
    return None if record is None else to_entity(record)


async def get_by_identifier(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    device_identifier: str,
) -> DeviceModel | None:
    """Return an installation by the identifier it presents.

    Revoked devices are returned: the caller decides what a revoked device means,
    and hiding it here would make "your phone was revoked" indistinguishable from
    "we have never seen this phone".
    """
    result = await session.execute(
        select(DeviceRecord)
        .where(DeviceRecord.tenant_id == tenant_id)
        .where(DeviceRecord.device_identifier == device_identifier)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def list_for_tenant(session: AsyncSession, tenant_id: UUID) -> list[DeviceModel]:
    result = await session.execute(
        select(DeviceRecord)
        .where(DeviceRecord.tenant_id == tenant_id)
        .order_by(DeviceRecord.last_seen_at.desc())
    )
    return [to_entity(record) for record in result.scalars().all()]


async def list_for_user(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID
) -> list[DeviceModel]:
    result = await session.execute(
        select(DeviceRecord)
        .where(DeviceRecord.tenant_id == tenant_id)
        .where(DeviceRecord.user_id == user_id)
        .order_by(DeviceRecord.last_seen_at.desc())
    )
    return [to_entity(record) for record in result.scalars().all()]


async def update(session: AsyncSession, device: DeviceModel) -> DeviceModel:
    record = await session.get(DeviceRecord, device.id)
    if record is None:
        raise NotFoundError(
            operation="update_device",
            entity="device",
            identifier=str(device.id),
            detail="no row matched the identifier",
        )
    apply_entity(record, device)
    await session.flush()
    return to_entity(record)
