"""A notification: one thing the product decided a person should be told.

 The specification lists the channels it intends - in-app first, push and message channels later -
and
 this is the record the first one reads. Whatever eventually delivers a notification, the fact that
it
was raised, to whom, and whether it was read lives here.

**Addressed to a person, in a business.** `recipient_user_id` is who it is for and `tenant_id` is
where it happened, because a person can belong to more than one business and "your stock is low" is
only meaningful inside one of them. The read path is scoped by the recipient: a caller can see their
own notifications, and the query is what enforces it.

 **A notification is derived, never authored by a client.** Nothing in the product lets a client
write
one; they are raised by the use case that noticed something. `entity_type` and `entity_id` point at
what it is about, so a client can open the thing rather than guess from the words.

**`dedupe_key` is what stops the same alert arriving every hour.** A scheduled evaluator runs on a
timer, and a product that has been low on stock since Tuesday is still low on Wednesday: without a
key the person receives the same message a dozen times and stops reading any of them. The key is
unique per business and recipient, so raising the same alert twice is a no-op rather than a second
row.

 **Read is a state, not a deletion.** `read_at` records when somebody acknowledged it. Nothing
deletes
a notification through the API: an inbox that empties itself cannot answer "was anybody told".
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError

MAXIMUM_TITLE_LENGTH: Final[int] = 120
MAXIMUM_BODY_LENGTH: Final[int] = 500
MAXIMUM_ENTITY_TYPE_LENGTH: Final[int] = 64
MAXIMUM_DEDUPE_KEY_LENGTH: Final[int] = 128

#: The characters a dedupe key may use: lower-case words joined by underscores and colons, so a key
#: is a vocabulary rather than free text. It is a name a job builds, not a value a person types.
_KEY_CHARACTERS: Final[str] = "abcdefghijklmnopqrstuvwxyz0123456789_:-"


class NotificationType(StrEnum):
    """What kind of thing this is.

    A closed set. A notification type a client does not recognise is a notification it cannot
    render, and the type is what a client keys its icon and its routing off.
    """

    LOW_STOCK = "LOW_STOCK"
    STOCK_OUT = "STOCK_OUT"


@dataclass(frozen=True, slots=True)
class NotificationModel:
    """One notification for one person."""

    id: UUID
    tenant_id: UUID
    recipient_user_id: UUID
    notification_type: NotificationType
    title: str
    body: str
    created_at: datetime
    entity_type: str | None = None
    entity_id: UUID | None = None
    dedupe_key: str | None = None
    read_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_aware(self.created_at, field_name="created_at", notification_id=self.id)
        if not isinstance(self.notification_type, NotificationType):
            raise EntityInvariantError(
                operation="raise_notification",
                entity="notification",
                identifier=str(self.id),
                detail=(
                    "notification_type must be a NotificationType, "
                    f"not {type(self.notification_type).__name__}"
                ),
            )
        for field_name, value, maximum in (
            ("title", self.title, MAXIMUM_TITLE_LENGTH),
            ("body", self.body, MAXIMUM_BODY_LENGTH),
        ):
            if not value.strip():
                raise EntityInvariantError(
                    operation="raise_notification",
                    entity="notification",
                    identifier=str(self.id),
                    detail=f"{field_name} is required; an empty notification tells nobody anything",
                )
            if len(value) > maximum:
                raise EntityInvariantError(
                    operation="raise_notification",
                    entity="notification",
                    identifier=str(self.id),
                    detail=f"{field_name} exceeds {maximum} characters",
                )

        if self.entity_type is not None:
            if not self.entity_type.strip():
                raise EntityInvariantError(
                    operation="raise_notification",
                    entity="notification",
                    identifier=str(self.id),
                    detail="entity_type is empty; use None instead",
                )
            if len(self.entity_type) > MAXIMUM_ENTITY_TYPE_LENGTH:
                raise EntityInvariantError(
                    operation="raise_notification",
                    entity="notification",
                    identifier=str(self.id),
                    detail=f"entity_type exceeds {MAXIMUM_ENTITY_TYPE_LENGTH} characters",
                )

        if self.dedupe_key is not None:
            _require_dedupe_key(self.dedupe_key, notification_id=self.id)

        if self.read_at is not None:
            _require_aware(self.read_at, field_name="read_at", notification_id=self.id)
            if self.read_at < self.created_at:
                raise EntityInvariantError(
                    operation="raise_notification",
                    entity="notification",
                    identifier=str(self.id),
                    detail="read_at is earlier than created_at",
                )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def raise_for(
        cls,
        *,
        notification_id: UUID,
        tenant_id: UUID,
        recipient_user_id: UUID,
        notification_type: NotificationType,
        title: str,
        body: str,
        now: datetime,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        dedupe_key: str | None = None,
    ) -> NotificationModel:
        """Build a notification for one person.

        `now` is passed in rather than read here so a batch of alerts raised by one job shares one
        instant: an inbox ordered by three clocks inside one second is an inbox nobody can read.
        """
        return cls(
            id=notification_id,
            tenant_id=tenant_id,
            recipient_user_id=recipient_user_id,
            notification_type=notification_type,
            title=title.strip(),
            body=body.strip(),
            created_at=now,
            entity_type=entity_type.strip() if entity_type else None,
            entity_id=entity_id,
            dedupe_key=dedupe_key.strip() if dedupe_key else None,
        )

    # ------------------------------------------------------------------
    # Derived state and transitions
    # ------------------------------------------------------------------

    def is_read(self) -> bool:
        return self.read_at is not None

    def mark_read(self, *, at: datetime) -> NotificationModel:
        """Return the notification read.

        Idempotent: reading twice keeps the first moment, because that is when somebody actually saw
        it and the second request changed nothing.
        """
        if self.is_read():
            return self
        return replace(self, read_at=at)

    def describe_for_audit(self) -> dict[str, str]:
        """Return identifiers and the type, and never the words.

        The title and the body are written for a person and can name a product, a customer or an
        amount. The audit trail says which notification was raised, for whom and about what; support
        reads the text from the row.
        """
        description = {
            "notification_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "recipient_user_id": str(self.recipient_user_id),
            "notification_type": self.notification_type.value,
            "is_read": "true" if self.is_read() else "false",
        }
        if self.entity_type is not None:
            description["entity_type"] = self.entity_type
        if self.entity_id is not None:
            description["entity_id"] = str(self.entity_id)
        return description


def _require_dedupe_key(value: str, *, notification_id: UUID) -> None:
    if not value.strip():
        raise EntityInvariantError(
            operation="raise_notification",
            entity="notification",
            identifier=str(notification_id),
            detail="dedupe_key is empty; use None instead",
        )
    if len(value) > MAXIMUM_DEDUPE_KEY_LENGTH:
        raise EntityInvariantError(
            operation="raise_notification",
            entity="notification",
            identifier=str(notification_id),
            detail=f"dedupe_key exceeds {MAXIMUM_DEDUPE_KEY_LENGTH} characters",
        )
    if any(character not in _KEY_CHARACTERS for character in value):
        raise EntityInvariantError(
            operation="raise_notification",
            entity="notification",
            identifier=str(notification_id),
            detail=(
                "dedupe_key must be lower-case words joined by underscores or colons; it is a name "
                "the product builds, not text a person writes"
            ),
        )


def _require_aware(moment: datetime, *, field_name: str, notification_id: UUID) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="raise_notification",
            entity="notification",
            identifier=str(notification_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
