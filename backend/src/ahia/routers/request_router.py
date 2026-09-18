"""Lists: what a customer sends, and what the trader sees.

Two routers, because they are two different worlds. The public one has no session, no permissions
and
answers only that a list arrived. The versioned one belongs to a business and is reachable only with
a
role that may see sales.
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from ahia.core.tenant_context import TenantContext
from ahia.routers.tenant_router import require_tenant_context
from ahia.schemas.request_schema import (
    PublicRequestAcceptedSchema,
    PublicRequestSchema,
    RequestResponseSchema,
)
from ahia.services.request_service import RequestService

_TENANT_SCOPE_PREFIX: Final[str] = "/tenants/{tenant_id}"

public_router = APIRouter(tags=["public lists"])
router = APIRouter(prefix=_TENANT_SCOPE_PREFIX, tags=["lists"])


def get_request_service(request: Request) -> RequestService:
    """Return the list service for this request."""
    service: RequestService = request.app.state.container.request_service
    return service


RequestServiceDependency = Annotated[RequestService, Depends(get_request_service)]
TenantContextDependency = Annotated[TenantContext, Depends(require_tenant_context)]


@public_router.post(
    "/shop/{tenant_slug}/requests",
    response_model=PublicRequestAcceptedSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Send a list to a shop",
)
async def submit_public_list(
    tenant_slug: str,
    payload: PublicRequestSchema,
    service: RequestServiceDependency,
) -> PublicRequestAcceptedSchema:
    """Take a customer's list. No account, and no answer about the shop's own affairs.

    The response says the list arrived and how many lines it has. It does not say whether anything
    is in
    stock, what anything costs the shop, or whether this customer has ordered before - none of which
    is a
    customer's business, and the first of which the product owner settled explicitly: an Igbo trader
    is
    never truly out of stock, he goes and finds it.
    """
    request, line_count = await service.submit_customer_list(
        tenant_slug=tenant_slug,
        payload=payload,
    )
    return PublicRequestAcceptedSchema(
        request_id=request.id,
        line_count=line_count,
        message="Your list has reached the shop. They will get back to you on this number.",
    )


@router.get(
    "/requests",
    response_model=list[RequestResponseSchema],
    summary="Lists customers have sent this business",
)
async def list_requests(
    tenant_context: TenantContextDependency,
    service: RequestServiceDependency,
) -> list[RequestResponseSchema]:
    """Return this business's lists, newest first, with their lines."""
    requests = await service.list_requests(tenant_context)
    return [await service.as_response(tenant_context, request=request) for request in requests]


@router.get(
    "/requests/{request_id}",
    response_model=RequestResponseSchema,
    summary="One list, with its lines",
)
async def read_request(
    request_id: UUID,
    tenant_context: TenantContextDependency,
    service: RequestServiceDependency,
) -> RequestResponseSchema:
    """Return one list, or refuse as if it did not exist."""
    return await service.read_request(tenant_context, request_id=request_id)
