"""HTTP transport for product images.

**The upload takes the raw request body, not a multipart form.** A browser sends a file
this way with `fetch(url, {method: "POST", body: file})`, which sets the content type
from the file itself; multipart would exist to carry a filename and a field name, and
neither is used - the object key is built from server-side identifiers, so a client's
filename never reaches storage. Taking the raw body also avoids a dependency
(`python-multipart`) that would exist only to unpack a form nobody needs.

The body is read with a hard ceiling as it arrives, not after it has been buffered: a
client that streams a gigabyte must be stopped while it streams, not once the server has
already put it in memory. The limit that matters is the configured upload ceiling; the
media pipeline applies its own, narrower, image limit afterwards.

The declared content type comes from the request header and is treated as a claim. The
media pipeline compares it with the format it decodes, and refuses the upload when they
disagree - a client can lie about a header, so the bytes are the evidence.

Every handler parses, calls one service method and shapes the response. Authorization,
tenant resolution and every business rule live in the service.
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from ahia.core.errors import InvalidMediaError
from ahia.core.tenant_context import TenantContext
from ahia.routers.tenant_router import require_tenant_context
from ahia.schemas.product_image_schema import (
    ProductImageOrderSchema,
    ProductImageReconciliationResponseSchema,
    ProductImageRemovalResponseSchema,
    ProductImageResponseSchema,
)
from ahia.services.product_image_service import ProductImageService

_TENANT_SCOPE_PREFIX: Final[str] = "/tenants/{tenant_id}"

router = APIRouter(prefix=_TENANT_SCOPE_PREFIX, tags=["product images"])


def get_product_image_service(request: Request) -> ProductImageService:
    """Return the product image service for this request."""
    service: ProductImageService = request.app.state.container.product_image_service
    return service


ProductImageServiceDependency = Annotated[ProductImageService, Depends(get_product_image_service)]
TenantContextDependency = Annotated[TenantContext, Depends(require_tenant_context)]


async def read_body_within_limit(request: Request, *, limit_bytes: int) -> bytes:
    """Read the request body, refusing anything larger than the ceiling.

    Streamed rather than buffered: a body that is already too large is stopped while it
    arrives, so a client cannot make the server hold a gigabyte before deciding it is
    unacceptable.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit_bytes:
            raise InvalidMediaError(
                operation="read_upload",
                entity="product_image",
                detail=f"the uploaded file exceeds {limit_bytes} bytes",
            )
        chunks.append(chunk)

    content = b"".join(chunks)
    if not content:
        raise InvalidMediaError(
            operation="read_upload",
            entity="product_image",
            detail="the request body was empty",
        )
    return content


def declared_content_type(request: Request) -> str:
    """Return the media type the client declared, without its parameters.

    `image/png; charset=binary` is a content type with a parameter the pipeline has no
    use for; comparing the whole header against an allowlist would reject valid uploads
    for a reason that has nothing to do with the picture.
    """
    header = request.headers.get("content-type", "")
    return header.split(";", 1)[0].strip().lower()


@router.post(
    "/products/{product_id}/images",
    response_model=ProductImageResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Attach an image to a product",
)
async def attach_product_image(
    product_id: UUID,
    request: Request,
    tenant_context: TenantContextDependency,
    service: ProductImageServiceDependency,
    is_primary: Annotated[bool, Query(description="Make this the product's cover.")] = False,
) -> ProductImageResponseSchema:
    """Upload one image as the raw request body.

    The body's content type is a claim; the pipeline decodes the bytes and refuses the
    upload if the two disagree.
    """
    settings = request.app.state.settings
    content = await read_body_within_limit(
        request, limit_bytes=settings.storage_limits().max_upload_bytes
    )
    image = await service.attach_image(
        tenant_context,
        product_id=product_id,
        content=content,
        declared_content_type=declared_content_type(request),
        is_primary=is_primary,
    )
    return ProductImageResponseSchema.from_entity(
        image, delivery_url=await service.build_delivery_url(image)
    )


@router.get(
    "/products/{product_id}/images",
    response_model=list[ProductImageResponseSchema],
    summary="List a product's images",
)
async def list_product_images(
    product_id: UUID,
    tenant_context: TenantContextDependency,
    service: ProductImageServiceDependency,
) -> list[ProductImageResponseSchema]:
    """Return the gallery in the order the business arranged it."""
    images = await service.list_images(tenant_context, product_id=product_id)
    return [
        ProductImageResponseSchema.from_entity(
            image, delivery_url=await service.build_delivery_url(image)
        )
        for image in images
    ]


@router.post(
    "/products/{product_id}/images/{image_id}/primary",
    response_model=ProductImageResponseSchema,
    summary="Make an image the product's cover",
)
async def set_primary_product_image(
    product_id: UUID,
    image_id: UUID,
    tenant_context: TenantContextDependency,
    service: ProductImageServiceDependency,
) -> ProductImageResponseSchema:
    """Promote one image, demoting whatever held the cover."""
    image = await service.set_primary_image(
        tenant_context, product_id=product_id, image_id=image_id
    )
    return ProductImageResponseSchema.from_entity(
        image, delivery_url=await service.build_delivery_url(image)
    )


@router.put(
    "/products/{product_id}/images/order",
    response_model=list[ProductImageResponseSchema],
    summary="Arrange a product's gallery",
)
async def reorder_product_images(
    product_id: UUID,
    payload: ProductImageOrderSchema,
    tenant_context: TenantContextDependency,
    service: ProductImageServiceDependency,
) -> list[ProductImageResponseSchema]:
    """Apply a complete gallery order.

    The whole order is required: a partial one leaves the images it does not mention in
    an ambiguous position, and two clients dragging pictures at once would interleave
    into an order neither asked for.
    """
    images = await service.reorder_images(
        tenant_context, product_id=product_id, image_ids=payload.image_ids
    )
    return [
        ProductImageResponseSchema.from_entity(
            image, delivery_url=await service.build_delivery_url(image)
        )
        for image in images
    ]


@router.delete(
    "/products/{product_id}/images/{image_id}",
    response_model=ProductImageRemovalResponseSchema,
    summary="Remove an image from a product",
)
async def remove_product_image(
    product_id: UUID,
    image_id: UUID,
    tenant_context: TenantContextDependency,
    service: ProductImageServiceDependency,
) -> ProductImageRemovalResponseSchema:
    """Delete the stored object, release its bytes, and drop the row.

    A provider delete that fails is reported rather than hidden: the response says the
    storage was not released, and the image stays marked for reconciliation.
    """
    removal = await service.remove_image(tenant_context, product_id=product_id, image_id=image_id)
    return ProductImageRemovalResponseSchema(
        image_id=removal.image_id,
        storage_released=removal.storage_released,
        reconciliation_required=removal.reconciliation_required,
        released_bytes=removal.released_bytes,
    )


@router.post(
    "/product-images/reconcile",
    response_model=ProductImageReconciliationResponseSchema,
    summary="Retry image deletions the provider refused",
)
async def reconcile_product_images(
    tenant_context: TenantContextDependency,
    service: ProductImageServiceDependency,
) -> ProductImageReconciliationResponseSchema:
    """Retry deletions this business left pending, releasing the bytes that now go.

    An operator runs this after a provider incident. It is idempotent: a pass over a
    business with nothing pending does nothing and reports zeroes.
    """
    report = await service.reconcile_pending_deletions(tenant_context)
    return ProductImageReconciliationResponseSchema(
        attempted=report.attempted,
        released=report.released,
        still_pending=report.still_pending,
    )
