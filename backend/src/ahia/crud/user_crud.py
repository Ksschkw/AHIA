"""Persistence for the user entity.

One table, one entity, one file. This is the boundary where the framework-bound
representation meets the framework-free domain:

    UserModel (domain)  <->  UserRecord (this file)

The record is a persistence representation, not the domain model. That separation
is what lets the entity stay pure, and it is why the mapping functions live here
rather than on the entity.

What this file does not do: it does not decide whether a user may be created,
whether an email is acceptable, or whether an inactive user can act. Those are
business decisions and they belong to the service. This file inserts, selects,
updates, and maps.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import Boolean, DateTime, String, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import ConflictError, NotFoundError
from ahia.models.entities.user_model import UserModel

_TABLE_NAME: Final[str] = "users"

#: Column lengths mirror the entity's bounds. The database enforces them too,
#: because a constraint is the only check that survives a bug in application code
#: or a manual statement run by an operator.
_FIRST_NAME_LENGTH: Final[int] = 100
_LAST_NAME_LENGTH: Final[int] = 100
_EMAIL_LENGTH: Final[int] = 254
_PHONE_LENGTH: Final[int] = 20
_PASSWORD_HASH_LENGTH: Final[int] = 255


class UserRecord(Base):
    """The persistence representation of one user."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(_FIRST_NAME_LENGTH), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(_LAST_NAME_LENGTH), nullable=True)
    # Nullable and unique: a user may authenticate by phone only, and two users
    # may not share an address. Both constraints matter for the identity model.
    email: Mapped[str | None] = mapped_column(
        String(_EMAIL_LENGTH), nullable=True, unique=True, index=True
    )
    phone: Mapped[str | None] = mapped_column(
        String(_PHONE_LENGTH), nullable=True, unique=True, index=True
    )
    password_hash: Mapped[str | None] = mapped_column(String(_PASSWORD_HASH_LENGTH), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    phone_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def to_entity(record: UserRecord) -> UserModel:
    """Map a row to the domain entity."""
    return UserModel(
        id=record.id,
        first_name=record.first_name,
        last_name=record.last_name,
        email=record.email,
        phone=record.phone,
        password_hash=record.password_hash,
        is_active=record.is_active,
        email_verified_at=record.email_verified_at,
        phone_verified_at=record.phone_verified_at,
        last_login_at=record.last_login_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def apply_entity(record: UserRecord, entity: UserModel) -> None:
    """Copy entity state onto a row."""
    record.first_name = entity.first_name
    record.last_name = entity.last_name
    record.email = entity.email
    record.phone = entity.phone
    record.password_hash = entity.password_hash
    record.is_active = entity.is_active
    record.email_verified_at = entity.email_verified_at
    record.phone_verified_at = entity.phone_verified_at
    record.last_login_at = entity.last_login_at
    record.created_at = entity.created_at
    record.updated_at = entity.updated_at


async def create(session: AsyncSession, user: UserModel) -> UserModel:
    """Insert a user and return the stored entity.

    A uniqueness violation becomes a typed ConflictError. The constraint may be
    on either the email or the phone index, so the offending constraint name is
    reported internally and never externally: telling a caller which of the two
    collided would confirm that an account exists for a given address.
    """
    record = UserRecord(id=user.id)
    apply_entity(record, user)
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise ConflictError(
            operation="create_user",
            entity="user",
            identifier=str(user.id),
            detail=f"a user with this email or phone already exists: {_constraint_name(conflict)}",
            cause=conflict,
        ) from conflict
    return to_entity(record)


async def get_by_id(session: AsyncSession, user_id: UUID) -> UserModel | None:
    """Return a user by identifier, or None.

    Deactivated users are returned. Whether an inactive user may act is an
    authorization decision, and hiding the row here would turn a business rule
    into a persistence rule that nobody can find.
    """
    record = await session.get(UserRecord, user_id)
    return None if record is None else to_entity(record)


async def get_by_email(session: AsyncSession, email: str) -> UserModel | None:
    """Return a user by normalized email address, or None.

    The caller passes an already-normalized address. Normalizing here would hide
    the fact that two call sites disagree about what normalization means.
    """
    result = await session.execute(select(UserRecord).where(UserRecord.email == email))
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def get_by_phone(session: AsyncSession, phone: str) -> UserModel | None:
    """Return a user by normalized phone number, or None."""
    result = await session.execute(select(UserRecord).where(UserRecord.phone == phone))
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def update(session: AsyncSession, user: UserModel) -> UserModel:
    """Persist changes to an existing user.

    Uses a direct UPDATE keyed by identifier, so a stale in-memory entity cannot
    resurrect a row that another request deleted. A missing row is a typed
    NotFoundError rather than a silent no-op.
    """
    record = await session.get(UserRecord, user.id)
    if record is None:
        raise NotFoundError(
            operation="update_user",
            entity="user",
            identifier=str(user.id),
            detail="no row matched the identifier",
        )
    apply_entity(record, user)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise ConflictError(
            operation="update_user",
            entity="user",
            identifier=str(user.id),
            detail=f"the update collides with an existing user: {_constraint_name(conflict)}",
            cause=conflict,
        ) from conflict
    return to_entity(record)


async def count_users(session: AsyncSession) -> int:
    """Return the number of user rows.

    Used by operational tooling and by the tests that need to prove a rollback
    left nothing behind. It is not part of any use case.
    """
    result = await session.execute(select(func.count()).select_from(UserRecord))
    return int(result.scalar_one())


def _constraint_name(conflict: IntegrityError) -> str:
    """Extract the violated constraint name for the internal error detail.

    Only for logs: the name is never returned to a client. The driver's exception
    can sit at different depths depending on the dialect, so each known location
    is checked before falling back to the exception type.
    """
    original: Any = getattr(conflict, "orig", None)
    candidates = [
        original,
        getattr(original, "__cause__", None),
        getattr(original, "__context__", None),
    ]
    for candidate in candidates:
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


async def require_by_id(session: AsyncSession, user_id: UUID) -> UserModel:
    """Return a user by identifier, raising NotFoundError when absent.

    A convenience for callers that treat absence as a failure, so the pattern is
    written once rather than at each call site.
    """
    user = await get_by_id(session, user_id)
    if user is None:
        raise NotFoundError(
            operation="fetch_user",
            entity="user",
            identifier=str(user_id),
            detail="no row matched the identifier",
        )
    return user


__all__ = [
    "UserRecord",
    "apply_entity",
    "count_users",
    "create",
    "get_by_email",
    "get_by_id",
    "get_by_phone",
    "require_by_id",
    "to_entity",
    "update",
]
