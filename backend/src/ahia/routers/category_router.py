"""HTTP transport for categories.

Tenant-scoped routes, like every other business resource: the identifier in the path
is resolved to an authorized context, so a category from another business is answered
as a missing category.

Four routes, and every one of them does three things: parse the request, call one
service method, shape the response. There is no permission check here, no lookup, and
no database call - a check in the transport can be bypassed by a CLI command or a
scheduled job calling the same use case, so the service owns it.
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from ahia.core.tenant_context import TenantContext
from ahia.routers.tenant_router import require_tenant_context
from ahia.schemas.category_schema import (
    CategoryCreateSchema,
    CategoryResponseSchema,
    CategoryUpdateSchema,
)
from ahia.services.category_service import CategoryService

_TENANT_SCOPE_PREFIX: Final[str] = "/tenants/{tenant_id}"

router = APIRouter(prefix=_TENANT_SCOPE_PREFIX, tags=["categories"])


def get_category_service(request: Request) -> CategoryService:
    """Return the category service for this request."""
    service: CategoryService = request.app.state.container.category_service
    return service


CategoryServiceDependency = Annotated[CategoryService, Depends(get_category_service)]
TenantContextDependency = Annotated[TenantContext, Depends(require_tenant_context)]


@router.post(
    "/categories",
    response_model=CategoryResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Add a category to this business",
)
async def create_category(
    payload: CategoryCreateSchema,
    tenant_context: TenantContextDependency,
    service: CategoryServiceDependency,
) -> CategoryResponseSchema:
    """Create a category. The slug is derived from the name, never sent."""
    category = await service.create_category(
        tenant_context,
        name=payload.name,
        description=payload.description,
        parent_id=payload.parent_id,
        default_normal_price=payload.default_normal_price,
        default_wholesale_price=payload.default_wholesale_price,
        default_pieces_per_pack=payload.default_pieces_per_pack,
    )
    return CategoryResponseSchema.from_entity(category)


@router.get(
    "/categories",
    response_model=list[CategoryResponseSchema],
    summary="List this business's categories",
)
async def list_categories(
    tenant_context: TenantContextDependency,
    service: CategoryServiceDependency,
) -> list[CategoryResponseSchema]:
    """Return every category in the business, ordered by name."""
    categories = await service.list_categories(tenant_context)
    return [CategoryResponseSchema.from_entity(category) for category in categories]


@router.get(
    "/categories/{category_id}",
    response_model=CategoryResponseSchema,
    summary="Read one category",
)
async def get_category(
    category_id: UUID,
    tenant_context: TenantContextDependency,
    service: CategoryServiceDependency,
) -> CategoryResponseSchema:
    """Return one category. A category in another business is a 404, not a 403."""
    category = await service.get_category(tenant_context, category_id=category_id)
    return CategoryResponseSchema.from_entity(category)


@router.patch(
    "/categories/{category_id}",
    response_model=CategoryResponseSchema,
    summary="Rename a category or change its description",
)
async def update_category(
    category_id: UUID,
    payload: CategoryUpdateSchema,
    tenant_context: TenantContextDependency,
    service: CategoryServiceDependency,
) -> CategoryResponseSchema:
    """Apply a partial edit. The slug is not editable, and a null description clears it."""
    category = await service.update_category(
        tenant_context,
        category_id=category_id,
        changes=payload.to_entity_changes(),
    )
    return CategoryResponseSchema.from_entity(category)


@router.delete(
    "/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a category with confirmation safeguards",
)
async def delete_category(
    category_id: UUID,
    tenant_context: TenantContextDependency,
    service: CategoryServiceDependency,
    strategy: Annotated[str, Query(description="move_up, cascade, or restrict")] = "move_up",
) -> None:
    """Delete a category using the chosen content safeguard strategy."""
    await service.delete_category(tenant_context, category_id=category_id, strategy=strategy)
