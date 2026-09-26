"""HTTP transport for products.

Tenant-scoped routes, like every other business resource: the identifier in the path is
resolved to an authorized context, so a product from another business is answered as a
missing product.

Publication has its own endpoints rather than a boolean on the update contract.
Publishing is a decision with a consequence - a customer can now see and share this -
and it issues a public address. A `PATCH {"is_published": true}` would hide that inside
a profile edit, and it would leave "why did this product appear on the storefront" to be
answered by reading a diff.

Every handler here parses, calls one service method and shapes the response. There is no
permission check, no lookup and no database call: a check in transport can be bypassed
by a CLI command or a scheduled job calling the same use case, so the service owns it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from ahia.core.tenant_context import TenantContext
from ahia.routers.tenant_router import require_tenant_context
from ahia.schemas.product_schema import (
    PriceForResponse,
    ProductCopySchema,
    ProductCreateSchema,
    ProductForResponse,
    ProductMoveBatchSchema,
    ProductResponseSchema,
    ProductUpdateSchema,
)
from ahia.services.product_service import ProductService

_TENANT_SCOPE_PREFIX: Final[str] = "/tenants/{tenant_id}"

router = APIRouter(prefix=_TENANT_SCOPE_PREFIX, tags=["products"])


def get_product_service(request: Request) -> ProductService:
    """Return the product service for this request."""
    service: ProductService = request.app.state.container.product_service
    return service


ProductServiceDependency = Annotated[ProductService, Depends(get_product_service)]
TenantContextDependency = Annotated[TenantContext, Depends(require_tenant_context)]


def _shape(product: ProductForResponse, price: PriceForResponse) -> ProductResponseSchema:
    """Shape one product and the price that applies to it.

    Pure, and typed structurally on both halves: the price is resolved by the service - it needs the
    item's group, which is the service layer's business - and this layer's only job is to arrange
    what it was given. Nothing here names a domain entity, which is the line the architecture
    contract draws."""
    return ProductResponseSchema.from_entity(product, price)


def _shape_all(
    products: Sequence[ProductForResponse],
    prices: Mapping[UUID, PriceForResponse],
) -> list[ProductResponseSchema]:
    """Shape a catalogue whose prices were resolved in one pass."""
    return [ProductResponseSchema.from_entity(product, prices[product.id]) for product in products]


@router.post(
    "/products",
    response_model=ProductResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Add a product to this business's catalogue",
)
async def create_product(
    payload: ProductCreateSchema,
    tenant_context: TenantContextDependency,
    service: ProductServiceDependency,
) -> ProductResponseSchema:
    """Create a product. It starts active and unpublished."""
    product = await service.create_product(
        tenant_context,
        name=payload.name,
        selling_price=payload.selling_price,
        category_id=payload.category_id,
        description=payload.description,
        sku=payload.sku,
        barcode=payload.barcode,
        cost_price=payload.cost_price,
        wholesale_price=payload.wholesale_price,
        pieces_per_pack=payload.pieces_per_pack,
        low_stock_threshold=payload.low_stock_threshold,
    )
    return _shape(product, await service.price_for(tenant_context, product))


@router.post(
    "/products/copy",
    response_model=list[ProductResponseSchema],
    status_code=status.HTTP_201_CREATED,
    summary="Copy products into another category",
)
async def copy_products(
    payload: ProductCopySchema,
    tenant_context: TenantContextDependency,
    service: ProductServiceDependency,
) -> list[ProductResponseSchema]:
    """Copy products into another category, adopting target category prices."""
    products = await service.copy_products(
        tenant_context,
        product_ids=payload.product_ids,
        target_category_id=payload.target_category_id,
    )
    prices = await service.prices_for(tenant_context, products)
    return _shape_all(products, prices)


@router.post(
    "/products/move-batch",
    response_model=list[ProductResponseSchema],
    status_code=status.HTTP_200_OK,
    summary="Move multiple products into another category",
)
async def move_products_batch(
    payload: ProductMoveBatchSchema,
    tenant_context: TenantContextDependency,
    service: ProductServiceDependency,
) -> list[ProductResponseSchema]:
    """Move multiple products into another category in one transaction."""
    products = await service.move_products(
        tenant_context,
        product_ids=payload.product_ids,
        target_category_id=payload.target_category_id,
    )
    prices = await service.prices_for(tenant_context, products)
    return _shape_all(products, prices)


@router.get(
    "/products",
    response_model=list[ProductResponseSchema],
    summary="List this business's catalogue",
)
async def list_products(
    tenant_context: TenantContextDependency,
    service: ProductServiceDependency,
    include_inactive: Annotated[
        bool,
        Query(description="Include products withdrawn from sale. Defaults to yes."),
    ] = True,
) -> list[ProductResponseSchema]:
    """Return the catalogue. Withdrawn products are included unless asked otherwise."""
    products = await service.list_products(tenant_context, include_inactive=include_inactive)
    return _shape_all(products, await service.prices_for(tenant_context, products))


@router.get(
    "/products/{product_id}",
    response_model=ProductResponseSchema,
    summary="Read one product",
)
async def get_product(
    product_id: UUID,
    tenant_context: TenantContextDependency,
    service: ProductServiceDependency,
) -> ProductResponseSchema:
    """Return one product. A product in another business is a 404, not a 403."""
    product = await service.get_product(tenant_context, product_id=product_id)
    return _shape(product, await service.price_for(tenant_context, product))


@router.patch(
    "/products/{product_id}",
    response_model=ProductResponseSchema,
    summary="Edit a product's details, prices or codes",
)
async def update_product(
    product_id: UUID,
    payload: ProductUpdateSchema,
    tenant_context: TenantContextDependency,
    service: ProductServiceDependency,
) -> ProductResponseSchema:
    """Apply a partial edit. The slug and the lifecycle are not editable here."""
    product = await service.update_product(
        tenant_context,
        product_id=product_id,
        changes=payload.to_entity_changes(),
    )
    return _shape(product, await service.price_for(tenant_context, product))


@router.post(
    "/products/{product_id}/publish",
    response_model=ProductResponseSchema,
    summary="Publish a product at a public address",
)
async def publish_product(
    product_id: UUID,
    tenant_context: TenantContextDependency,
    service: ProductServiceDependency,
) -> ProductResponseSchema:
    """Publish. Publishing twice keeps the address customers already have."""
    product = await service.publish_product(tenant_context, product_id=product_id)
    return _shape(product, await service.price_for(tenant_context, product))


@router.post(
    "/products/{product_id}/unpublish",
    response_model=ProductResponseSchema,
    summary="Withdraw a product from the storefront",
)
async def unpublish_product(
    product_id: UUID,
    tenant_context: TenantContextDependency,
    service: ProductServiceDependency,
) -> ProductResponseSchema:
    """Withdraw from the storefront. The product stays in the catalogue."""
    product = await service.unpublish_product(tenant_context, product_id=product_id)
    return _shape(product, await service.price_for(tenant_context, product))


@router.post(
    "/products/{product_id}/activate",
    response_model=ProductResponseSchema,
    summary="Return a withdrawn product to the catalogue",
)
async def activate_product(
    product_id: UUID,
    tenant_context: TenantContextDependency,
    service: ProductServiceDependency,
) -> ProductResponseSchema:
    """Return to the catalogue. It stays unpublished until it is published again."""
    product = await service.activate_product(tenant_context, product_id=product_id)
    return _shape(product, await service.price_for(tenant_context, product))


@router.delete(
    "/products/{product_id}",
    response_model=ProductResponseSchema,
    summary="Withdraw a product from sale",
)
async def deactivate_product(
    product_id: UUID,
    tenant_context: TenantContextDependency,
    service: ProductServiceDependency,
) -> ProductResponseSchema:
    """Withdraw from sale, and from the storefront with it.

    Deletion is not offered: every sale line that references this product must keep
    resolving to it.
    """
    product = await service.deactivate_product(tenant_context, product_id=product_id)
    return _shape(product, await service.price_for(tenant_context, product))
