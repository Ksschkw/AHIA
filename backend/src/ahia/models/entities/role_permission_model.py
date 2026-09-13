"""The role-permission link.

A join entity rather than a list on the role, because it is queried from both
directions: which permissions a role grants, and which roles grant a permission.
The second question is what an operator asks when deciding whether revoking a
capability is safe.

The pair is unique. A duplicated link would make "how many roles grant this" wrong
and would let a role appear twice in a list of who can do something.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ahia.core.errors import EntityInvariantError


@dataclass(frozen=True, slots=True)
class RolePermissionModel:
    """One permission granted to one role."""

    role_id: UUID
    permission_id: UUID

    def __post_init__(self) -> None:
        if self.role_id == self.permission_id:
            # Not a security boundary, but a join whose two sides are the same
            # identifier means something upstream confused a role for a permission.
            raise EntityInvariantError(
                operation="build_role_permission",
                entity="role_permission",
                identifier=str(self.role_id),
                detail="a role and a permission cannot share an identifier",
            )

    def describe_for_audit(self) -> dict[str, str]:
        return {"role_id": str(self.role_id), "permission_id": str(self.permission_id)}
