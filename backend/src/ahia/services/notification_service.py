"""Notification use cases: raising an alert, and reading your own inbox.

# Audit exemption: a notification is a message to a person rather than a change to business
# data, and the row is itself the record of what was raised, for whom and when. The action that
# noticed something - today, the scheduled low-stock evaluation - is what a trail entry would
# describe, and duplicating the message into the trail would put product names and stock counts
# in a second store with a longer retention.

**Raising a notification needs no permission, and reading one needs no permission either.** What it
needs is to be the person it is for. A notification is addressed to one user in one business, and
every reader in `notification_crud` takes the recipient as part of its lookup rather than checking
it
afterwards - so there is no code path that returns somebody else's inbox, and no permission code was
invented to stand in for that. The active membership a `TenantContext` already carries is what
establishes that the person is in the business at all.

**`raise` is idempotent when it is given a dedupe key.** This is the whole reason the key exists: a
scheduled evaluator runs every hour, and a product that has been low since Tuesday is still low on
Wednesday. The caller supplies a key built from what the alert is about and when it is due - the
service does not invent a window, because only the caller knows whether "once a day" or "once a
week"
is right for the thing it is reporting.

**A batch of alerts shares one instant.** `raise_many` takes the moment once and gives it to every
notification, so an inbox ordered by three clocks inside one second is an inbox somebody can read.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.errors import NotFoundError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.tenant_context import TenantContext
from ahia.crud import notification_crud
from ahia.models.entities.notification_model import (
    NotificationModel,
    NotificationType,
)

_NOTIFICATION_LOGGER_NAME: Final[str] = "ahia.services.notification"


@dataclass(frozen=True, slots=True)
class NotificationRequest:
    """One notification to raise, before it has an identifier or a moment."""

    notification_type: NotificationType
    title: str
    body: str
    entity_type: str | None = None
    entity_id: UUID | None = None
    dedupe_key: str | None = None


@dataclass(frozen=True, slots=True)
class RaisedNotifications:
    """What raising a batch produced, and what it declined to produce again."""

    raised: list[NotificationModel]
    skipped_duplicates: int = 0

    @property
    def raised_count(self) -> int:
        return len(self.raised)


class NotificationService:
    """Notification use cases."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._logger = (logger or get_logger(_NOTIFICATION_LOGGER_NAME)).bind(
            component="notification_service", layer="service"
        )

    # ------------------------------------------------------------------
    # Raising
    # ------------------------------------------------------------------

    async def raise_many(
        self,
        *,
        tenant_id: UUID,
        recipient_user_id: UUID,
        notifications: Sequence[NotificationRequest],
        now: datetime | None = None,
    ) -> RaisedNotifications:
        """Raise a batch for one person, skipping anything the dedupe key already raised.

        Takes a tenant and a recipient rather than a context, because the callers are jobs: the
        scheduled evaluator has no caller identity, and inventing one would put a name on an alert
        nobody's action produced. A user-facing caller that wants to notify somebody goes through
        the
        use case that owns the fact - the evaluator is the only one there is today.
        """
        moment = now or datetime.now(UTC)
        raised: list[NotificationModel] = []
        skipped = 0
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            for request in notifications:
                candidate = NotificationModel.raise_for(
                    notification_id=uuid4(),
                    tenant_id=tenant_id,
                    recipient_user_id=recipient_user_id,
                    notification_type=request.notification_type,
                    title=request.title,
                    body=request.body,
                    entity_type=request.entity_type,
                    entity_id=request.entity_id,
                    dedupe_key=request.dedupe_key,
                    now=moment,
                )
                stored, created = await notification_crud.create_or_skip(session, candidate)
                if created:
                    raised.append(stored)
                else:
                    skipped += 1
            await unit_of_work.commit()

        if raised:
            self._logger.info(
                "notifications_raised",
                tenant_id=str(tenant_id),
                recipient_user_id=str(recipient_user_id),
                raised_count=len(raised),
                skipped_duplicates=skipped,
                notification_types=sorted(
                    {notification.notification_type.value for notification in raised}
                ),
            )
        return RaisedNotifications(raised=raised, skipped_duplicates=skipped)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    async def list_notifications(
        self,
        tenant_context: TenantContext,
        *,
        unread_only: bool = False,
        limit: int = 50,
    ) -> list[NotificationModel]:
        """Return this person's inbox in this business, most recent first."""
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await notification_crud.list_for_recipient(
                unit_of_work.session_handle,
                tenant_id=tenant_context.tenant_id,
                recipient_user_id=tenant_context.user_id,
                unread_only=unread_only,
                limit=limit,
            )

    async def unread_count(self, tenant_context: TenantContext) -> int:
        """Return how many notifications this person has not read here."""
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await notification_crud.count_unread(
                unit_of_work.session_handle,
                tenant_id=tenant_context.tenant_id,
                recipient_user_id=tenant_context.user_id,
            )

    async def mark_read(
        self, tenant_context: TenantContext, *, notification_id: UUID
    ) -> NotificationModel:
        """Mark one of this person's notifications as read.

        A notification that belongs to somebody else is a not-found rather than a refusal: telling a
        caller "that exists but is not yours" would confirm that it exists.
        """
        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            stored = await notification_crud.get_for_recipient(
                session,
                tenant_id=tenant_context.tenant_id,
                recipient_user_id=tenant_context.user_id,
                notification_id=notification_id,
            )
            if stored is None:
                raise NotFoundError(
                    operation="mark_notification_read",
                    entity="notification",
                    identifier=str(notification_id),
                    detail="no notification matched for this person",
                )
            updated = await notification_crud.mark_read(session, stored.mark_read(at=now))
            await unit_of_work.commit()
        return updated

    async def mark_all_read(self, tenant_context: TenantContext) -> int:
        """Mark everything in this person's inbox as read, and return how many changed."""
        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            unread = await notification_crud.list_for_recipient(
                session,
                tenant_id=tenant_context.tenant_id,
                recipient_user_id=tenant_context.user_id,
                unread_only=True,
                limit=500,
            )
            for notification in unread:
                await notification_crud.mark_read(session, notification.mark_read(at=now))
            await unit_of_work.commit()
        return len(unread)
