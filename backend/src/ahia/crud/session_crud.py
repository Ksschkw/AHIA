"""Persistence for refresh sessions.

One table, one entity. The lookups this file provides are exactly the ones
authentication needs: find a session by the digest of a presented token, revoke
one, revoke a family, and prune what has expired.

The digest is what is stored and what is searched. Storing the token itself would
make the table a list of live credentials.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final, cast
from uuid import UUID

from sqlalchemy import DateTime, String, delete, func, select
from sqlalchemy import update as sql_update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import NotFoundError
from ahia.models.entities.session_model import SessionModel

_TABLE_NAME: Final[str] = "user_sessions"
_TOKEN_HASH_LENGTH: Final[int] = 128
_REVOCATION_REASON_LENGTH: Final[int] = 64


class SessionRecord(Base):
    """The persistence representation of one refresh session."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    refresh_token_hash: Mapped[str] = mapped_column(
        String(_TOKEN_HASH_LENGTH), nullable=False, unique=True, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(
        String(_REVOCATION_REASON_LENGTH), nullable=True
    )
    replaced_by_session_id: Mapped[UUID | None] = mapped_column(nullable=True)
    device_id: Mapped[UUID | None] = mapped_column(nullable=True)


def to_entity(record: SessionRecord) -> SessionModel:
    return SessionModel(
        id=record.id,
        user_id=record.user_id,
        refresh_token_hash=record.refresh_token_hash,
        expires_at=record.expires_at,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
        revoked_at=record.revoked_at,
        revocation_reason=record.revocation_reason,
        replaced_by_session_id=record.replaced_by_session_id,
        device_id=record.device_id,
    )


def apply_entity(record: SessionRecord, entity: SessionModel) -> None:
    record.user_id = entity.user_id
    record.refresh_token_hash = entity.refresh_token_hash
    record.expires_at = entity.expires_at
    record.created_at = entity.created_at
    record.last_used_at = entity.last_used_at
    record.revoked_at = entity.revoked_at
    record.revocation_reason = entity.revocation_reason
    record.replaced_by_session_id = entity.replaced_by_session_id
    record.device_id = entity.device_id


async def create(session: AsyncSession, entity: SessionModel) -> SessionModel:
    """Insert a session."""
    record = SessionRecord(id=entity.id)
    apply_entity(record, entity)
    session.add(record)
    await session.flush()
    return to_entity(record)


async def get_by_id(session: AsyncSession, session_id: UUID) -> SessionModel | None:
    record = await session.get(SessionRecord, session_id)
    return None if record is None else to_entity(record)


async def get_by_token_hash(session: AsyncSession, token_hash: str) -> SessionModel | None:
    """Return the session for a presented token digest, revoked or not.

    Revoked sessions are returned on purpose: a presented token that maps to a
    revoked-and-rotated session is the reuse signal, and filtering it here would
    turn a detectable theft into an ordinary "not found".
    """
    result = await session.execute(
        select(SessionRecord).where(SessionRecord.refresh_token_hash == token_hash)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def get_by_token_hash_for_update(
    session: AsyncSession, token_hash: str
) -> SessionModel | None:
    """Return the session for a digest with the row locked.

    Used by refresh: two concurrent refreshes of the same token must not both
    rotate, or one of the two resulting sessions is immediately orphaned and the
    reuse detector sees a legitimate token as a replay.
    """
    result = await session.execute(
        select(SessionRecord)
        .where(SessionRecord.refresh_token_hash == token_hash)
        .with_for_update()
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def update(session: AsyncSession, entity: SessionModel) -> SessionModel:
    """Persist changes to an existing session."""
    record = await session.get(SessionRecord, entity.id)
    if record is None:
        raise NotFoundError(
            operation="update_session",
            entity="session",
            identifier=str(entity.id),
            detail="no row matched the identifier",
        )
    apply_entity(record, entity)
    await session.flush()
    return to_entity(record)


async def revoke_all_for_user(
    session: AsyncSession,
    *,
    user_id: UUID,
    at: datetime,
    reason: str,
    except_session_id: UUID | None = None,
) -> int:
    """Revoke every active session a user holds, optionally sparing one.

    Sparing one is what makes "change password, stay signed in on this device"
    possible without leaving the stolen device signed in.
    """
    statement = (
        sql_update(SessionRecord)
        .where(SessionRecord.user_id == user_id)
        .where(SessionRecord.revoked_at.is_(None))
        .values(revoked_at=at, revocation_reason=reason)
    )
    if except_session_id is not None:
        statement = statement.where(SessionRecord.id != except_session_id)
    # `CursorResult.rowcount` is the affected-row count for an UPDATE. Typed as
    # Result by the ORM overloads, so the cast is explicit rather than silent.
    cursor_result = cast(CursorResult[Any], await session.execute(statement))
    return int(cursor_result.rowcount or 0)


async def list_active_for_user(
    session: AsyncSession,
    *,
    user_id: UUID,
    at: datetime,
) -> list[SessionModel]:
    """Return the user's unexpired, unrevoked sessions, newest first."""
    result = await session.execute(
        select(SessionRecord)
        .where(SessionRecord.user_id == user_id)
        .where(SessionRecord.revoked_at.is_(None))
        .where(SessionRecord.expires_at > at)
        .order_by(SessionRecord.created_at.desc())
    )
    return [to_entity(record) for record in result.scalars().all()]


async def delete_expired(session: AsyncSession, *, before: datetime) -> int:
    """Delete sessions that expired before a cutoff.

    An expired session carries no authority, so removing it is housekeeping
    rather than a security decision; its revocation chain is no longer needed
    once the reuse window has passed.
    """
    cursor_result = cast(
        CursorResult[Any],
        await session.execute(delete(SessionRecord).where(SessionRecord.expires_at < before)),
    )
    return int(cursor_result.rowcount or 0)


async def count_sessions(session: AsyncSession) -> int:
    """Return the number of session rows. Used by tests and operations tooling."""
    result = await session.execute(select(func.count()).select_from(SessionRecord))
    return int(result.scalar_one())
