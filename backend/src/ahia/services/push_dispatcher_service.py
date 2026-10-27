"""Push notification dispatcher service for Web Push and Mobile Push.

Dispatches outbound push notifications to registered browser endpoints and
Expo / mobile device tokens asynchronously. Cleans up stale / expired tokens
when push gateways report unregistered endpoints (404/410/DeviceNotRegistered).
"""

# Audit exemption: token cleanup is operational; notifications carry their own audit record

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Final
from uuid import UUID

import httpx
from sqlalchemy.exc import SQLAlchemyError

from ahia.core.database import UnitOfWork
from ahia.core.logging import StructuredLogger, get_logger
from ahia.crud import push_subscription_crud, tenant_crud

_LOGGER_NAME: Final[str] = "ahia.services.push_dispatcher"
_EXPO_PUSH_URL: Final[str] = "https://exp.host/--/api/v2/push/send"


class PushDispatcherService:
    """Outbound push dispatcher for browser Web Push and native mobile notifications."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._logger = (logger or get_logger(_LOGGER_NAME)).bind(
            component="push_dispatcher", layer="service"
        )

    async def register_subscription(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        platform: str,
        endpoint: str,
        p256dh: str | None = None,
        auth: str | None = None,
    ) -> None:
        """Register or renew a push token or browser subscription."""
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            await push_subscription_crud.upsert(
                unit_of_work.session_handle,
                tenant_id=tenant_id,
                user_id=user_id,
                platform=platform,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
            )
            await unit_of_work.commit()

        self._logger.info(
            "push_subscription_registered",
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            platform=platform,
        )

    def _resolve_target_url(
        self,
        *,
        tenant_id: UUID,
        entity_type: str | None,
        entity_id: UUID | None,
    ) -> str:
        if entity_type == "customer_list" and entity_id:
            return f"/app/lists?business={tenant_id}&list={entity_id}"
        if entity_type == "product" and entity_id:
            return f"/app/items?business={tenant_id}&product={entity_id}"
        if entity_type == "sale" and entity_id:
            return f"/app/sales?business={tenant_id}&sale={entity_id}"
        return f"/app/more?business={tenant_id}"

    async def _send_expo(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        payload: dict[str, object],
    ) -> bool:
        try:
            res = await client.post(_EXPO_PUSH_URL, json=payload)
            if res.status_code == 200:
                data = res.json()
                details = data.get("data", {}).get("details", {})
                if details.get("error") == "DeviceNotRegistered":
                    await self._cleanup_endpoint(endpoint)
                    return False
                return True
            if res.status_code in {400, 404, 410}:
                await self._cleanup_endpoint(endpoint)
            return False
        except httpx.HTTPError as err:
            self._logger.warning("expo_push_failed", endpoint=endpoint[:30], error=str(err))
            return False

    async def _send_web(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        content_bytes: bytes,
    ) -> bool:
        headers = {"TTL": "86400", "Urgency": "high"}
        try:
            res = await client.post(endpoint, headers=headers, content=content_bytes)
            if res.status_code in {200, 201, 202}:
                return True
            if res.status_code in {404, 410}:
                await self._cleanup_endpoint(endpoint)
            return False
        except httpx.HTTPError as err:
            self._logger.warning("web_push_failed", endpoint=endpoint[:30], error=str(err))
            return False

    async def dispatch_to_user(
        self,
        *,
        tenant_id: UUID,
        recipient_user_id: UUID,
        title: str,
        body: str,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        image_url: str | None = None,
    ) -> int:
        """Send a push notification to all registered endpoints of a recipient."""
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            tenant = await tenant_crud.get_by_id(unit_of_work.session_handle, tenant_id)
            tenant_name = tenant.name if tenant else "AHIA"
            subscriptions = await push_subscription_crud.list_for_recipient(
                unit_of_work.session_handle,
                tenant_id=tenant_id,
                user_id=recipient_user_id,
            )
            endpoints = [sub.endpoint.strip() for sub in subscriptions]

        if not endpoints:
            return 0

        display_title = title
        if not title.startswith(f"[{tenant_name}]") and not title.startswith(f"{tenant_name}:"):
            display_title = f"[{tenant_name}] {title}"

        target_url = self._resolve_target_url(
            tenant_id=tenant_id, entity_type=entity_type, entity_id=entity_id
        )
        delivered = 0

        async with httpx.AsyncClient(timeout=10.0) as client:
            for endpoint in endpoints:
                is_expo = endpoint.startswith("ExponentPushToken[") or endpoint.startswith(
                    "ExpoPushToken["
                )
                if is_expo:
                    expo_payload: dict[str, object] = {
                        "to": endpoint,
                        "title": display_title,
                        "body": body,
                        "sound": "default",
                        "priority": "high",
                        "channelId": f"stall-{tenant_id}",
                        "categoryId": "business_alerts",
                        "data": {
                            "tenant_id": str(tenant_id),
                            "tenant_name": tenant_name,
                            "entity_type": entity_type,
                            "entity_id": str(entity_id) if entity_id else None,
                            "url": target_url,
                        },
                    }
                    if image_url:
                        expo_payload["attachments"] = [{"url": image_url}]
                    if await self._send_expo(client, endpoint, expo_payload):
                        delivered += 1
                elif endpoint.startswith("http://") or endpoint.startswith("https://"):
                    web_payload = json.dumps(
                        {
                            "title": display_title,
                            "body": body,
                            "icon": "/icon-192.png",
                            "badge": "/icon-192.png",
                            "image": image_url,
                            "tag": f"ahia-{tenant_id}",
                            "data": {
                                "url": target_url,
                                "tenant_id": str(tenant_id),
                                "tenant_name": tenant_name,
                                "entity_type": entity_type,
                                "entity_id": str(entity_id) if entity_id else None,
                            },
                        }
                    ).encode("utf-8")
                    if await self._send_web(client, endpoint, web_payload):
                        delivered += 1

        return delivered

    async def _cleanup_endpoint(self, endpoint: str) -> None:
        try:
            unit_of_work = self._unit_of_work_factory()
            async with unit_of_work:
                await push_subscription_crud.delete_by_endpoint(
                    unit_of_work.session_handle,
                    endpoint=endpoint,
                )
                await unit_of_work.commit()
        except (SQLAlchemyError, httpx.HTTPError) as cleanup_err:
            self._logger.warning(
                "cleanup_endpoint_error", endpoint=endpoint[:30], error=str(cleanup_err)
            )
