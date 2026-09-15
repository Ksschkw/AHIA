"""Persistence for notifications.

One table, one entity, one file. Four properties are worth stating.

The dedupe key is unique per recipient, per business, where it is present
    `UNIQUE(tenant_id, recipient_user_id, dedupe_key) WHERE dedupe_key IS NOT NULL`. A scheduled
    evaluator runs on a timer and a product that was low on Tuesday is still low on Wednesday:
    without this constraint the same person receives the same alert every hour until they stop
    reading any of them. The constraint makes the second attempt a no-op rather than a second row,
    and the partial clause is what lets a notification raised by hand - with no key to dedupe on -
    coexist with the ones a job raises.

A notification is read by its recipient, and the query is what says so
    Every reader takes a `recipient_user_id` and filters on it. That is not a convention a caller
    could forget: there is no function here that returns another person's notifications, and the API
    has no way to ask for one.

Reading is an update, and it is the only one
    `mark_read` sets `read_at` once. Nothing deletes a notification: an inbox that empties itself
    cannot answer "was anybody told", and the answer matters more than the tidiness.

The unread count is a query, not a column
    A counter column would need maintaining on every write and would be wrong the first time a
    transaction rolled back. The count is computed where the rows are, which is what an index on
    `(tenant_id, recipient_user_id, read_at)` is for.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.crud.integrity_violations import constraint_name, translate_integrity_violation
from ahia.models.entities.notification_model import (
    MAXIMUM_DEDUPE_KEY_LENGTH,
    MAXIMUM_ENTITY_TYPE_LENGTH,
    MAXIMUM_TITLE_LENGTH,
    NotificationModel,
    NotificationType,
)

_TABLE_NAME: Final[str] = "notifications"
_TYPE_LENGTH: Final[int] = 32

_CONFLICT_DETAILS: Final[dict[str, str]] = {
    "uq_notifications_tenant_recipient_dedupe": "this notification has already been raised",
}

_MISSING_REFERENCE: Final[str] = (
    "the business, recipient or device this notification references does not exist"
)


class NotificationRecord(Base):
    """The persistence representation of one notification."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    # A real reference: a notification addressed to somebody who does not exist is a row nobody can
    # ever read, and the reader filters on this column.
    recipient_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(_TYPE_LENGTH), nullable=False)
    title: Mapped[str] = mapped_column(String(MAXIMUM_TITLE_LENGTH), nullable=False)
    # TEXT rather than a bounded VARCHAR: the entity is where the bound lives, and a second, weaker
    # bound on the column would only be a second answer.
    body: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(
        String(MAXIMUM_ENTITY_TYPE_LENGTH), nullable=True
    )
    # Not a foreign key: a notification can be about a product today and a sale tomorrow, and a
    # column per subject would make this table depend on every module that can raise one.
    entity_id: Mapped[UUID | None] = mapped_column(nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(MAXIMUM_DEDUPE_KEY_LENGTH), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # One alert per recipient per business, where the product named it.
        Index(
            "uq_notifications_tenant_recipient_dedupe",
            "tenant_id",
            "recipient_user_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("dedupe_key IS NOT NULL"),
        ),
        # The inbox, most recent first.
        Index("ix_notifications_recipient_created", "tenant_id", "recipient_user_id", "created_at"),
        # The unread count.
        Index("ix_notifications_recipient_read", "tenant_id", "recipient_user_id", "read_at"),
    )


def to_entity(record: NotificationRecord) -> NotificationModel:
    return NotificationModel(
        id=record.id,
        tenant_id=record.tenant_id,
        recipient_user_id=record.recipient_user_id,
        notification_type=NotificationType(record.notification_type),
        title=record.title,
        body=record.body,
        created_at=record.created_at,
        entity_type=record.entity_type,
        entity_id=record.entity_id,
        dedupe_key=record.dedupe_key,
        read_at=record.read_at,
    )


def apply_entity(record: NotificationRecord, entity: NotificationModel) -> None:
    record.tenant_id = entity.tenant_id
    record.recipient_user_id = entity.recipient_user_id
    record.notification_type = entity.notification_type.value
    record.title = entity.title
    record.body = entity.body
    record.entity_type = entity.entity_type
    record.entity_id = entity.entity_id
    record.dedupe_key = entity.dedupe_key
    record.read_at = entity.read_at
    record.created_at = entity.created_at


