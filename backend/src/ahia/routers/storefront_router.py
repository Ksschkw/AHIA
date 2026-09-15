"""HTTP transport for the storefront: the business's own management, and the public shop.

Two routers in one file, and the split is the point.

`public_router` is unversioned and requires no identity
    `/shop/{tenant_slug}` and `/shop/{tenant_slug}/product/{product_slug}` are addresses a business
    prints on a poster, and a link a customer holds must keep working while the API contract
    evolves. That is why they carry no version prefix - the same reason the health endpoints do -
    and why they are declared separately from the management routes rather than sharing a prefix
    that would have to be excluded from authentication.

`router` is versioned and tenant-scoped, like every other business route
    Reading your own shop, opening it, editing what it says and closing it again. Authorization is
    the service's, where a CLI or a scheduled job gets the same answer as an HTTP request.

The public routes are the only place this product answers without an identity
    Everywhere else an anonymous caller is refused. Here the answer is a projection built from an
    allowlist in the service, the shop must be published, and the path is rate limited into its own
    bucket by the middleware - a tighter limit than the global one, because a shop page is cheap to
    serve and easy to scrape. Nothing about the response depends on who is asking, so there is
    nothing an identity would add.

A refused public read is the same not-found for every reason
    No such business, a business that was deactivated, a shop that never opened, a shop that was
    withdrawn, a product that is not published: one answer, so a stranger cannot enumerate which
    businesses exist by comparing them.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request

from ahia.core.tenant_context import TenantContext
from ahia.routers.tenant_router import require_tenant_context
from ahia.schemas.storefront_schema import (
    PublicProductPageSchema,
    PublicSlug,
    PublicStorefrontSchema,
    StorefrontPublishSchema,
    StorefrontResponseSchema,
    StorefrontUpdateSchema,
)
from ahia.services.storefront_service import StorefrontService

_TENANT_SCOPE_PREFIX: Final[str] = "/tenants/{tenant_id}"

#: The business's own view, under the versioned prefix like every other business route.
router = APIRouter(prefix=_TENANT_SCOPE_PREFIX, tags=["storefront"])

#: The shop a customer sees. Unversioned: a printed link must not carry a version.
public_router = APIRouter(tags=["public storefront"])


def get_storefront_service(request: Request) -> StorefrontService:
    """Return the storefront service for this request."""
    service: StorefrontService = request.app.state.container.storefront_service
    return service


StorefrontServiceDependency = Annotated[StorefrontService, Depends(get_storefront_service)]
TenantContextDependency = Annotated[TenantContext, Depends(require_tenant_context)]


# ---------------------------------------------------------------------------
# The business's own shop
# ---------------------------------------------------------------------------


@router.get(
    "/storefront",
    response_model=StorefrontResponseSchema,
    summary="Read this business's shop",
)
async def get_storefront(
    tenant_context: TenantContextDependency,
    service: StorefrontServiceDependency,
) -> StorefrontResponseSchema:
    """Return the shop, closed and empty if the business never opened one.

    A shop that does not exist yet is not a 404: it is a shop that is closed, which is the state
    every business starts in and the state a screen has to be able to render.
    """
    storefront = await service.get_storefront(tenant_context)
    return StorefrontResponseSchema.from_entity(storefront)


@router.post(
    "/storefront/publish",
    response_model=StorefrontResponseSchema,
    summary="Open the shop at its public address",
)
async def publish_storefront(
    payload: StorefrontPublishSchema,
    tenant_context: TenantContextDependency,
    service: StorefrontServiceDependency,
) -> StorefrontResponseSchema:
    """Publish the shop, with what it says about itself.

    Idempotent: publishing an open shop keeps the moment it first opened.
    """
    storefront = await service.publish_storefront(
        tenant_context,
        headline=payload.headline,
        description=payload.description,
        contact_phone=payload.contact_phone,
    )
    return StorefrontResponseSchema.from_entity(storefront)


@router.post(
    "/storefront/unpublish",
    response_model=StorefrontResponseSchema,
    summary="Close the shop, keeping its address",
)
async def unpublish_storefront(
    tenant_context: TenantContextDependency,
    service: StorefrontServiceDependency,
) -> StorefrontResponseSchema:
    """Withdraw the shop from the public internet without losing the address it was given."""
    storefront = await service.unpublish_storefront(tenant_context)
    return StorefrontResponseSchema.from_entity(storefront)


@router.patch(
    "/storefront",
    response_model=StorefrontResponseSchema,
    summary="Edit what the shop says about itself",
)
async def update_storefront(
    payload: StorefrontUpdateSchema,
    tenant_context: TenantContextDependency,
    service: StorefrontServiceDependency,
) -> StorefrontResponseSchema:
    """Apply a partial edit. Whether the shop is open is a different call, not a field here."""
    storefront = await service.update_storefront(tenant_context, changes=payload.to_changes())
    return StorefrontResponseSchema.from_entity(storefront)


# ---------------------------------------------------------------------------
# The shop a customer sees
# ---------------------------------------------------------------------------


@public_router.get(
    "/shop/{tenant_slug}",
    response_model=PublicStorefrontSchema,
    summary="A business's public shop and its catalogue",
)
async def read_public_storefront(
    tenant_slug: PublicSlug,
    service: StorefrontServiceDependency,
) -> PublicStorefrontSchema:
    """Return a published shop, for a caller with no account and no token."""
    storefront = await service.read_public_storefront(tenant_slug=tenant_slug)
    return PublicStorefrontSchema.from_projection(storefront)


@public_router.get(
    "/shop/{tenant_slug}/product/{product_slug}",
    response_model=PublicProductPageSchema,
    summary="One product of a public shop",
)
async def read_public_product(
    tenant_slug: PublicSlug,
    product_slug: PublicSlug,
    service: StorefrontServiceDependency,
) -> PublicProductPageSchema:
    """Return one published product of a published shop, for a caller with no account.

    Declared after the shop route and with a longer path, so the shop page is matched exactly and
    a product address cannot be confused with a business address.
    """
    storefront = await service.read_public_storefront(tenant_slug=tenant_slug)
    product = await service.read_public_product(tenant_slug=tenant_slug, product_slug=product_slug)
    return PublicProductPageSchema.from_projection(storefront=storefront, product=product)
