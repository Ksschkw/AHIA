"""Persistence for roles.

One table, two kinds of row, distinguished by whether a tenant owns them. The
uniqueness rules are the interesting part and they are enforced by two partial
indexes rather than by application logic:

    a system role's name is unique across the installation
    a custom role's name is unique within its tenant

PostgreSQL treats nulls as distinct, so a single unique index over (tenant_id,
name) would allow two system roles called OWNER. Two partial indexes say what is
actually meant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Index, String, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import ConflictError, NotFoundError
from ahia.models.entities.role_model import RoleModel

_TABLE_NAME: Final[str] = "roles"
_NAME_LENGTH: Final[int] = 32
_DESCRIPTION_LENGTH: Final[int] = 255


class RoleRecord(Base):
    """The persistence representation of one role."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    # Null for a system role, set for a tenant's own role.
    tenant_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(_NAME_LENGTH), nullable=False)
    description: Mapped[str] = mapped_column(String(_DESCRIPTION_LENGTH), nullable=False)
    is_system_role: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "uq_roles_system_name",
            "name",
            unique=True,
            postgresql_where=text("tenant_id IS NULL"),
        ),
        Index(
            "uq_roles_tenant_name",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("tenant_id IS NOT NULL"),
        ),
    )


def to_entity(record: RoleRecord) -> RoleModel:
    return RoleModel(
        id=record.id,
        name=record.name,
        description=record.description,
        is_system_role=record.is_system_role,
        tenant_id=record.tenant_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def apply_entity(record: RoleRecord, entity: RoleModel) -> None:
    record.tenant_id = entity.tenant_id
    record.name = entity.name
    record.description = entity.description
    record.is_system_role = entity.is_system_role
    record.created_at = entity.created_at
    record.updated_at = entity.updated_at


async def create(session: AsyncSession, role: RoleModel) -> RoleModel:
    record = RoleRecord(id=role.id)
    apply_entity(record, role)
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise ConflictError(
            operation="create_role",
            entity="role",
            identifier=str(role.id),
            detail=f"a role with this name already exists here: {_constraint_name(conflict)}",
            cause=conflict,
        ) from conflict
    return to_entity(record)


async def get_by_id(session: AsyncSession, role_id: UUID) -> RoleModel | None:
    record = await session.get(RoleRecord, role_id)
    return None if record is None else to_entity(record)


async def get_system_role_by_name(session: AsyncSession, name: str) -> RoleModel | None:
    """Return a system role by name.

    The lookup authorization depends on, so it is a single indexed query rather
    than a scan filtered in Python.
    """
    result = await session.execute(
        select(RoleRecord).where(RoleRecord.is_system_role.is_(True)).where(RoleRecord.name == name)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def get_custom_role_for_tenant(
    session: AsyncSession, *, tenant_id: UUID, name: str
) -> RoleModel | None:
    result = await session.execute(
        select(RoleRecord).where(RoleRecord.tenant_id == tenant_id).where(RoleRecord.name == name)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def get_role_for_tenant(
    session: AsyncSession, *, tenant_id: UUID, name: str
) -> RoleModel | None:
    """Return the role a tenant's membership would resolve to.

    A tenant's own role is preferred, so a business that defines SUPERVISOR gets
    its own definition. A custom role may not take a system role's name - the
    service refuses it, because an audit record must not be ambiguous about which
    OWNER applied - so the two sets can never actually collide.
    """
    custom = await get_custom_role_for_tenant(session, tenant_id=tenant_id, name=name)
    if custom is not None:
        return custom
    return await get_system_role_by_name(session, name)


async def list_system_roles(session: AsyncSession) -> list[RoleModel]:
    result = await session.execute(
        select(RoleRecord).where(RoleRecord.is_system_role.is_(True)).order_by(RoleRecord.name)
    )
    return [to_entity(record) for record in result.scalars().all()]


async def list_for_tenant(session: AsyncSession, tenant_id: UUID) -> list[RoleModel]:
    """Return the roles available to one business: the system ones and its own."""
    result = await session.execute(
        select(RoleRecord)
        .where(or_(RoleRecord.is_system_role.is_(True), RoleRecord.tenant_id == tenant_id))
        .order_by(RoleRecord.is_system_role.desc(), RoleRecord.name)
    )
    return [to_entity(record) for record in result.scalars().all()]


async def update(session: AsyncSession, role: RoleModel) -> RoleModel:
    record = await session.get(RoleRecord, role.id)
    if record is None:
        raise NotFoundError(
            operation="update_role",
            entity="role",
            identifier=str(role.id),
            detail="no row matched the identifier",
        )
    record.description = role.description
    record.updated_at = role.updated_at
    await session.flush()
    return to_entity(record)


async def count_roles(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(RoleRecord))
    return int(result.scalar_one())


def _constraint_name(conflict: IntegrityError) -> str:
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
