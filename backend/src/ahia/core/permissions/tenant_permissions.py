"""Tenant permissions.

The business itself is a resource: its profile, its settings, its currency and
timezone, and whether it is open at all. These are separate capabilities from the
storefront's public presentation, because changing what a business is called and
changing what its customers see are different acts with different consequences.

Deactivation is its own permission. Closing a business takes every member's access
away and stops the storefront answering, so it is granted to the owner and to
nobody else by default.
"""

from __future__ import annotations

from typing import Final

from ahia.core.permissions.permission_types import PermissionDefinition

TENANTS_READ: Final[str] = "tenants.read"
TENANTS_MANAGE: Final[str] = "tenants.manage"
TENANTS_DEACTIVATE: Final[str] = "tenants.deactivate"

PERMISSIONS: Final[tuple[PermissionDefinition, ...]] = (
    PermissionDefinition(
        code=TENANTS_READ,
        module="tenants",
        description="View the business profile, its settings and its public link",
    ),
    PermissionDefinition(
        code=TENANTS_MANAGE,
        module="tenants",
        description="Change the business profile, currency, timezone and contact details",
    ),
    PermissionDefinition(
        code=TENANTS_DEACTIVATE,
        module="tenants",
        description="Close the business, ending access for every member",
    ),
)
