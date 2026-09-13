"""Storefront permissions.

`storefront.read` covers the trader's own view of the storefront and its public
URL. `storefront.manage` covers branding, configuration and publishing. The
public storefront itself requires no permission at all: customers do not have
accounts.
"""

from __future__ import annotations

from typing import Final

from ahia.core.permissions.permission_types import PermissionDefinition

STOREFRONT_READ: Final[str] = "storefront.read"
STOREFRONT_MANAGE: Final[str] = "storefront.manage"

PERMISSIONS: Final[tuple[PermissionDefinition, ...]] = (
    PermissionDefinition(
        code=STOREFRONT_READ,
        module="storefront",
        description="View the business storefront configuration and public link",
    ),
    PermissionDefinition(
        code=STOREFRONT_MANAGE,
        module="storefront",
        description="Change storefront branding and configuration, and publish or unpublish it",
    ),
)
