"""Staff and membership permissions.

Removing a member and changing a role are the operations that decide who can do
what, so they are granted narrowly and audited. The last owner cannot be removed
or demoted; that rule lives in the service, not here.
"""

from __future__ import annotations

from typing import Final

from ahia.core.permissions.permission_types import PermissionDefinition

STAFF_READ: Final[str] = "staff.read"
STAFF_INVITE: Final[str] = "staff.invite"
STAFF_UPDATE: Final[str] = "staff.update"
STAFF_REMOVE: Final[str] = "staff.remove"

PERMISSIONS: Final[tuple[PermissionDefinition, ...]] = (
    PermissionDefinition(
        code=STAFF_READ,
        module="staff",
        description="View the staff list, their roles and their membership status",
    ),
    PermissionDefinition(
        code=STAFF_INVITE,
        module="staff",
        description="Invite a worker to the business with a role",
    ),
    PermissionDefinition(
        code=STAFF_UPDATE,
        module="staff",
        description="Change a member's role, permissions or membership status",
    ),
    PermissionDefinition(
        code=STAFF_REMOVE,
        module="staff",
        description="Remove a member's access to the business",
    ),
)
