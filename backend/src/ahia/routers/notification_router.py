"""HTTP transport for notifications.

Three routes on `/tenants/{tenant_id}/notifications`: the inbox, the unread count, and marking one
read.

**The recipient is the caller, and there is no way to ask for anybody else.** Every handler
passes the authenticated context's user to the service, and the service's readers take the
recipient as part of their lookup. A notification that belongs to a colleague is a not-found
rather than a refusal, so the answer does not confirm that it exists.

**Nothing here creates, edits or deletes a notification.** They are raised by the use case that
noticed something - today the scheduled low-stock evaluation - and a client that could write one
could put whatever it liked in somebody's inbox. Marking one read is the only state change, and it
records acknowledgement rather than hiding anything.

Every handler parses, calls one service method and shapes the response.
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from ahia.core.tenant_context import TenantContext
from ahia.routers.tenant_router import require_tenant_context
from ahia.schemas.notification_schema import (
    NotificationCountSchema,
    NotificationLimit,
    NotificationResponseSchema,
)
from ahia.services.notification_service import NotificationService

_TENANT_SCOPE_PREFIX: Final[str] = "/tenants/{tenant_id}"

router = APIRouter(prefix=_TENANT_SCOPE_PREFIX, tags=["notifications"])


def get_notification_service(request: Request) -> NotificationService:
    """Return the notification service for this request."""
    service: NotificationService = request.app.state.container.notification_service
    return service


NotificationServiceDependency = Annotated[NotificationService, Depends(get_notification_service)]
TenantContextDependency = Annotated[TenantContext, Depends(require_tenant_context)]


@router.get(
    "/notifications/unread-count",
    response_model=NotificationCountSchema,
    summary="How many notifications are unread",
)
async def read_unread_count(
    tenant_context: TenantContextDependency,
    service: NotificationServiceDependency,
) -> NotificationCountSchema:
    """Return the count, which is what a badge shows.

    Declared before the inbox route so the literal word is not read as a path parameter; the paths
    differ in shape, and ordering them explicitly is what keeps that true if one changes.
    """
    return NotificationCountSchema(unread=await service.unread_count(tenant_context))


@router.get(
    "/notifications",
    response_model=list[NotificationResponseSchema],
    summary="Read your own inbox",
)
async def list_notifications(
    tenant_context: TenantContextDependency,
    service: NotificationServiceDependency,
    unread_only: Annotated[
        bool, Query(description="Only the ones this person has not read.")
    ] = False,
    limit: Annotated[NotificationLimit, Query(description="How many to return.")] = 50,
) -> list[NotificationResponseSchema]:
    """Return the caller's notifications in this business, most recent first."""
    notifications = await service.list_notifications(
        tenant_context, unread_only=unread_only, limit=limit
    )
    return [NotificationResponseSchema.from_projection(item) for item in notifications]


@router.post(
    "/notifications/{notification_id}/read",
    response_model=NotificationResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Mark a notification as read",
)
async def mark_notification_read(
    notification_id: UUID,
    tenant_context: TenantContextDependency,
    service: NotificationServiceDependency,
) -> NotificationResponseSchema:
    """Record that the caller has seen this notification.

    Idempotent: reading it twice keeps the first moment, because that is when somebody actually saw
    it.
    """
    notification = await service.mark_read(tenant_context, notification_id=notification_id)
    return NotificationResponseSchema.from_projection(notification)


@router.post(
    "/notifications/read-all",
    response_model=NotificationCountSchema,
    status_code=status.HTTP_200_OK,
    summary="Mark everything in your inbox as read",
)
async def mark_all_notifications_read(
    tenant_context: TenantContextDependency,
    service: NotificationServiceDependency,
) -> NotificationCountSchema:
    """Clear the badge, and report what is left unread - which is nothing.

    A count rather than a list: a client that just cleared its inbox needs to know it worked, and
    a response carrying every notification it changed would be the inbox again. The number that
    changed is in the log line the service writes, where an operator can see it.
    """
    await service.mark_all_read(tenant_context)
    return NotificationCountSchema(unread=0)
