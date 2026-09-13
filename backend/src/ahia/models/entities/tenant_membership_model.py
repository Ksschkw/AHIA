"""The tenant membership entity: one person's access to one business.

A user is an identity; a membership is what gives that identity access to a
particular business. The distinction is the whole multi-tenancy model: the same
person can be an owner here and a salesperson there, and deactivating one
membership must not touch the other.

Decisions worth stating.

The role is a name, not a permission list
    A membership carries a system role name, validated against the registry in
    `core.permissions`. Permissions are derived from that role rather than stored
    per membership, so changing what a role means changes it for everyone holding
    it, and no membership can drift into a bespoke permission set nobody can
    audit. Tenant-defined custom roles arrive in M6 with a `role_id`; the system
    role name stays the source of truth for the roles the product promises.

One membership per person per business
    Enforced by a unique constraint rather than by a check, because two
    memberships for one person in one business means two answers to "what may this
    person do".

Status is the lifecycle, and only one status grants access
    An invitation that was never accepted is not access. A suspension is a
    deliberate act. A removal is recorded rather than deleted, because the person's
    sales and audit events still reference them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from ahia.core.errors import EntityInvariantError
from ahia.core.permissions.permissions_registry import SYSTEM_ROLES


class MembershipStatus(StrEnum):
    """The lifecycle of one person's access to one business."""

    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REMOVED = "removed"

    @property
    def grants_access(self) -> bool:
        """Return True only for an active membership.

        Every other state denies. Written as a property on the vocabulary rather
        than a condition at each call site, so there is one place where the rule
        lives and no way to spell it differently.
        """
        return self is MembershipStatus.ACTIVE

    @property
    def is_terminal(self) -> bool:
        """Return True when the membership cannot be revived by an ordinary action."""
        return self is MembershipStatus.REMOVED