async def create_or_skip(
    session: AsyncSession, notification: NotificationModel
) -> tuple[NotificationModel, bool]:
    """Insert a notification, or return the one this key already raised.

    Returns the row and whether this call created it. A second attempt at the same alert is an
    ordinary outcome of a job that runs on a timer, not an error: the caller wanted the person told,
    and the person has been told.
    """
    if notification.dedupe_key is not None:
        existing = await get_by_dedupe_key(
            session,
            tenant_id=notification.tenant_id,
            recipient_user_id=notification.recipient_user_id,
            dedupe_key=notification.dedupe_key,
        )
        if existing is not None:
            return existing, False

    record = NotificationRecord(id=notification.id)
    apply_entity(record, notification)
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        name = constraint_name(conflict)
        if name in _CONFLICT_DETAILS and notification.dedupe_key is not None:
            # Two evaluators ran at the same moment: the other one won, and this call's answer is
            # the row it wrote rather than a failure.
            existing = await get_by_dedupe_key(
                session,
                tenant_id=notification.tenant_id,
                recipient_user_id=notification.recipient_user_id,
                dedupe_key=notification.dedupe_key,
            )
            if existing is not None:
                return existing, False
        raise translate_integrity_violation(
            conflict,
            operation="raise_notification",
            entity="notification",
            identifier=str(notification.id),
            conflict_detail=_CONFLICT_DETAILS.get(
                name, f"this notification collides with an existing one ({name})"
            ),
            missing_detail=_MISSING_REFERENCE,
        ) from conflict
    return to_entity(record), True


async def get_by_dedupe_key(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    recipient_user_id: UUID,
    dedupe_key: str,
) -> NotificationModel | None:
    """Return the notification this key already raised, if it was raised before."""
    result = await session.execute(
        select(NotificationRecord)
        .where(NotificationRecord.tenant_id == tenant_id)
        .where(NotificationRecord.recipient_user_id == recipient_user_id)
        .where(NotificationRecord.dedupe_key == dedupe_key)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def get_for_recipient(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    recipient_user_id: UUID,
    notification_id: UUID,
) -> NotificationModel | None:
    """Return one notification, addressed to this person in this business.

    The recipient is part of the lookup rather than a check afterwards: a notification belongs to
    the person it was raised for, and there is no query here that can return somebody else's.
    """
    result = await session.execute(
        select(NotificationRecord)
        .where(NotificationRecord.tenant_id == tenant_id)
        .where(NotificationRecord.recipient_user_id == recipient_user_id)
        .where(NotificationRecord.id == notification_id)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def list_for_recipient(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    recipient_user_id: UUID,
    unread_only: bool = False,
    limit: int = 50,
) -> list[NotificationModel]:
    """Return one person's inbox in one business, most recent first."""
    statement = (
        select(NotificationRecord)
        .where(NotificationRecord.tenant_id == tenant_id)
        .where(NotificationRecord.recipient_user_id == recipient_user_id)
    )
    if unread_only:
        statement = statement.where(NotificationRecord.read_at.is_(None))
    result = await session.execute(
        statement.order_by(
            NotificationRecord.created_at.desc(), NotificationRecord.id.desc()
        ).limit(limit)
    )
    return [to_entity(record) for record in result.scalars().all()]


async def count_unread(session: AsyncSession, *, tenant_id: UUID, recipient_user_id: UUID) -> int:
    """Return how many notifications this person has not read in this business."""
    result = await session.execute(
        select(func.count())
        .select_from(NotificationRecord)
        .where(NotificationRecord.tenant_id == tenant_id)
        .where(NotificationRecord.recipient_user_id == recipient_user_id)
        .where(NotificationRecord.read_at.is_(None))
    )
    return int(result.scalar_one())


async def mark_read(session: AsyncSession, notification: NotificationModel) -> NotificationModel:
    """Set the moment this person read the notification.

    The only update this module offers, and it is idempotent through the entity: the first moment is
    the one that is kept.
    """
    result = await session.execute(
        select(NotificationRecord)
        .where(NotificationRecord.tenant_id == notification.tenant_id)
        .where(NotificationRecord.recipient_user_id == notification.recipient_user_id)
        .where(NotificationRecord.id == notification.id)
    )
    stored = result.scalar_one_or_none()
    if stored is None:
        return notification
    stored.read_at = notification.read_at
    await session.flush()
    return to_entity(stored)
