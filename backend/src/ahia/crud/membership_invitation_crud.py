"""Persistence for membership invitations.

One table, one entity. The lookup that matters is by token digest, because that is
how an invitation is accepted; the others support an owner reviewing who has been
invited and an invitee seeing what is waiting for them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import DateTime, String, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import ConflictError, NotFoundError
from ahia.models.entities.membership_invitation_model import MembershipInvitationModel

_TABLE_NAME: Final[str] = "membership_invitations"
_TOKEN_HASH_LENGTH: Final[int] = 128
_ROLE_NAME_LENGTH: Final[int] = 32
_EMAIL_LENGTH: Final[int] = 254
_PHONE_LENGTH: Final[int] = 20


class MembershipInvitationRecord(Base):
    """The persistence representation of one invitation."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    role_name: Mapped[str] = mapped_column(String(_ROLE_NAME_LENGTH), nullable=False)
    token_hash: Mapped[str] = mapped_column(
        String(_TOKEN_HASH_LENGTH), nullable=False, unique=True, index=True
    )
    invited_email: Mapped[str | None] = mapped_column(
        String(_EMAIL_LENGTH), nullable=True, index=True
    )
    invited_phone: Mapped[str | None] = mapped_column(
        String(_PHONE_LENGTH), nullable=True, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by_user_id: Mapped[UUID | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def to_entity(record: MembershipInvitationRecord) -> MembershipInvitationModel:
    return MembershipInvitationModel(
        id=record.id,
        tenant_id=record.tenant_id,
        role_name=record.role_name,
        token_hash=record.token_hash,
        invited_email=record.invited_email,
        invited_phone=record.invited_phone,
        expires_at=record.expires_at,
        created_at=record.created_at,
        created_by_user_id=record.created_by_user_id,
        accepted_at=record.accepted_at,
        accepted_by_user_id=record.accepted_by_user_id,
        revoked_at=record.revoked_at,
    )


def apply_entity(record: MembershipInvitationRecord, entity: MembershipInvitationModel) -> None:
    record.tenant_id = entity.tenant_id
    record.role_name = entity.role_name
    record.token_hash = entity.token_hash
    record.invited_email = entity.invited_email
    record.invited_phone = entity.invited_phone
    record.expires_at = entity.expires_at
    record.created_at = entity.created_at
    record.created_by_user_id = entity.created_by_user_id
    record.accepted_at = entity.accepted_at
    record.accepted_by_user_id = entity.accepted_by_user_id
    record.revoked_at = entity.revoked_at


async def create(
    session: AsyncSession, invitation: MembershipInvitationModel
) -> MembershipInvitationModel:
    record = MembershipInvitationRecord(id=invitation.id)
    apply_entity(record, invitation)
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise ConflictError(
            operation="create_invitation",
            entity="membership_invitation",
            identifier=str(invitation.id),
            detail=f"the invitation token collides: {_constraint_name(conflict)}",
            cause=conflict,
        ) from conflict
    return to_entity(record)


async def get_by_id(session: AsyncSession, invitation_id: UUID) -> MembershipInvitationModel | None:
    record = await session.get(MembershipInvitationRecord, invitation_id)
    return None if record is None else to_entity(record)


async def get_by_token_hash(
    session: AsyncSession, token_hash: str
) -> MembershipInvitationModel | None:
    """Return the invitation for a presented token digest, whatever its state.

    Expired, accepted and revoked invitations are returned so the caller can say
    which it was internally; externally every one of them is the same refusal.
    """
    result = await session.execute(
        select(MembershipInvitationRecord).where(
            MembershipInvitationRecord.token_hash == token_hash
        )
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def list_for_tenant(
    session: AsyncSession, tenant_id: UUID
) -> list[MembershipInvitationModel]:
    """Return every invitation a business has issued, newest first."""
    result = await session.execute(
        select(MembershipInvitationRecord)
        .where(MembershipInvitationRecord.tenant_id == tenant_id)
        .order_by(MembershipInvitationRecord.created_at.desc())
    )
    return [to_entity(record) for record in result.scalars().all()]


async def list_pending_for_identity(
    session: AsyncSession,
    *,
    email: str | None,
    phone: str | None,
) -> list[MembershipInvitationModel]:
    """Return the invitations addressed to one identity.

    Matched on the exact channel used, so an invitation sent to a phone number is
    not offered to whoever holds a similar email address.
    """
    conditions = []
    if email is not None:
        conditions.append(MembershipInvitationRecord.invited_email == email)
    if phone is not None:
        conditions.append(MembershipInvitationRecord.invited_phone == phone)
    if not conditions:
        return []

    result = await session.execute(
        select(MembershipInvitationRecord)
        .where(or_(*conditions))
        .order_by(MembershipInvitationRecord.created_at.desc())
    )
    return [to_entity(record) for record in result.scalars().all()]


async def update(
    session: AsyncSession, invitation: MembershipInvitationModel
) -> MembershipInvitationModel:
    record = await session.get(MembershipInvitationRecord, invitation.id)
    if record is None:
        raise NotFoundError(
            operation="update_invitation",
            entity="membership_invitation",
            identifier=str(invitation.id),
            detail="no row matched the identifier",
        )
    apply_entity(record, invitation)
    await session.flush()
    return to_entity(record)


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
