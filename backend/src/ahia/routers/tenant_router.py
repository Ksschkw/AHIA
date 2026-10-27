"""HTTP transport for the tenant slice.

Handlers parse, call one service method and return a schema. The interesting part
is the dependency: `require_tenant_context` resolves the authorized context for the
business named in the path, which is what makes every tenant-scoped route denial
by default. A caller with no membership receives the same 404 a stranger receives
for a business that does not exist.

Tenant context resolution lives in the service, not here, so a scheduled job or a
CLI command obtains the same proof by calling the same method.
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel

from ahia.core.authentication import Principal
from ahia.core.ports.storage_port import StorageCategory, StorageObjectKey, StorageUploadRequest
from ahia.core.tenant_context import TenantContext
from ahia.routers.upload_support import extract_upload_content_and_type
from ahia.routers.user_router import require_principal
from ahia.schemas.tenant_schema import (
    TenantCreateSchema,
    TenantResponseSchema,
    TenantStockPolicyUpdateSchema,
    TenantSummarySchema,
    TenantUpdateSchema,
)
from ahia.services.tenant_service import TenantService

_TENANT_ROUTER_PREFIX: Final[str] = "/tenants"

router = APIRouter(prefix=_TENANT_ROUTER_PREFIX, tags=["tenants"])


def get_tenant_service(request: Request) -> TenantService:
    """Return the tenant service for this request."""
    service: TenantService = request.app.state.container.tenant_service
    return service


TenantServiceDependency = Annotated[TenantService, Depends(get_tenant_service)]
PrincipalDependency = Annotated[Principal, Depends(require_principal)]


async def require_tenant_context(
    tenant_id: UUID,
    principal: PrincipalDependency,
    service: TenantServiceDependency,
) -> TenantContext:
    """Resolve the caller's authorized context for the business in the path.

    The identifier in the path is a selection hint. Membership is the proof, and
    the service is the only place that decides.

    Resolving also binds the Row-Level Security scope for the rest of the request,
    as a side effect inside the service. A route therefore cannot be authorized
    for one business and query the database as another, or as nobody.
    """
    return await service.resolve_tenant_context(
        principal,
        requested_tenant_id=tenant_id,
    )


TenantContextDependency = Annotated[TenantContext, Depends(require_tenant_context)]


@router.post(
    "",
    response_model=TenantResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create a business and become its owner",
)
async def create_tenant(
    payload: TenantCreateSchema,
    principal: PrincipalDependency,
    service: TenantServiceDependency,
) -> TenantResponseSchema:
    """Create a business.

    No permission is required beyond being authenticated: starting a business is
    how a person acquires their first permission.
    """
    tenant = await service.create_tenant(
        principal,
        name=payload.name,
        requested_slug=payload.slug,
        business_type=payload.business_type,
        phone=payload.phone,
        email=payload.email,
        address=payload.address,
        city=payload.city,
        state=payload.state,
        country=payload.country,
        currency=payload.currency,
        timezone=payload.timezone,
    )
    return TenantResponseSchema.from_entity(tenant)


@router.get(
    "",
    response_model=list[TenantSummarySchema],
    summary="List the businesses the caller may reach",
)
async def list_tenants(
    principal: PrincipalDependency,
    service: TenantServiceDependency,
) -> list[TenantSummarySchema]:
    """List the caller's businesses, with their role in each."""
    views = await service.list_own_tenants(principal)
    return [
        TenantSummarySchema.from_membership(view.tenant, role_name=view.role_name) for view in views
    ]


@router.get(
    "/{tenant_id}",
    response_model=TenantResponseSchema,
    summary="Read a business",
)
async def read_tenant(
    tenant_context: TenantContextDependency,
    service: TenantServiceDependency,
) -> TenantResponseSchema:
    """Return the business the caller is authorized for."""
    tenant = await service.get_tenant(tenant_context)
    return TenantResponseSchema.from_entity(tenant)


