"""The membership invitation entity.

An owner adds a worker by inviting an identity, not by creating an account for
them. The invitation is the durable record of that intent: who was invited, by
whom, to do what, until when, and whether it was taken up.

Why an invitation is separate from a membership
    A worker may not have an account yet. Creating a user row for somebody who has
    not signed up would put a person in the identity table who never agreed to be
    there, and it would give the owner a way to invent accounts. The invitation
    holds the *identity* that was invited; the membership is created when that
    identity accepts.

Why the identity is stored in two nullable columns rather than one
    An invitation is addressed to an email address or a phone number. Keeping them
    separate means acceptance can match on the exact channel that was used: a
    person whose invitation went to a phone number cannot accept it from an email
    account that happens to share a name.

Why the token is stored as a digest
    The token is the authorization to join a business. Storing only its digest
    means a database disclosure does not let somebody walk into a business.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from ahia.core.errors import EntityInvariantError
from ahia.core.permissions.permissions_registry import SYSTEM_ROLES


@dataclass(frozen=True, slots=True)
class MembershipInvitationModel:
    """One pending invitation for one identity to join one business."""

    id: UUID
    tenant_id: UUID
    role_name: str
    token_hash: str
    expires_at: datetime
    created_at: datetime
    created_by_user_id: UUID
    invited_email: str | None = None
    invited_phone: str | None = None
    accepted_at: datetime | None = None
    accepted_by_user_id: UUID | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_aware(self.created_at, field_name="created_at", invitation_id=self.id)
        _require_aware(self.expires_at, field_name="expires_at", invitation_id=self.id)

        if self.expires_at <= self.created_at:
            raise EntityInvariantError(
                operation="build_invitation",
                entity="membership_invitation",
                identifier=str(self.id),
                detail="expires_at is not later than created_at",
            )

        if self.invited_email is None and self.invited_phone is None:
            raise EntityInvariantError(
                operation="build_invitation",
                entity="membership_invitation",
                identifier=str(self.id),
                detail="an invitation needs an email address or a phone number to address",
            )

        if not self.token_hash.strip():
            raise EntityInvariantError(
                operation="build_invitation",
                entity="membership_invitation",
                identifier=str(self.id),
                detail="token_hash is empty",
            )

        normalized_role = self.role_name.strip().upper()
        if normalized_role not in SYSTEM_ROLES:
            raise EntityInvariantError(
                operation="build_invitation",
                entity="membership_invitation",
                identifier=str(self.id),
                detail=f"unknown role: {self.role_name}",
            )

        if self.accepted_at is not None and self.accepted_at < self.created_at:
            raise EntityInvariantError(
                operation="build_invitation",
                entity="membership_invitation",
                identifier=str(self.id),
                detail="accepted_at is earlier than created_at",
            )
        if self.revoked_at is not None and self.accepted_at is not None:
            raise EntityInvariantError(
                operation="build_invitation",
                entity="membership_invitation",
                identifier=str(self.id),
                detail="an invitation cannot be both accepted and revoked",
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def issue(
        cls,
        *,
        invitation_id: UUID,
        tenant_id: UUID,
        role_name: str,
        token_hash: str,
        expires_at: datetime,
        created_at: datetime,
        created_by_user_id: UUID,
        invited_email: str | None = None,
        invited_phone: str | None = None,
    ) -> MembershipInvitationModel:
        return cls(
            id=invitation_id,
            tenant_id=tenant_id,
            role_name=role_name.strip().upper(),
            token_hash=token_hash,
            expires_at=expires_at,
            created_at=created_at,
            created_by_user_id=created_by_user_id,
            invited_email=invited_email,
            invited_phone=invited_phone,
        )

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def is_expired(self, *, at: datetime) -> bool:
        return at >= self.expires_at

    def is_accepted(self) -> bool:
        return self.accepted_at is not None

    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_pending(self, *, at: datetime) -> bool:
        """Return True while the invitation can still be taken up."""
        return not self.is_accepted() and not self.is_revoked() and not self.is_expired(at=at)

    def addresses(self, *, email: str | None, phone: str | None) -> bool:
        """Return True when the invitation was addressed to this identity.

        Matched on the exact channel that was used: an invitation sent to a phone
        number cannot be accepted from an email account, even one whose address
        looks similar.
        """
        if self.invited_email is not None and email is not None:
            return self.invited_email == email
        if self.invited_phone is not None and phone is not None:
            return self.invited_phone == phone
        return False

    def describe_for_audit(self) -> dict[str, str]:
        """Return identifiers only: the invited address is personal data."""
        return {
            "invitation_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "role_name": self.role_name,
            "invited_by_user_id": str(self.created_by_user_id),
        }

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def accept(self, *, user_id: UUID, at: datetime) -> MembershipInvitationModel:
        """Return the invitation accepted by a user."""
        if self.is_accepted():
            raise EntityInvariantError(
                operation="accept_invitation",
                entity="membership_invitation",
                identifier=str(self.id),
                detail="the invitation was already accepted",
            )
        if self.is_revoked():
            raise EntityInvariantError(
                operation="accept_invitation",
                entity="membership_invitation",
                identifier=str(self.id),
                detail="the invitation was revoked",
            )
        if self.is_expired(at=at):
            raise EntityInvariantError(
                operation="accept_invitation",
                entity="membership_invitation",
                identifier=str(self.id),
                detail="the invitation has expired",
            )
        return replace(self, accepted_at=at, accepted_by_user_id=user_id)

    def revoke(self, *, at: datetime) -> MembershipInvitationModel:
        """Return the invitation withdrawn, as an owner does when they change their mind."""
        if self.is_accepted():
            raise EntityInvariantError(
                operation="revoke_invitation",
                entity="membership_invitation",
                identifier=str(self.id),
                detail="an accepted invitation cannot be revoked; remove the membership instead",
            )
        return replace(self, revoked_at=at)


def _require_aware(moment: datetime, *, field_name: str, invitation_id: UUID) -> None:
    """Reject a naive timestamp, as every entity in this codebase does."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="build_invitation",
            entity="membership_invitation",
            identifier=str(invitation_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
