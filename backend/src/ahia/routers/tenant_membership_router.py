"""HTTP transport for staff administration.

Two routers in one module, because they are two halves of one act.

`router` is tenant-scoped: every route resolves an authorized tenant context from
the path, so a member identifier from another business is answered as a missing
membership rather than as a permission denial.

`invitation_router` is self-scoped: the person accepting an invitation has no
membership yet, so there is no tenant to resolve. Their authorization is the
invitation token plus their own identity, and it is checked in the service.
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from ahia.core.authentication import Principal
from ahia.core.tenant_context import TenantContext
from ahia.routers.tenant_router import require_tenant_context
from ahia.routers.user_router import require_principal
from ahia.schemas.tenant_membership_schema import (
    AcceptedInvitationSchema,
    AcceptInvitationSchema,
    InvitationResponseSchema,
    MembershipInviteSchema,
    MembershipResponseSchema,
    MembershipRoleUpdateSchema,
    MembershipStatusUpdateSchema,
    PendingInvitationSchema,
)
from ahia.services.tenant_membership_service import MemberView, TenantMembershipService

_TENANT_MEMBERS_PREFIX: Final[str] = "/tenants/{tenant_id}"
_INVITATION_PREFIX: Final[str] = "/invitations"

router = APIRouter(prefix=_TENANT_MEMBERS_PREFIX, tags=["staff"])
invitation_router = APIRouter(prefix=_INVITATION_PREFIX, tags=["invitations"])


def get_membership_service(request: Request) -> TenantMembershipService:
    """Return the staff service for this request."""
    service: TenantMembershipService = request.app.state.container.membership_service
    return service


MembershipServiceDependency = Annotated[TenantMembershipService, Depends(get_membership_service)]
TenantContextDependency = Annotated[TenantContext, Depends(require_tenant_context)]
PrincipalDependency = Annotated[Principal, Depends(require_principal)]


def build_member_response(view: MemberView) -> MembershipResponseSchema:
    """Serialise a member.

    The person's name and contacts come from the user entity; the role and status
    come from the membership. Both are needed to render a staff list, and neither
    layer had to learn about the other to produce it.
    """
    return MembershipResponseSchema.from_membership(
        view.membership,
        full_name=view.user.full_name,
        email=view.user.email,
        phone=view.user.phone,
    )


@router.post(
    "/members",
    response_model=InvitationResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Invite somebody to the business",
)
async def invite_member(
    payload: MembershipInviteSchema,
    tenant_context: TenantContextDependency,
    service: MembershipServiceDependency,
) -> InvitationResponseSchema:
    """Issue an invitation and return its token once."""
    invitation, token = await service.invite_member(
        tenant_context,
        role_name=payload.role_name,
        email=payload.email,
        phone=payload.phone,
    )
    return InvitationResponseSchema.from_invitation(invitation, token=token)


@router.get(
    "/members",
    response_model=list[MembershipResponseSchema],
    summary="List the members of the business",
)
async def list_members(
    tenant_context: TenantContextDependency,
    service: MembershipServiceDependency,
) -> list[MembershipResponseSchema]:
    """Return every member, including suspended and removed ones."""
    views = await service.list_members(tenant_context)
    return [build_member_response(view) for view in views]


@router.get(
    "/invitations",
    response_model=list[InvitationResponseSchema],
    summary="List the invitations the business has issued",
)
async def list_invitations(
    tenant_context: TenantContextDependency,
    service: MembershipServiceDependency,
) -> list[InvitationResponseSchema]:
    """Return every invitation, with no token: the digest is all that remains."""
    invitations = await service.list_invitations(tenant_context)
    return [InvitationResponseSchema.from_invitation(invitation) for invitation in invitations]


@router.patch(
    "/members/{membership_id}",
    response_model=MembershipResponseSchema,
    summary="Change a member's role or status",
)
async def update_member(
    membership_id: UUID,
    payload: MembershipRoleUpdateSchema | MembershipStatusUpdateSchema,
    tenant_context: TenantContextDependency,
    service: MembershipServiceDependency,
) -> MembershipResponseSchema:
    """Change a member's role, or suspend or reactivate them.

    One route with a union body rather than two routes with one field each: the
    client sends what it means to change, and the schema decides which of the two
    shapes it is.
    """
    if isinstance(payload, MembershipRoleUpdateSchema):
        membership = await service.change_member_role(
            tenant_context,
            membership_id=membership_id,
            role_name=payload.role_name,
        )
    elif payload.status.value == "active":
        membership = await service.reactivate_member(tenant_context, membership_id=membership_id)
    else:
        membership = await service.suspend_member(tenant_context, membership_id=membership_id)

    user = await service.load_member_user(tenant_context, membership.user_id)
    return MembershipResponseSchema.from_membership(
        membership,
        full_name=user.full_name if user is not None else "",
        email=user.email if user is not None else None,
        phone=user.phone if user is not None else None,
    )


@router.delete(
    "/members/{membership_id}",
    response_model=MembershipResponseSchema,
    summary="Remove a member's access",
)
async def remove_member(
    membership_id: UUID,
    tenant_context: TenantContextDependency,
    service: MembershipServiceDependency,
) -> MembershipResponseSchema:
    """Remove a member. The person and their history remain."""
    membership = await service.remove_member(tenant_context, membership_id=membership_id)
    user = await service.load_member_user(tenant_context, membership.user_id)
    return MembershipResponseSchema.from_membership(
        membership,
        full_name=user.full_name if user is not None else "",
        email=user.email if user is not None else None,
        phone=user.phone if user is not None else None,
    )


@invitation_router.get(
    "",
    response_model=list[PendingInvitationSchema],
    summary="List the invitations addressed to the caller",
)
async def list_my_invitations(
    principal: PrincipalDependency,
    service: MembershipServiceDependency,
) -> list[PendingInvitationSchema]:
    """Return what is waiting for the authenticated person."""
    views = await service.list_pending_invitations(principal)
    return [
        PendingInvitationSchema(
            id=view.invitation.id,
            tenant_id=view.tenant.id,
            tenant_name=view.tenant.name,
            role_name=view.invitation.role_name,
            expires_at=view.invitation.expires_at,
        )
        for view in views
    ]


@invitation_router.post(
    "/accept",
    response_model=AcceptedInvitationSchema,
    summary="Accept an invitation to a business",
)
async def accept_invitation(
    payload: AcceptInvitationSchema,
    principal: PrincipalDependency,
    service: MembershipServiceDependency,
) -> AcceptedInvitationSchema:
    """Join the business the invitation names."""
    membership, tenant = await service.accept_invitation(principal, token=payload.token)
    return AcceptedInvitationSchema(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        tenant_slug=tenant.slug,
        role_name=membership.role_name,
        membership_id=membership.id,
    )
