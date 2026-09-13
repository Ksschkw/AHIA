"""The role entity: a named bundle of permissions.

Two kinds of role exist in this model, and the difference matters.

A **system role** is declared in `core.permissions` and provisioned into every
deployment. Its `tenant_id` is null, and its name is unique across the whole
installation, because `OWNER` must mean the same thing in every business.

A **custom role** belongs to one tenant and is invisible to every other. Its
`tenant_id` is set, and its name is unique only within that business, so two
traders may each have a role they call `SUPERVISOR` without colliding.

System roles are provisioned by the seed and never edited through the API: a role
that every business depends on is not a per-tenant resource. Custom roles are the
extension point the specification leaves open.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError

#: Role names appear in audit records and in permission checks, so they are narrow
#: on purpose: uppercase, digits and underscores.
_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")
_MAXIMUM_DESCRIPTION_LENGTH: Final[int] = 255


@dataclass(frozen=True, slots=True)
class RoleModel:
    """One role: a system role, or one business's own role."""

    id: UUID
    name: str
    description: str
    is_system_role: bool
    created_at: datetime
    updated_at: datetime
    tenant_id: UUID | None = None

    def __post_init__(self) -> None:
        _require_aware(self.created_at, field_name="created_at", role_id=self.id)
        _require_aware(self.updated_at, field_name="updated_at", role_id=self.id)

        if self.updated_at < self.created_at:
            raise EntityInvariantError(
                operation="build_role",
                entity="role",
                identifier=str(self.id),
                detail="updated_at is earlier than created_at",
            )
        if not _NAME_PATTERN.match(self.name):
            raise EntityInvariantError(
                operation="build_role",
                entity="role",
                identifier=str(self.id),
                detail=f"role name {self.name!r} must be uppercase letters, digits and underscores",
            )
        if len(self.description) > _MAXIMUM_DESCRIPTION_LENGTH:
            raise EntityInvariantError(
                operation="build_role",
                entity="role",
                identifier=str(self.id),
                detail=f"description exceeds {_MAXIMUM_DESCRIPTION_LENGTH} characters",
            )
        # The two kinds are distinguishable by construction, which is what lets the
        # uniqueness rules be expressed as two partial indexes.
        if self.is_system_role and self.tenant_id is not None:
            raise EntityInvariantError(
                operation="build_role",
                entity="role",
                identifier=str(self.id),
                detail="a system role cannot belong to a tenant",
            )
        if not self.is_system_role and self.tenant_id is None:
            raise EntityInvariantError(
                operation="build_role",
                entity="role",
                identifier=str(self.id),
                detail="a custom role must belong to a tenant",
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def system_role(
        cls,
        *,
        role_id: UUID,
        name: str,
        description: str,
        now: datetime,
    ) -> RoleModel:
        return cls(
            id=role_id,
            name=name,
            description=description,
            is_system_role=True,
            tenant_id=None,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def custom_role(
        cls,
        *,
        role_id: UUID,
        tenant_id: UUID,
        name: str,
        description: str,
        now: datetime,
    ) -> RoleModel:
        return cls(
            id=role_id,
            name=name,
            description=description,
            is_system_role=False,
            tenant_id=tenant_id,
            created_at=now,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    @property
    def is_custom(self) -> bool:
        return not self.is_system_role

    def describe_for_audit(self) -> dict[str, str]:
        description = {
            "role_id": str(self.id),
            "role_name": self.name,
            "is_system_role": "true" if self.is_system_role else "false",
        }
        if self.tenant_id is not None:
            description["tenant_id"] = str(self.tenant_id)
        return description

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def with_description(self, *, description: str, at: datetime) -> RoleModel:
        """Return the role with a new description.

        The name is immutable: it is the value membership rows reference, and a
        rename would silently change what existing members hold.
        """
        if self.is_system_role:
            raise EntityInvariantError(
                operation="update_role",
                entity="role",
                identifier=str(self.id),
                detail="a system role is provisioned from code and cannot be edited",
            )
        return replace(self, description=description, updated_at=at)


def _require_aware(moment: datetime, *, field_name: str, role_id: UUID) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="build_role",
            entity="role",
            identifier=str(role_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
