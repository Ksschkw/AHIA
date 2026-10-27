"""Persistence for push notification subscriptions and device tokens.

Stores Web Push subscriptions (VAPID endpoints and keys) and mobile push tokens
(Expo / FCM) keyed by tenant and recipient.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base

_TABLE_NAME: Final[str] = "push_subscriptions"
_PLATFORM_LENGTH: Final[int] = 32
_ENDPOINT_LENGTH: Final[int] = 1024


class PushSubscriptionRecord(Base):
    """The persistence representation of one push registration."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(_PLATFORM_LENGTH), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(_ENDPOINT_LENGTH), nullable=False)
    p256dh: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "uq_push_subscriptions_tenant_user_endpoint",
            "tenant_id",
            "user_id",
            "endpoint",
            unique=True,
        ),
        Index("ix_push_subscriptions_recipient", "tenant_id", "user_id"),
    )


async def upsert(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    platform: str,
    endpoint: str,
    p256dh: str | None = None,
    auth: str | None = None,
) -> PushSubscriptionRecord:
    """Store or refresh a push subscription for a user in a business."""
    now = datetime.now(UTC)
    stmt = select(PushSubscriptionRecord).where(
        PushSubscriptionRecord.tenant_id == tenant_id,
        PushSubscriptionRecord.user_id == user_id,
        PushSubscriptionRecord.endpoint == endpoint,
    )
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.platform = platform
        existing.p256dh = p256dh
        existing.auth = auth
        existing.updated_at = now
        await session.flush()
        return existing

    record = PushSubscriptionRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        platform=platform,
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth,
        created_at=now,
        updated_at=now,
    )
    session.add(record)
    await session.flush()
    return record


async def list_for_recipient(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
) -> list[PushSubscriptionRecord]:
    """Return all active push registrations for one user in this business."""
    stmt = (
        select(PushSubscriptionRecord)
        .where(
            PushSubscriptionRecord.tenant_id == tenant_id,
            PushSubscriptionRecord.user_id == user_id,
        )
        .order_by(PushSubscriptionRecord.updated_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: UUID,
) -> list[PushSubscriptionRecord]:
    """Return all active push registrations for any member of this business."""
    stmt = (
        select(PushSubscriptionRecord)
        .where(PushSubscriptionRecord.tenant_id == tenant_id)
        .order_by(PushSubscriptionRecord.updated_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def delete_by_endpoint(
    session: AsyncSession,
    *,
    endpoint: str,
) -> int:
    """Remove invalid or expired subscriptions by endpoint."""
    stmt = select(PushSubscriptionRecord).where(PushSubscriptionRecord.endpoint == endpoint)
    result = await session.execute(stmt)
    records = list(result.scalars().all())
    for rec in records:
        await session.delete(rec)
    if records:
        await session.flush()
    return len(records)
