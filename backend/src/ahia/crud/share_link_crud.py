"""Persistence for share links.

One table, one entity, one file. Three properties are worth stating.

The token is stored as a digest, and the digest is the lookup key
    `UNIQUE(token_hash)`. A public request arrives with a plaintext token, the service digests it
    and looks the row up; the plaintext is never written, so a leaked table yields no working links.
    The uniqueness also means two links cannot share a digest, which would make revocation
    ambiguous.

Revocation is an update, and it is the only update
    A revoked link keeps its row, its resource and its creation details, because "this invoice was
    shared and then withdrawn" is a fact a business may need. Nothing deletes a link: a deleted row
    would leave the same questions unanswerable, and the digest being gone would be
    indistinguishable from a token that never existed.

A link is found by its digest, never listed by its token
    The public path asks "does this digest open anything"; the management path asks "what links
    does this record have". Both are indexed, and neither ever returns a token because the table
    does not hold one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import NotFoundError
from ahia.models.entities.share_link_model import (
    TOKEN_HASH_LENGTH,
    ShareableResource,
    ShareLinkModel,
)

_TABLE_NAME: Final[str] = "share_links"
_RESOURCE_TYPE_LENGTH: Final[int] = 32


class ShareLinkRecord(Base):
    """The persistence representation of one share link."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(_RESOURCE_TYPE_LENGTH), nullable=False)
    # Not a foreign key: a link can point at a sale today and a shipment tomorrow, and a column
    # per resource type would make this table depend on every module that can be shared.
    resource_id: Mapped[UUID] = mapped_column(nullable=False)
    token_hash: Mapped[str] = mapped_column(String(TOKEN_HASH_LENGTH), nullable=False, unique=True)
    # Copied rather than referenced: it is who created the link, and the answer to "who shared
    # this" must not change because a user row was later edited.
    created_by_user_id: Mapped[UUID | None] = mapped_column(nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_share_links_tenant_resource", "tenant_id", "resource_type", "resource_id"),
        Index("ix_share_links_tenant_created", "tenant_id", "created_at"),
    )


def to_entity(record: ShareLinkRecord) -> ShareLinkModel:
    return ShareLinkModel(
        id=record.id,
        tenant_id=record.tenant_id,
        resource_type=ShareableResource(record.resource_type),
        resource_id=record.resource_id,
        token_hash=record.token_hash,
        expires_at=record.expires_at,
        created_at=record.created_at,
        created_by_user_id=record.created_by_user_id,
        revoked_at=record.revoked_at,
    )


def apply_entity(record: ShareLinkRecord, entity: ShareLinkModel) -> None:
    record.tenant_id = entity.tenant_id
    record.resource_type = entity.resource_type.value
    record.resource_id = entity.resource_id
    record.token_hash = entity.token_hash
    record.created_by_user_id = entity.created_by_user_id
    record.expires_at = entity.expires_at
    record.revoked_at = entity.revoked_at
    record.created_at = entity.created_at


async def create(session: AsyncSession, link: ShareLinkModel) -> ShareLinkModel:
    """Insert a share link."""
    record = ShareLinkRecord(id=link.id)
    apply_entity(record, link)
    session.add(record)
    await session.flush()
    return to_entity(record)


async def get_by_token_hash(session: AsyncSession, token_hash: str) -> ShareLinkModel | None:
    """Return the link a token digest opens, or None.

    The digest is the only thing the public path knows: the request carries a token, the service
    digests it, and this is the lookup. Nothing here can enumerate links.
    """
    result = await session.execute(
        select(ShareLinkRecord).where(ShareLinkRecord.token_hash == token_hash)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def get_for_tenant(
    session: AsyncSession, *, tenant_id: UUID, share_link_id: UUID
) -> ShareLinkModel | None:
    """Return one link, scoped to the business that created it."""
    result = await session.execute(
        select(ShareLinkRecord)
        .where(ShareLinkRecord.tenant_id == tenant_id)
        .where(ShareLinkRecord.id == share_link_id)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def list_for_resource(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    resource_type: ShareableResource,
    resource_id: UUID,
) -> list[ShareLinkModel]:
    """Return the links a record has been shared through, most recent first."""
    result = await session.execute(
        select(ShareLinkRecord)
        .where(ShareLinkRecord.tenant_id == tenant_id)
        .where(ShareLinkRecord.resource_type == resource_type.value)
        .where(ShareLinkRecord.resource_id == resource_id)
        .order_by(ShareLinkRecord.created_at.desc(), ShareLinkRecord.id.desc())
    )
    return [to_entity(record) for record in result.scalars().all()]


async def update(session: AsyncSession, link: ShareLinkModel) -> ShareLinkModel:
    """Persist a change to a link. Revocation is the only change there is."""
    result = await session.execute(
        select(ShareLinkRecord)
        .where(ShareLinkRecord.tenant_id == link.tenant_id)
        .where(ShareLinkRecord.id == link.id)
    )
    stored = result.scalar_one_or_none()
    if stored is None:
        raise NotFoundError(
            operation="revoke_share_link",
            entity="share_link",
            identifier=str(link.id),
            detail="no share link matched in this business",
        )
    stored.revoked_at = link.revoked_at
    await session.flush()
    return to_entity(stored)
