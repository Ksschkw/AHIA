"""Persistence for tenant memberships.

One table, one entity. The lookups fall into two shapes: everything about one
business, and everything one person may reach. Both are needed, and neither is a
join across entities - a list of a person's businesses is assembled by the
service from memberships and then tenants, because a join here would make this
file own two entities' storage.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import DateTime, String, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import ConflictError, NotFoundError
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

    id: Mapped[UUID] = mapped_column(primary_key=True)
    # Indexed individually as well as together: a tenant-scoped query filters on
    # tenant_id, and a person's own list filters on user_id.
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    role_name: Mapped[str] = mapped_column(String(_ROLE_NAME_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(String(_STATUS_LENGTH), nullable=False)
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invited_by_user_id: Mapped[UUID | None] = mapped_column(nullable=True)
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
        raise ConflictError(
            operation="create_membership",
            entity="tenant_membership",
            identifier=str(membership.id),
            detail=(
                "this person already has a membership in this business: "
                f"{_constraint_name(conflict)}"
            ),
            cause=conflict,
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


def _constraint_name(conflict: IntegrityError) -> str:
    """Extract the violated index name for the internal detail. Never published."""
    original: Any = getattr(conflict, "orig", None)
    for candidate in (original, getattr(original, "__cause__", None)):
        if candidate is None:
            continue
        direct = getattr(candidate, "constraint_name", None)
        if direct:
            return str(direct)
        diagnostic = getattr(candidate, "diag", None)
        named = getattr(diagnostic, "constraint_name", None)
        if named:
            return str(named)
    return type(original).__name__ if original is not None else "unknown-constraint"