@router.patch(
    "/{tenant_id}",
    response_model=TenantResponseSchema,
    summary="Update a business profile",
)
async def update_tenant(
    payload: TenantUpdateSchema,
    tenant_context: TenantContextDependency,
    service: TenantServiceDependency,
) -> TenantResponseSchema:
    """Apply a partial update. The public slug is not editable."""
    tenant = await service.update_tenant_profile(
        tenant_context,
        changes=payload.to_entity_changes(),
    )
    return TenantResponseSchema.from_entity(tenant)


@router.put(
    "/{tenant_id}/stock-policy",
    response_model=TenantResponseSchema,
    summary="Change what happens when stock would go negative",
)
async def update_stock_policy(
    payload: TenantStockPolicyUpdateSchema,
    tenant_context: TenantContextDependency,
    service: TenantServiceDependency,
) -> TenantResponseSchema:
    """Set the business's negative-stock policy.

    Its own operation rather than a profile field: allowing negative stock changes what
    every stock number in the business means.
    """
    tenant = await service.update_negative_stock_policy(tenant_context, policy=payload.policy)
    return TenantResponseSchema.from_entity(tenant)


class TenantMediaUploadResponseSchema(BaseModel):
    url: str
    delivery_url: str
    size_bytes: int
    asset_type: str


@router.post(
    "/{tenant_id}/media/upload",
    response_model=TenantMediaUploadResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an image asset for the tenant (logo, banner, category, etc.)",
)
async def upload_tenant_media(
    tenant_id: UUID,
    request: Request,
    tenant_context: TenantContextDependency,
    asset_type: Annotated[
        str, Query(description="The asset category: logo, banner, category, general")
    ] = "general",
) -> TenantMediaUploadResponseSchema:
    """Upload any image asset to storage under the business scope.

    Normalizes the image to WebP, verifies quota limits, and returns the public delivery URL.
    """
    settings = request.app.state.settings
    media = request.app.state.container.media
    storage = request.app.state.container.storage
    quota_service = request.app.state.container.storage_quota_service

    content, content_type = await extract_upload_content_and_type(
        request, limit_bytes=settings.storage_limits().max_upload_bytes
    )

    optimized = await media.optimize(
        content=content,
        declared_content_type=content_type,
        maximum_size_bytes=settings.storage_limits().max_image_bytes,
    )

    reservation = await quota_service.reserve(
        tenant_context,
        incoming_bytes=optimized.size_bytes,
        operation="tenant_media_upload",
    )

    safe_asset_type = asset_type if asset_type in ("logo", "banner", "category") else "general"
    random_suffix = uuid4().hex[:12]
    key = StorageObjectKey(
        tenant_id=str(tenant_context.tenant_id),
        category=StorageCategory.STOREFRONT,
        resource_id=safe_asset_type,
        filename=f"{random_suffix}.webp",
    )

    try:
        stored = await storage.upload(
            StorageUploadRequest(
                key=key.value,
                content=optimized.content,
                mime_type=optimized.mime_type,
                tenant_id=str(tenant_context.tenant_id),
                filename=key.filename,
            )
        )
        delivery_url = stored.delivery_url or await storage.build_delivery_url(
            key=key.value, is_public=True
        )
        await quota_service.commit_reservation(
            reservation,
            operation="tenant_media_upload",
        )
    except Exception:
        await quota_service.release_reservation(
            reservation,
            reason="upload_failed",
            operation="tenant_media_upload",
        )
        raise

    return TenantMediaUploadResponseSchema(
        url=delivery_url,
        delivery_url=delivery_url,
        size_bytes=optimized.size_bytes,
        asset_type=safe_asset_type,
    )


@router.delete(
    "/{tenant_id}",
    response_model=TenantResponseSchema,
    summary="Close a business",
)
async def deactivate_tenant(
    tenant_context: TenantContextDependency,
    service: TenantServiceDependency,
) -> TenantResponseSchema:
    """Close the business. Deactivation, never deletion."""
    tenant = await service.deactivate_tenant(tenant_context)
    return TenantResponseSchema.from_entity(tenant)
