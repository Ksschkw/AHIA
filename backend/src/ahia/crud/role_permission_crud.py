"""Persistence for the role-permission links.

A join table with a composite primary key, so the pair is unique by construction
rather than by a check. Two functions carry most of the weight: replacing a role's
permission set in one operation, and answering which roles grant a permission.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.models.entities.role_permission_model import RolePermissionModel

_TABLE_NAME: Final[str] = "role_permissions"


class RolePermissionRecord(Base):
    """The persistence representation of one grant."""

    __tablename__ = _TABLE_NAME

    role_id: Mapped[UUID] = mapped_column(primary_key=True, index=True)
    permission_id: Mapped[UUID] = mapped_column(primary_key=True, index=True)


def to_entity(record: RolePermissionRecord) -> RolePermissionModel:
    return RolePermissionModel(role_id=record.role_id, permission_id=record.permission_id)


async def add_grants(
    session: AsyncSession,
    *,
    role_id: UUID,
    permission_ids: list[UUID],
) -> int:
    """Grant permissions to a role, ignoring pairs that already exist.

    Idempotent by construction: the seed runs on every deployment and must not
    fail because a grant is already present.
    """
    if not permission_ids:
        return 0
    statement = (
        postgresql_insert(RolePermissionRecord)
        .values(
            [
                {"role_id": role_id, "permission_id": permission_id}
                for permission_id in permission_ids
            ]
        )
        .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
    )
    result = await session.execute(statement)
    await session.flush()
    return int(getattr(result, "rowcount", 0) or 0)


async def remove_grants(
    session: AsyncSession,
    *,
    role_id: UUID,
    permission_ids: list[UUID],
) -> int:
    """Revoke permissions from a role."""
    if not permission_ids:
        return 0
    result = await session.execute(
        delete(RolePermissionRecord)
        .where(RolePermissionRecord.role_id == role_id)
        .where(RolePermissionRecord.permission_id.in_(permission_ids))
    )
    await session.flush()
    return int(getattr(result, "rowcount", 0) or 0)


async def list_permission_ids_for_role(session: AsyncSession, role_id: UUID) -> list[UUID]:
    result = await session.execute(
        select(RolePermissionRecord.permission_id).where(RolePermissionRecord.role_id == role_id)
    )
    return list(result.scalars().all())


async def list_role_ids_for_permission(session: AsyncSession, permission_id: UUID) -> list[UUID]:
    """Return which roles grant a permission.

    The question an operator asks before revoking a capability: what breaks?
    """
    result = await session.execute(
        select(RolePermissionRecord.role_id).where(
            RolePermissionRecord.permission_id == permission_id
        )
    )
    return list(result.scalars().all())


async def count_grants(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(RolePermissionRecord))
    return int(result.scalar_one())
