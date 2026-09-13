"""HTTP transport for devices.

Tenant-scoped routes, like every other business resource: the identifier in the
path is resolved to an authorized context, so a device from another business is
answered as a missing device.

The register route doubles as the heartbeat. A client presents the same identity on
every launch, and the service decides whether that identity is new, known or
refused; asking a client to know which is asking it to track server state.
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from ahia.core.tenant_context import TenantContext
from ahia.routers.tenant_router import require_tenant_context
from ahia.schemas.device_schema import (
    DeviceRegisterSchema,
    DeviceResponseSchema,
    DeviceRevocationResponseSchema,
)
from ahia.services.device_service import DeviceService

_TENANT_SCOPE_PREFIX: Final[str] = "/tenants/{tenant_id}"

router = APIRouter(prefix=_TENANT_SCOPE_PREFIX, tags=["devices"])


def get_device_service(request: Request) -> DeviceService:
    """Return the device service for this request."""
    service: DeviceService = request.app.state.container.device_service
    return service


DeviceServiceDependency = Annotated[DeviceService, Depends(get_device_service)]
TenantContextDependency = Annotated[TenantContext, Depends(require_tenant_context)]


@router.post(
    "/devices",
    response_model=DeviceResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Register this installation, or renew a known one",
)
async def register_device(
    payload: DeviceRegisterSchema,
    tenant_context: TenantContextDependency,
    service: DeviceServiceDependency,
) -> DeviceResponseSchema:
    """Register or renew. No permission is required: a person's phone is theirs."""
    device = await service.register_or_touch_device(
        tenant_context,
        device_identifier=payload.device_identifier,
        platform=payload.platform,
        device_name=payload.device_name,
        app_version=payload.app_version,
    )
    return DeviceResponseSchema.from_entity(device)


@router.get(
    "/devices",
    response_model=list[DeviceResponseSchema],
    summary="List the devices that have accessed this business",
)
async def list_devices(
    tenant_context: TenantContextDependency,
    service: DeviceServiceDependency,
) -> list[DeviceResponseSchema]:
    """Return every device. Reading the business's device list needs devices.read."""
    devices = await service.list_devices(tenant_context)
    return [DeviceResponseSchema.from_entity(device) for device in devices]


@router.get(
    "/devices/mine",
    response_model=list[DeviceResponseSchema],
    summary="List the caller's own devices",
)
async def list_own_devices(
    tenant_context: TenantContextDependency,
    service: DeviceServiceDependency,
) -> list[DeviceResponseSchema]:
    """Return the caller's own installations. No permission is needed for your own."""
    devices = await service.list_own_devices(tenant_context)
    return [DeviceResponseSchema.from_entity(device) for device in devices]


@router.delete(
    "/devices/{device_id}",
    response_model=DeviceRevocationResponseSchema,
    summary="Revoke a device and end its sessions",
)
async def revoke_device(
    device_id: UUID,
    tenant_context: TenantContextDependency,
    service: DeviceServiceDependency,
) -> DeviceRevocationResponseSchema:
    """Revoke a device.

    Revoking your own needs no permission; revoking somebody else's needs
    devices.revoke.
    """
    device, sessions_ended = await service.revoke_device(tenant_context, device_id=device_id)
    return DeviceRevocationResponseSchema(
        device=DeviceResponseSchema.from_entity(device),
        sessions_ended=sessions_ended,
    )
