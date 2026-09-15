"""Transport contracts for notifications.

**Addressed to the caller, and the contract has no field to say who.** A notification is raised for
one person in one business, and a client cannot ask for somebody else's: the read paths take the
recipient from the authenticated context, and there is no request shape that names a different one.

**A notification is read-only over HTTP.** The only write is marking one read, which is an
acknowledgement rather than an edit: nothing in the API creates a notification, changes its words or
deletes it. A client that could write one could put whatever it liked in a colleague's inbox.

**The body travels as text.** It is written for a person, it is bounded by the entity, and it is
never rendered as HTML by anything in this product.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ahia.models.entities.notification_model import NotificationType

NotificationLimit = Annotated[int, Field(ge=1, le=200, description="How many to return.")]


class NotificationResponseSchema(BaseModel):
    """One notification, as the person it is for sees it."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    notification_type: NotificationType
    title: str
    body: str
    entity_type: str | None
    entity_id: UUID | None
    created_at: datetime
    read_at: datetime | None
    is_read: bool

    @classmethod
    def from_projection(cls, notification: Any) -> NotificationResponseSchema:
        return cls(
            id=notification.id,
            notification_type=notification.notification_type,
            title=notification.title,
            body=notification.body,
            entity_type=notification.entity_type,
            entity_id=notification.entity_id,
            created_at=notification.created_at,
            read_at=notification.read_at,
            is_read=notification.is_read(),
        )


class NotificationCountSchema(BaseModel):
    """How many notifications this person has not read here."""

    model_config = ConfigDict(extra="forbid")

    unread: int
