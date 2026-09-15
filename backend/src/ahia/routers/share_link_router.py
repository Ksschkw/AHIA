"""HTTP transport for share links: minting them, revoking them, and opening one.

Two routers, for the same reason the storefront has two.

`public_router` is unversioned and requires no identity
    `/share/{token}` is a link a business sends in a message. The token is the authorization, the
    version prefix would make the address change when the API contract does, and the middleware
    classifies the path into the public read bucket so it carries its own rate limit.

`router` is versioned and tenant-scoped
    Minting a link for an invoice, listing the links one invoice has been shared through, and
    revoking one. The permission to share is the resource's own read permission, checked in the
    service: somebody who may not read a sale may not publish it to the internet.

The token is returned once and never again
    `POST .../share` responds with the token; every other response about links has no field for it,
    because the server stores only a digest. A business that loses the link mints a new one, which
    is also the only safe answer: a system that can re-show a link is a system that kept it.

Every refusal on the public path is the same not-found
    An unknown token, a revoked link, an expired link and a deleted sale are one answer. The
    difference is logged for an operator and withheld from the holder, because saying "that link
    was revoked" confirms that the token was once real.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from ahia.core.tenant_context import TenantContext
from ahia.routers.tenant_router import require_tenant_context
from ahia.schemas.share_link_schema import (
    IssuedShareLinkResponseSchema,
    SharedInvoiceSchema,
    ShareLinkCreateSchema,
    ShareLinkResponseSchema,
)
from ahia.services.share_link_service import ShareLinkService

_TENANT_SCOPE_PREFIX: Final[str] = "/tenants/{tenant_id}"

#: The business's own management of its links.
router = APIRouter(prefix=_TENANT_SCOPE_PREFIX, tags=["share links"])

#: The link a customer opens. Unversioned, like every public address in this product.
public_router = APIRouter(tags=["shared invoice"])


def get_share_link_service(request: Request) -> ShareLinkService:
    """Return the share link service for this request."""
    service: ShareLinkService = request.app.state.container.share_link_service
    return service


ShareLinkServiceDependency = Annotated[ShareLinkService, Depends(get_share_link_service)]
TenantContextDependency = Annotated[TenantContext, Depends(require_tenant_context)]


@router.post(
    "/sales/{sale_id}/share",
    response_model=IssuedShareLinkResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Share an invoice through a link",
)
async def share_invoice(
    sale_id: UUID,
    payload: ShareLinkCreateSchema,
    tenant_context: TenantContextDependency,
    service: ShareLinkServiceDependency,
) -> IssuedShareLinkResponseSchema:
    """Mint a link that opens one sale as an invoice.

    The token in this response is the only copy: it is not stored, not logged and not recoverable.
    """
    issued = await service.share_invoice(
        tenant_context,
        sale_id=sale_id,
        lifetime=timedelta(days=payload.lifetime_days),
    )
    return IssuedShareLinkResponseSchema(
        link=ShareLinkResponseSchema.from_entity(issued.link, is_open=True),
        token=issued.token,
        public_path=issued.public_path,
    )


@router.get(
    "/sales/{sale_id}/share-links",
    response_model=list[ShareLinkResponseSchema],
    summary="The links an invoice has been shared through",
)
async def list_share_links(
    sale_id: UUID,
    tenant_context: TenantContextDependency,
    service: ShareLinkServiceDependency,
) -> list[ShareLinkResponseSchema]:
    """Return the links, so a business can see what is open and revoke what it did not mean."""
    links = await service.list_links_for_invoice(tenant_context, sale_id=sale_id)
    return [
        ShareLinkResponseSchema.from_entity(link, is_open=service.is_open(link)) for link in links
    ]


@router.post(
    "/share-links/{share_link_id}/revoke",
    response_model=ShareLinkResponseSchema,
    summary="Stop a link from opening anything",
)
async def revoke_share_link(
    share_link_id: UUID,
    tenant_context: TenantContextDependency,
    service: ShareLinkServiceDependency,
) -> ShareLinkResponseSchema:
    """Revoke a link permanently.

    Idempotent: revoking twice keeps the first moment, because that is when the link stopped
    working.
    """
    link = await service.revoke_share_link(tenant_context, share_link_id=share_link_id)
    return ShareLinkResponseSchema.from_entity(link, is_open=False)


@public_router.get(
    "/share/{token}",
    response_model=SharedInvoiceSchema,
    summary="Open an invoice through a shared link",
)
async def read_shared_invoice(
    token: str,
    service: ShareLinkServiceDependency,
) -> SharedInvoiceSchema:
    """Return the invoice a token opens, for a caller with no account and no token of their own."""
    invoice = await service.read_shared_invoice(token=token)
    return SharedInvoiceSchema.from_projection(invoice)
