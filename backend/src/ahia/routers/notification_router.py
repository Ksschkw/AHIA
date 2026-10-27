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

import os
from typing import Annotated, Any, Final
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


@router.get(
    "/notifications/vapid-public-key",
    summary="Get VAPID public key for web push notifications",
)
async def get_vapid_public_key() -> dict[str, str]:
    """Return the VAPID public key for Web Push client subscription."""
    key = os.getenv("VAPID_PUBLIC_KEY", "")
    return {"public_key": key}


@router.post(
    "/notifications/push-subscription",
    summary="Register a push subscription (VAPID / Web Push or Native token)",
)
async def register_push_subscription(
    payload: dict[str, Any],
    tenant_context: TenantContextDependency,
    service: NotificationServiceDependency,
) -> dict[str, str]:
    """Register client push token or browser subscription."""
    platform = str(payload.get("platform", "web"))
    endpoint = ""
    p256dh = None
    auth = None

    if "subscription" in payload and isinstance(payload["subscription"], dict):
        sub = payload["subscription"]
        endpoint = str(sub.get("endpoint", ""))
        keys = sub.get("keys", {})
        if isinstance(keys, dict):
            p256dh = keys.get("p256dh")
            auth = keys.get("auth")
    elif "token" in payload:
        endpoint = str(payload["token"])
    elif "endpoint" in payload:
        endpoint = str(payload["endpoint"])
        p256dh = payload.get("p256dh")
        auth = payload.get("auth")

    if endpoint:
        await service.register_push_subscription(
            tenant_id=tenant_context.tenant_id,
            user_id=tenant_context.user_id,
            platform=platform,
            endpoint=endpoint,
            p256dh=str(p256dh) if p256dh else None,
            auth=str(auth) if auth else None,
        )
    return {"status": "ok", "message": "Push subscription registered"}


@router.post(
    "/notifications/test-push",
    summary="Send a test push notification to caller's registered devices",
)
async def send_test_push(
    payload: dict[str, Any],
    tenant_context: TenantContextDependency,
    service: NotificationServiceDependency,
) -> dict[str, Any]:
    """Dispatch a brief, detailed, or multimedia test notification."""
    variant = str(payload.get("type", "brief"))
    title = payload.get("title")
    body = payload.get("body")
    image_url = payload.get("image_url")

    if variant == "detailed":
        title = title or "Detailed Alert: Customer Order #1042"
        body = body or "Emeka submitted 4 items (approx N65,000). Delivery to Trade Fair Complex."
    elif variant == "multimedia":
        title = title or "Rich Media: Premium Stock Arrived"
        body = body or "Nike Air Max 90 restocked (24 pairs). Tap to view catalog entry."
        image_url = image_url or "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=600"
    else:
        title = title or "Test Notification"
        body = body or "Push notifications are working properly on this device!"

    delivered = await service.dispatch_test_push(
        tenant_id=tenant_context.tenant_id,
        user_id=tenant_context.user_id,
        title=str(title),
        body=str(body),
        image_url=str(image_url) if image_url else None,
    )
    return {
        "status": "ok",
        "delivered_endpoints": delivered,
        "variant": variant,
        "title": title,
        "body": body,
    }
