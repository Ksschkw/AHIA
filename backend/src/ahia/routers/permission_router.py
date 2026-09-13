"""HTTP transport for roles and permissions.

Every route is tenant-scoped, because roles are: a business sees the system roles
plus its own, and the tenant identifier in the path is resolved to an authorized
context exactly as it is for any other tenant-scoped route. Two routers share the
`/tenants/{tenant_id}` prefix rather than inventing a second addressing scheme for
the same resource.

Role administration lives in `permission_service` rather than in a service of its
own, because a role *is* a bundle of permissions: splitting them would put the
escalation rule in one file and the grant it protects in another.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request, status

from ahia.core.tenant_context import TenantContext
from ahia.routers.tenant_router import require_tenant_context
from ahia.schemas.permission_schema import (
    CustomRoleCreateSchema,
    PermissionResponseSchema,
    RolePermissionsUpdateSchema,
    RoleResponseSchema,
    build_role_response,
)
from ahia.services.permission_service import PermissionService

_TENANT_SCOPE_PREFIX: Final[str] = "/tenants/{tenant_id}"

router = APIRouter(prefix=_TENANT_SCOPE_PREFIX, tags=["iam"])


def get_permission_service(request: Request) -> PermissionService:
    """Return the permission service for this request."""
    service: PermissionService = request.app.state.container.permission_service
    return service


PermissionServiceDependency = Annotated[PermissionService, Depends(get_permission_service)]
TenantContextDependency = Annotated[TenantContext, Depends(require_tenant_context)]


@router.get(
    "/permissions",
    response_model=list[PermissionResponseSchema],
    summary="List every capability this deployment has",
)
async def list_permissions(
    tenant_context: TenantContextDependency,
    service: PermissionServiceDependency,
) -> list[PermissionResponseSchema]:
    """Return the catalogue. Reference data, readable by any active member."""
    permissions = await service.list_permissions(tenant_context)
    return [PermissionResponseSchema.from_entity(permission) for permission in permissions]


@router.get(
    "/roles",
    response_model=list[RoleResponseSchema],
    summary="List the roles available to this business",
)
async def list_roles(
    tenant_context: TenantContextDependency,
    service: PermissionServiceDependency,
) -> list[RoleResponseSchema]:
    """Return the system roles and this business's own."""
    views = await service.list_roles(tenant_context)
    return [
        build_role_response(view.role, permission_codes=view.permission_codes) for view in views
    ]


@router.post(
    "/roles",
    response_model=RoleResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create a role for this business",
)
async def create_custom_role(
    payload: CustomRoleCreateSchema,
    tenant_context: TenantContextDependency,
    service: PermissionServiceDependency,
) -> RoleResponseSchema:
    """Create a role. A caller cannot grant what they do not hold."""
    view = await service.create_custom_role(
        tenant_context,
        name=payload.name,
        description=payload.description,
        permission_codes=payload.permission_codes,
    )
    return build_role_response(view.role, permission_codes=view.permission_codes)


@router.patch(
    "/roles/{role_name}/permissions",
    response_model=RoleResponseSchema,
    summary="Replace the permissions of one of this business's roles",
)
async def update_role_permissions(
    role_name: str,
    payload: RolePermissionsUpdateSchema,
    tenant_context: TenantContextDependency,
    service: PermissionServiceDependency,
) -> RoleResponseSchema:
    """Replace the set. A system role is refused: it is provisioned from code."""
    view = await service.update_role_permissions(
        tenant_context,
        role_name=role_name,
        permission_codes=payload.permission_codes,
    )
    return build_role_response(view.role, permission_codes=view.permission_codes)
