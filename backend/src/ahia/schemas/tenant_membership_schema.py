"""Transport contracts for staff administration.

Two flows share this module because they are two halves of one act: an owner
issues an invitation, and the invited person accepts it. Keeping them together
means the fields that must line up - the identity, the role and the token - are
described in one place.

The role is validated against the registry rather than accepted as a string, so an
unknown role is a 422 at the edge instead of a membership that silently grants
nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator

from ahia.core.permissions.permissions_registry import SYSTEM_ROLES
from ahia.models.entities.membership_invitation_model import MembershipInvitationModel
from ahia.models.entities.tenant_membership_model import MembershipStatus, TenantMembershipModel

InvitedEmail = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=3, max_length=254)
]
InvitedPhone = Annotated[str, StringConstraints(strip_whitespace=True, min_length=7, max_length=20)]
InvitationToken = Annotated[str, StringConstraints(min_length=16, max_length=512)]

#: Roles an owner may hand out through an invitation. OWNER is excluded: elevating
#: somebody to owner is not a routine onboarding step, and it is the role that can
#: close the business.
INVITABLE_ROLES: Final[tuple[str, ...]] = ("MANAGER", "SALES", "INVENTORY")


def _validate_role(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in SYSTEM_ROLES:
        raise ValueError("unknown role")
    return normalized


class MembershipInviteSchema(BaseModel):
    """An invitation to join a business."""

    model_config = ConfigDict(extra="forbid")

    role_name: str
    email: InvitedEmail | None = None
    phone: InvitedPhone | None = None

    @field_validator("role_name")
    @classmethod
    def _check_role(cls, value: str) -> str:
        return _validate_role(value)

    @model_validator(mode="after")
    def _check_invitable(self) -> MembershipInviteSchema:
        if self.email is None and self.phone is None:
            raise ValueError("an email address or a phone number is required")
        if self.role_name not in INVITABLE_ROLES:
            raise ValueError("that role cannot be granted through an invitation")
        return self

    def to_invited_identity(self) -> dict[str, str | None]:
        return {"email": self.email, "phone": self.phone}


class MembershipRoleUpdateSchema(BaseModel):
    """A role change for an existing member."""

    model_config = ConfigDict(extra="forbid")

    role_name: str

    @field_validator("role_name")
    @classmethod
    def _check_role(cls, value: str) -> str:
        return _validate_role(value)


class MembershipStatusUpdateSchema(BaseModel):
    """A status change for an existing member.

    Only the two states an administrative action can reach are accepted: returning
    somebody to active, or suspending them. Removal is a DELETE, and an invitation
    is not a status a person can be moved back to.
    """

    model_config = ConfigDict(extra="forbid")

    status: MembershipStatus

    @field_validator("status")
    @classmethod
    def _check_status(cls, value: MembershipStatus) -> MembershipStatus:
        allowed = {MembershipStatus.ACTIVE, MembershipStatus.SUSPENDED}
        if value not in allowed:
            raise ValueError("status must be active or suspended")
        return value


class MembershipResponseSchema(BaseModel):
    """One member of a business."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    user_id: UUID
    role_name: str
    status: MembershipStatus
    full_name: str
    email: str | None
    phone: str | None
    invited_at: datetime | None
    joined_at: datetime | None
    created_at: datetime

    @classmethod
    def from_membership(
        cls,
        membership: TenantMembershipModel,
        *,
        full_name: str,
        email: str | None,
        phone: str | None,
    ) -> MembershipResponseSchema:
        return cls(
            id=membership.id,
            user_id=membership.user_id,
            role_name=membership.role_name,
            status=membership.status,
            full_name=full_name,
            email=email,
            phone=phone,
            invited_at=membership.invited_at,
            joined_at=membership.joined_at,
            created_at=membership.created_at,
        )


class InvitationResponseSchema(BaseModel):
    """An invitation as an owner sees it.

    `token` is present only in the response that creates the invitation. The
    digest is what is stored, so this is the single moment the value exists in a
    response, and the owner is expected to pass it on through whatever channel they
    already use to talk to that worker.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    role_name: str
    email: str | None
    phone: str | None
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    token: str | None = None

    @classmethod
    def from_invitation(
        cls,
        invitation: MembershipInvitationModel,
        *,
        token: str | None = None,
    ) -> InvitationResponseSchema:
        return cls(
            id=invitation.id,
            tenant_id=invitation.tenant_id,
            role_name=invitation.role_name,
            email=invitation.invited_email,
            phone=invitation.invited_phone,
            expires_at=invitation.expires_at,
            accepted_at=invitation.accepted_at,
            revoked_at=invitation.revoked_at,
            created_at=invitation.created_at,
            token=token,
        )


class PendingInvitationSchema(BaseModel):
    """An invitation as the invited person sees it.

    Names the business and the role and nothing more: the invitee has not joined
    yet, so they are not entitled to the business's details until they accept.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    tenant_name: str
    role_name: str
    expires_at: datetime


class AcceptInvitationSchema(BaseModel):
    """Accepting an invitation."""

    model_config = ConfigDict(extra="forbid")

    token: InvitationToken


class AcceptedInvitationSchema(BaseModel):
    """The result of accepting, so the client can navigate straight to the business."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    tenant_name: str
    tenant_slug: str
    role_name: str
    membership_id: UUID
