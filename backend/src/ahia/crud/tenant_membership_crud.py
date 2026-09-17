"""Persistence for tenant memberships.

One table, one entity. The lookups fall into two shapes: everything about one
business, and everything one person may reach. Both are needed, and neither is a
join across entities - a list of a person's businesses is assembled by the
service from memberships and then tenants, because a join here would make this
file own two entities' storage.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import NotFoundError
from ahia.crud.integrity_violations import translate_integrity_violation
from ahia.models.entities.tenant_membership_model import (
    MembershipStatus,
    TenantMembershipModel,
)

_TABLE_NAME: Final[str] = "tenant_memberships"
_ROLE_NAME_LENGTH: Final[int] = 32
_STATUS_LENGTH: Final[int] = 16


class TenantMembershipRecord(Base):
    """The persistence representation of one person's access to one business."""

    __tablename__ = _TABLE_NAME

    #: One person, one *current* membership per business.
    #:
    #: This is a database constraint and not only a service check, because two requests can pass the
    #: service's "are they already a member" test at the same time - which is exactly what a
    #: double-tapped invitation link does - and then both insert. The partial clause is what lets
    #: removed memberships stay as the audit trail while forbidding a second live one.
    __table_args__ = (
        Index(
            "uq_tenant_memberships_current_member",
            "tenant_id",
            "user_id",
            unique=True,
            postgresql_where=text("status <> 'removed'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    # Indexed individually as well as together: a tenant-scoped query filters on
    # tenant_id, and a person's own list filters on user_id.
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role_name: Mapped[str] = mapped_column(String(_ROLE_NAME_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(String(_STATUS_LENGTH), nullable=False)
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invited_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def to_entity(record: TenantMembershipRecord) -> TenantMembershipModel:
    return TenantMembershipModel(
        id=record.id,
        tenant_id=record.tenant_id,
        user_id=record.user_id,
        role_name=record.role_name,
        status=MembershipStatus(record.status),
        invited_at=record.invited_at,
        joined_at=record.joined_at,
        removed_at=record.removed_at,
        invited_by_user_id=record.invited_by_user_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def apply_entity(record: TenantMembershipRecord, entity: TenantMembershipModel) -> None:
    record.tenant_id = entity.tenant_id
    record.user_id = entity.user_id
    record.role_name = entity.role_name
    record.status = entity.status.value
    record.invited_at = entity.invited_at
    record.joined_at = entity.joined_at
    record.removed_at = entity.removed_at
    record.invited_by_user_id = entity.invited_by_user_id
    record.created_at = entity.created_at
    record.updated_at = entity.updated_at


async def create(session: AsyncSession, membership: TenantMembershipModel) -> TenantMembershipModel:
    """Insert a membership.

    A duplicate is a typed conflict: one person may hold exactly one membership per
    business, because two would mean two answers to "what may this person do".
    """
    record = TenantMembershipRecord(id=membership.id)
    apply_entity(record, membership)
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise translate_integrity_violation(
            conflict,
            operation="create_membership",
            entity="tenant_membership",
            identifier=str(membership.id),
            conflict_detail="this person already has a membership in this business",
            missing_detail="the business, person or inviter this membership names does not exist",
        ) from conflict
    return to_entity(record)


async def get_by_id(session: AsyncSession, membership_id: UUID) -> TenantMembershipModel | None:
    record = await session.get(TenantMembershipRecord, membership_id)
    return None if record is None else to_entity(record)


async def get_for_user_in_tenant(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
) -> TenantMembershipModel | None:
    """Return one person's membership in one business, whatever its status.

    Removed memberships are returned too: the caller decides whether to treat the
    membership as absent, and hiding it here would make "you were removed" look
    like "you were never here".
    """
    result = await session.execute(
        select(TenantMembershipRecord)
        .where(TenantMembershipRecord.tenant_id == tenant_id)
        .where(TenantMembershipRecord.user_id == user_id)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def list_for_tenant(session: AsyncSession, tenant_id: UUID) -> list[TenantMembershipModel]:
    """Return every membership in a business, oldest first."""
    result = await session.execute(
        select(TenantMembershipRecord)
        .where(TenantMembershipRecord.tenant_id == tenant_id)
        .order_by(TenantMembershipRecord.created_at.asc())
    )
    return [to_entity(record) for record in result.scalars().all()]


async def list_for_user(session: AsyncSession, user_id: UUID) -> list[TenantMembershipModel]:
    """Return every membership a person holds, newest first."""
    result = await session.execute(
        select(TenantMembershipRecord)
        .where(TenantMembershipRecord.user_id == user_id)
        .order_by(TenantMembershipRecord.created_at.desc())
    )
    return [to_entity(record) for record in result.scalars().all()]


async def update(session: AsyncSession, membership: TenantMembershipModel) -> TenantMembershipModel:
    """Persist changes to an existing membership."""
    record = await session.get(TenantMembershipRecord, membership.id)
    if record is None:
        raise NotFoundError(
            operation="update_membership",
            entity="tenant_membership",
            identifier=str(membership.id),
            detail="no row matched the identifier",
        )
    apply_entity(record, membership)
    await session.flush()
    return to_entity(record)


async def count_active_owners(session: AsyncSession, tenant_id: UUID) -> int:
    """Return how many active owners a business has.

    The last-owner rule reads this before a removal or a demotion, because a
    business with no owner is a business nobody can administer.
    """
    result = await session.execute(
        select(func.count())
        .select_from(TenantMembershipRecord)
        .where(TenantMembershipRecord.tenant_id == tenant_id)
        .where(TenantMembershipRecord.role_name == "OWNER")
        .where(TenantMembershipRecord.status == MembershipStatus.ACTIVE.value)
    )
    return int(result.scalar_one())


async def count_memberships(session: AsyncSession) -> int:
    """Return the number of membership rows. Used by tests and operational tooling."""
    result = await session.execute(select(func.count()).select_from(TenantMembershipRecord))
    return int(result.scalar_one())
