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
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from ahia.core.authentication import Principal
from ahia.core.tenant_context import TenantContext
from ahia.routers.user_router import require_principal
from ahia.schemas.tenant_schema import (
    TenantCreateSchema,
    TenantResponseSchema,
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
