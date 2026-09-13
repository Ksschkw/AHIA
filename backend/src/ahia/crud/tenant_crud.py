"""Persistence for the tenant entity.

One table, one entity, one file. The only unusual property here is that the slug
is globally unique rather than tenant-scoped: a slug is a public address, and two
businesses cannot share one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import Boolean, DateTime, String, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import NotFoundError
from ahia.crud.integrity_violations import translate_integrity_violation
from ahia.models.entities.tenant_model import TenantModel

_TABLE_NAME: Final[str] = "tenants"
_NAME_LENGTH: Final[int] = 120
_SLUG_LENGTH: Final[int] = 63
_SHORT_TEXT_LENGTH: Final[int] = 120
_LOCATION_LENGTH: Final[int] = 80
_EMAIL_LENGTH: Final[int] = 254
_PHONE_LENGTH: Final[int] = 20


class TenantRecord(Base):
    """The persistence representation of one business."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(_NAME_LENGTH), nullable=False)
    # Globally unique: a slug is a public address, so it is the one string in this
    # schema that two tenants may never share.
    slug: Mapped[str] = mapped_column(String(_SLUG_LENGTH), nullable=False, unique=True, index=True)
    business_type: Mapped[str | None] = mapped_column(String(_SHORT_TEXT_LENGTH), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(_PHONE_LENGTH), nullable=True)
    email: Mapped[str | None] = mapped_column(String(_EMAIL_LENGTH), nullable=True)
    address: Mapped[str | None] = mapped_column(String(_SHORT_TEXT_LENGTH), nullable=True)
    city: Mapped[str | None] = mapped_column(String(_LOCATION_LENGTH), nullable=True)
    state: Mapped[str | None] = mapped_column(String(_LOCATION_LENGTH), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="NG")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    timezone: Mapped[str] = mapped_column(String(_SHORT_TEXT_LENGTH), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # No composite-key anchor here: a tenant is not owned by a tenant, so there is no
    # (id, tenant_id) pair to make unique. The specification's composite foreign keys
    # - sale_items (product_id, tenant_id) referencing products (id, tenant_id) -
    # anchor on the tenant-owned table that is actually referenced, and the constraint
    # is added there when that table exists (M9).


def to_entity(record: TenantRecord) -> TenantModel:
    return TenantModel(
        id=record.id,
        name=record.name,
        slug=record.slug,
        business_type=record.business_type,
        phone=record.phone,
        email=record.email,
        address=record.address,
        city=record.city,
        state=record.state,
        country=record.country,
        currency=record.currency,
        timezone=record.timezone,
        is_active=record.is_active,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def apply_entity(record: TenantRecord, entity: TenantModel) -> None:
    record.name = entity.name
    record.slug = entity.slug
    record.business_type = entity.business_type
    record.phone = entity.phone
    record.email = entity.email
    record.address = entity.address
    record.city = entity.city
    record.state = entity.state
    record.country = entity.country
    record.currency = entity.currency
    record.timezone = entity.timezone
    record.is_active = entity.is_active
    record.created_at = entity.created_at
    record.updated_at = entity.updated_at


async def create(session: AsyncSession, tenant: TenantModel) -> TenantModel:
    """Insert a business, translating a slug collision into a typed conflict."""
    record = TenantRecord(id=tenant.id)
    apply_entity(record, tenant)
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise translate_integrity_violation(
            conflict,
            operation="create_tenant",
            entity="tenant",
            identifier=str(tenant.id),
            conflict_detail="the slug is already taken",
        ) from conflict
    return to_entity(record)


async def get_by_id(session: AsyncSession, tenant_id: UUID) -> TenantModel | None:
    """Return a business by identifier, active or not.

    Whether an inactive business may be read is an authorization decision, so this
    lookup does not make it.
    """
    record = await session.get(TenantRecord, tenant_id)
    return None if record is None else to_entity(record)


async def require_by_id(session: AsyncSession, tenant_id: UUID) -> TenantModel:
    tenant = await get_by_id(session, tenant_id)
    if tenant is None:
        raise NotFoundError(
            operation="fetch_tenant",
            entity="tenant",
            identifier=str(tenant_id),
            detail="no row matched the identifier",
        )
    return tenant


async def get_by_slug(session: AsyncSession, slug: str) -> TenantModel | None:
    """Return a business by its public slug."""
    result = await session.execute(select(TenantRecord).where(TenantRecord.slug == slug))
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def slug_is_taken(session: AsyncSession, slug: str) -> bool:
    """Return True when a slug is already in use.

    Used to generate a readable suggestion rather than a random one when the
    chosen name is taken.
    """
    result = await session.execute(
        select(TenantRecord.id).where(TenantRecord.slug == slug).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def update(session: AsyncSession, tenant: TenantModel) -> TenantModel:
    """Persist changes to an existing business."""
    record = await session.get(TenantRecord, tenant.id)
    if record is None:
        raise NotFoundError(
            operation="update_tenant",
            entity="tenant",
            identifier=str(tenant.id),
            detail="no row matched the identifier",
        )
    apply_entity(record, tenant)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise translate_integrity_violation(
            conflict,
            operation="update_tenant",
            entity="tenant",
            identifier=str(tenant.id),
            conflict_detail="the update collides with an existing business",
        ) from conflict
    return to_entity(record)


async def count_tenants(session: AsyncSession) -> int:
    """Return the number of businesses. Used by tests and operational tooling."""
    result = await session.execute(select(func.count()).select_from(TenantRecord))
    return int(result.scalar_one())
