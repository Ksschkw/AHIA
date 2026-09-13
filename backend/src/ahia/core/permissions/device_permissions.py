"""Device permissions.

A device never grants permission; it is an identity for synchronization, audit
and security. These permissions control who may see the device list and who may
revoke a device's access.
"""

from __future__ import annotations

from typing import Final

from ahia.core.permissions.permission_types import PermissionDefinition

DEVICES_READ: Final[str] = "devices.read"
DEVICES_REVOKE: Final[str] = "devices.revoke"

PERMISSIONS: Final[tuple[PermissionDefinition, ...]] = (
    PermissionDefinition(
        code=DEVICES_READ,
        module="devices",
        description="View the devices that have accessed the business",
    ),
    PermissionDefinition(
        code=DEVICES_REVOKE,
        module="devices",
        description="Revoke a device, ending its synchronization and session access",
    ),
)
