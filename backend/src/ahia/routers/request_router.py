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
    CustomerListSummarySchema,
    DispatchSchema,
    PublicListSchema,
    PublicRequestAcceptedSchema,
    PublicRequestSchema,
    RequestLineWorkSchema,
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
    request, line_count, list_token = await service.submit_customer_list(
        tenant_slug=tenant_slug,
        payload=payload,
    )
    return PublicRequestAcceptedSchema(
        request_id=request.id,
        line_count=line_count,
        message="Your list has reached the shop. They will get back to you on this number.",
        # The customer's own address for the list. They need it because they will close the page,
        # and
        # the trader needs it because it is the same list he works from.
        list_path=f"/list/{tenant_slug}/{list_token}",
    )


@public_router.get(
    "/shop/{tenant_slug}/requests/{list_token}",
    response_model=PublicListSchema,
    summary="A customer's own list, at its own address",
)
async def read_public_list(
    tenant_slug: str,
    list_token: str,
    service: RequestServiceDependency,
) -> PublicListSchema:
    """Return the list a token names. The token is the whole of the authority, as a share link's
    is."""
    return await service.read_public_list(list_token=list_token)


@public_router.get(
    "/shop/{tenant_slug}/customer-lists",
    response_model=list[CustomerListSummarySchema],
    summary="Lists a customer has previously sent to this shop",
)
async def list_customer_history(
    tenant_slug: str,
    phone: str,
    service: RequestServiceDependency,
) -> list[CustomerListSummarySchema]:
    """Return recent lists from this phone number to this shop, with lines for one-tap reuse."""
    return await service.list_customer_history(tenant_slug=tenant_slug, customer_phone=phone)


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


@router.patch(
    "/requests/{request_id}/lines/{line_id}",
    response_model=RequestResponseSchema,
    summary="Record what was done with one line of a list",
)
async def work_request_line(
    request_id: UUID,
    line_id: UUID,
    payload: RequestLineWorkSchema,
    tenant_context: TenantContextDependency,
    service: RequestServiceDependency,
) -> RequestResponseSchema:
    """Say where the item came from, what it cost, and what the customer pays for it."""
    return await service.work_line(
        tenant_context,
        request_id=request_id,
        line_id=line_id,
        changes=payload,
    )


@router.post(
    "/requests/{request_id}/dispatch",
    response_model=RequestResponseSchema,
    summary="Record how a list was sent",
)
async def dispatch_request(
    request_id: UUID,
    payload: DispatchSchema,
    tenant_context: TenantContextDependency,
    service: RequestServiceDependency,
) -> RequestResponseSchema:
    """Write down the transporter, the waybill number, the cost, and where to follow it."""
    return await service.dispatch_request(tenant_context, request_id=request_id, payload=payload)


@router.post(
    "/requests/{request_id}/confirm",
    response_model=RequestResponseSchema,
    summary="Turn a list into a sale",
)
async def confirm_request(
    request_id: UUID,
    tenant_context: TenantContextDependency,
    service: RequestServiceDependency,
) -> RequestResponseSchema:
    """Confirm the list. Refused while any line is unpriced, because a total with holes is not a
    deal."""
    return await service.confirm_request(tenant_context, request_id=request_id)
