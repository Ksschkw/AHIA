"""Customer permissions.

A customer list is personal data. Reading it is a capability, not an implicit
consequence of being able to sell.
"""

from __future__ import annotations

from typing import Final

from ahia.core.permissions.permission_types import PermissionDefinition

CUSTOMERS_READ: Final[str] = "customers.read"
CUSTOMERS_CREATE: Final[str] = "customers.create"
CUSTOMERS_UPDATE: Final[str] = "customers.update"

PERMISSIONS: Final[tuple[PermissionDefinition, ...]] = (
    PermissionDefinition(
        code=CUSTOMERS_READ,
        module="customers",
        description="View customer profiles and their purchase history",
    ),
    PermissionDefinition(
        code=CUSTOMERS_CREATE,
        module="customers",
        description="Add a customer record",
    ),
    PermissionDefinition(
        code=CUSTOMERS_UPDATE,
        module="customers",
        description="Change customer details, notes and marketing preference",
    ),
)
