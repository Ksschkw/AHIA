"""Persistence for permissions.

Reference data, declared in code and provisioned into the database. The seed reads
the registry and writes here, so the only writes this file sees are provisioning
and nothing at runtime.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy import String, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import NotFoundError
from ahia.crud.integrity_violations import translate_integrity_violation
from ahia.models.entities.permission_model import PermissionModel

_TABLE_NAME: Final[str] = "permissions"
_CODE_LENGTH: Final[int] = 128
_MODULE_LENGTH: Final[int] = 64
_DESCRIPTION_LENGTH: Final[int] = 255


class PermissionRecord(Base):
    """The persistence representation of one application capability."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(_CODE_LENGTH), nullable=False, unique=True, index=True)
    module: Mapped[str] = mapped_column(String(_MODULE_LENGTH), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(_DESCRIPTION_LENGTH), nullable=False)


def to_entity(record: PermissionRecord) -> PermissionModel:
    return PermissionModel(
        id=record.id,
        code=record.code,
        module=record.module,
        description=record.description,
    )


def apply_entity(record: PermissionRecord, entity: PermissionModel) -> None:
    record.code = entity.code
    record.module = entity.module
    record.description = entity.description


async def create(session: AsyncSession, permission: PermissionModel) -> PermissionModel:
    record = PermissionRecord(id=permission.id)
    apply_entity(record, permission)
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise translate_integrity_violation(
            conflict,
            operation="create_permission",
            entity="permission",
            identifier=str(permission.id),
            conflict_detail="the permission code already exists",
        ) from conflict
    return to_entity(record)


async def get_by_code(session: AsyncSession, code: str) -> PermissionModel | None:
    result = await session.execute(select(PermissionRecord).where(PermissionRecord.code == code))
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def get_by_id(session: AsyncSession, permission_id: UUID) -> PermissionModel | None:
    record = await session.get(PermissionRecord, permission_id)
    return None if record is None else to_entity(record)


async def list_all(session: AsyncSession) -> list[PermissionModel]:
    """Return every permission, ordered by code so the catalogue reads predictably."""
    result = await session.execute(select(PermissionRecord).order_by(PermissionRecord.code))
    return [to_entity(record) for record in result.scalars().all()]


async def list_by_codes(session: AsyncSession, codes: frozenset[str]) -> list[PermissionModel]:
    """Return the permissions matching a set of codes, ignoring codes that do not exist."""
    if not codes:
        return []
    result = await session.execute(
        select(PermissionRecord).where(PermissionRecord.code.in_(sorted(codes)))
    )
    return [to_entity(record) for record in result.scalars().all()]


async def update(session: AsyncSession, permission: PermissionModel) -> PermissionModel:
    record = await session.get(PermissionRecord, permission.id)
    if record is None:
        raise NotFoundError(
            operation="update_permission",
            entity="permission",
            identifier=str(permission.id),
            detail="no row matched the identifier",
        )
    apply_entity(record, permission)
    await session.flush()
    return to_entity(record)


async def count_permissions(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(PermissionRecord))
    return int(result.scalar_one())