#: Statuses a membership may move to from a given status. Declared as data so the
#: allowed lifecycle is readable in one place, and an illegal transition is a
#: typed failure rather than a state nobody expected.
ALLOWED_TRANSITIONS: dict[MembershipStatus, frozenset[MembershipStatus]] = {
    MembershipStatus.INVITED: frozenset({MembershipStatus.ACTIVE, MembershipStatus.REMOVED}),
    MembershipStatus.ACTIVE: frozenset(
        {MembershipStatus.SUSPENDED, MembershipStatus.REMOVED, MembershipStatus.ACTIVE}
    ),
    MembershipStatus.SUSPENDED: frozenset({MembershipStatus.ACTIVE, MembershipStatus.REMOVED}),
    MembershipStatus.REMOVED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class TenantMembershipModel:
    """A person's access to one business."""

    id: UUID
    tenant_id: UUID
    user_id: UUID
    role_name: str
    status: MembershipStatus
    created_at: datetime
    updated_at: datetime
    invited_at: datetime | None = None
    joined_at: datetime | None = None
    removed_at: datetime | None = None
    invited_by_user_id: UUID | None = None

    def __post_init__(self) -> None:
        _require_aware(self.created_at, field_name="created_at", membership_id=self.id)
        _require_aware(self.updated_at, field_name="updated_at", membership_id=self.id)

        if self.updated_at < self.created_at:
            raise EntityInvariantError(
                operation="build_membership",
                entity="tenant_membership",
                identifier=str(self.id),
                detail="updated_at is earlier than created_at",
            )

        normalized_role = self.role_name.strip().upper()
        if normalized_role not in SYSTEM_ROLES:
            # An unknown role would resolve to no permissions, which denies
            # everything and looks like a bug rather than a misconfiguration.
            raise EntityInvariantError(
                operation="build_membership",
                entity="tenant_membership",
                identifier=str(self.id),
                detail=f"unknown role: {self.role_name}",
            )
        if normalized_role != self.role_name:
            # The entity is frozen, so a corrected role is applied by the factory
            # rather than by mutating here.
            raise EntityInvariantError(
                operation="build_membership",
                entity="tenant_membership",
                identifier=str(self.id),
                detail="role_name must be an uppercase system role name",
            )

        if self.status is MembershipStatus.ACTIVE and self.joined_at is None:
            raise EntityInvariantError(
                operation="build_membership",
                entity="tenant_membership",
                identifier=str(self.id),
                detail="an active membership must record when the person joined",
            )
        if self.status is MembershipStatus.REMOVED and self.removed_at is None:
            raise EntityInvariantError(
                operation="build_membership",
                entity="tenant_membership",
                identifier=str(self.id),
                detail="a removed membership must record when it ended",
            )
        if self.status is not MembershipStatus.REMOVED and self.removed_at is not None:
            raise EntityInvariantError(
                operation="build_membership",
                entity="tenant_membership",
                identifier=str(self.id),
                detail="removed_at is set on a membership that is not removed",
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def invite(
        cls,
        *,
        membership_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
        role_name: str,
        now: datetime,
        invited_by_user_id: UUID | None = None,
    ) -> TenantMembershipModel:
        """Create an invitation, which grants nothing until it is accepted."""
        return cls(
            id=membership_id,
            tenant_id=tenant_id,
            user_id=user_id,
            role_name=role_name.strip().upper(),
            status=MembershipStatus.INVITED,
            invited_at=now,
            invited_by_user_id=invited_by_user_id,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def activate_immediately(
        cls,
        *,
        membership_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
        role_name: str,
        now: datetime,
    ) -> TenantMembershipModel:
        """Create an already-active membership.

        Used for the owner created with the business: the person creating it has
        already proven who they are, and an invitation to themselves would be
        theatre.
        """
        return cls(
            id=membership_id,
            tenant_id=tenant_id,
            user_id=user_id,
            role_name=role_name.strip().upper(),
            status=MembershipStatus.ACTIVE,
            invited_at=now,
            joined_at=now,
            created_at=now,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    @property
    def grants_access(self) -> bool:
        """Return True only when this membership gives the person access."""
        return self.status.grants_access

    @property
    def permission_codes(self) -> frozenset[str]:
        """Return the permissions this membership confers.

        Resolved from the role registry rather than stored, so a change to what a
        role means applies to everyone holding it.
        """
        return SYSTEM_ROLES[self.role_name].permissions

    @property
    def is_owner(self) -> bool:
        """Return True when this membership is the business owner.

        Used for the last-owner rule, which is the one place the product names a
        role directly: removing the final owner would leave a business nobody can
        administer.
        """
        return self.role_name == "OWNER"

    def describe_for_audit(self) -> dict[str, str]:
        """Return the fields an audit record needs, with no personal data."""
        return {
            "membership_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "user_id": str(self.user_id),
            "role_name": self.role_name,
            "status": self.status.value,
        }

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def _transition(
        self,
        to_status: MembershipStatus,
        *,
        at: datetime,
        **changes: object,
    ) -> TenantMembershipModel:
        """Return the membership moved to a new status, or refuse the move."""
        if to_status not in ALLOWED_TRANSITIONS[self.status]:
            raise EntityInvariantError(
                operation="transition_membership",
                entity="tenant_membership",
                identifier=str(self.id),
                detail=f"cannot move from {self.status.value} to {to_status.value}",
            )
        return replace(self, status=to_status, updated_at=at, **changes)  # type: ignore[arg-type]

    def activate(self, *, at: datetime) -> TenantMembershipModel:
        """Return the membership activated, recording the join if it is the first."""
        joined_at = self.joined_at if self.joined_at is not None else at
        return self._transition(MembershipStatus.ACTIVE, at=at, joined_at=joined_at)

    def suspend(self, *, at: datetime) -> TenantMembershipModel:
        """Return the membership suspended.

        A suspension keeps the person in the business and takes their access away,
        which is what an owner does while something is being looked into.
        """
        return self._transition(MembershipStatus.SUSPENDED, at=at)

    def remove(self, *, at: datetime) -> TenantMembershipModel:
        """Return the membership removed, recording when.

        Removal is terminal by ordinary means: reinstating the same membership
        would silently restore whatever access it had before, so a returning
        worker is invited again and the history shows two memberships.
        """
        return self._transition(MembershipStatus.REMOVED, at=at, removed_at=at)

    def change_role(self, *, role_name: str, at: datetime) -> TenantMembershipModel:
        """Return the membership with a different role."""
        normalized = role_name.strip().upper()
        if normalized not in SYSTEM_ROLES:
            raise EntityInvariantError(
                operation="change_membership_role",
                entity="tenant_membership",
                identifier=str(self.id),
                detail=f"unknown role: {role_name}",
            )
        if self.status is MembershipStatus.REMOVED:
            raise EntityInvariantError(
                operation="change_membership_role",
                entity="tenant_membership",
                identifier=str(self.id),
                detail="a removed membership cannot be given a role",
            )
        return replace(self, role_name=normalized, updated_at=at)


def _require_aware(moment: datetime, *, field_name: str, membership_id: UUID) -> None:
    """Reject a naive timestamp, as every entity in this codebase does."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="build_membership",
            entity="tenant_membership",
            identifier=str(membership_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
