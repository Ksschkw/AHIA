"""Permission registry.

Aggregates the per-domain permission modules into the one closed set the
application understands, and defines the system role bundles.

A role is a bundle of permission codes. The code is written once, in its domain
module, and referenced here and in the database seed, so a renamed capability
breaks the build rather than silently un-granting access.
"""

from __future__ import annotations

from typing import Final

from ahia.core.permissions import (
    customer_permissions,
    device_permissions,
    expense_permissions,
    inventory_permissions,
    product_permissions,
    report_permissions,
    sales_permissions,
    staff_permissions,
    storefront_permissions,
)
from ahia.core.permissions.permission_types import (
    CODE_SEPARATOR,
    PermissionDefinition,
    RoleDefinition,
)

_PERMISSION_MODULES: Final[tuple[tuple[PermissionDefinition, ...], ...]] = (
    product_permissions.PERMISSIONS,
    inventory_permissions.PERMISSIONS,
    sales_permissions.PERMISSIONS,
    customer_permissions.PERMISSIONS,
    expense_permissions.PERMISSIONS,
    staff_permissions.PERMISSIONS,
    storefront_permissions.PERMISSIONS,
    report_permissions.PERMISSIONS,
    device_permissions.PERMISSIONS,
)

#: Every permission the application understands.
ALL_PERMISSIONS: Final[tuple[PermissionDefinition, ...]] = tuple(
    permission for module_permissions in _PERMISSION_MODULES for permission in module_permissions
)

#: Every permission code, for validation and for the database seed.
PERMISSION_CODES: Final[frozenset[str]] = frozenset(
    permission.code for permission in ALL_PERMISSIONS
)

#: Bundles that must exist in every deployment. A tenant may add custom roles
#: later; these are the ones the product promises.
SYSTEM_ROLES: Final[dict[str, RoleDefinition]] = {
    "OWNER": RoleDefinition(
        name="OWNER",
        description="The business owner. Holds every tenant permission.",
        permissions=PERMISSION_CODES,
    ),
    "MANAGER": RoleDefinition(
        name="MANAGER",
        description=(
            "Runs the shop day to day: full operations, staff administration and "
            "reports, but not removing staff or revoking devices."
        ),
        permissions=frozenset(
            {
                product_permissions.PRODUCTS_READ,
                product_permissions.PRODUCTS_CREATE,
                product_permissions.PRODUCTS_UPDATE,
                inventory_permissions.INVENTORY_READ,
                inventory_permissions.INVENTORY_STOCK_IN,
                inventory_permissions.INVENTORY_ADJUST,
                inventory_permissions.INVENTORY_SCAN,
                sales_permissions.SALES_READ,
                sales_permissions.SALES_CREATE,
                sales_permissions.SALES_CANCEL,
                customer_permissions.CUSTOMERS_READ,
                customer_permissions.CUSTOMERS_CREATE,
                customer_permissions.CUSTOMERS_UPDATE,
                expense_permissions.EXPENSES_READ,
                expense_permissions.EXPENSES_CREATE,
                staff_permissions.STAFF_READ,
                staff_permissions.STAFF_INVITE,
                staff_permissions.STAFF_UPDATE,
                storefront_permissions.STOREFRONT_READ,
                storefront_permissions.STOREFRONT_MANAGE,
                report_permissions.REPORTS_READ,
                device_permissions.DEVICES_READ,
            }
        ),
    ),
    "SALES": RoleDefinition(
        name="SALES",
        description=(
            "A salesperson. Sells and records customers and sees the catalogue, "
            "but never financial reports, staff administration or device control."
        ),
        permissions=frozenset(
            {
                product_permissions.PRODUCTS_READ,
                inventory_permissions.INVENTORY_READ,
                sales_permissions.SALES_READ,
                sales_permissions.SALES_CREATE,
                customer_permissions.CUSTOMERS_READ,
                customer_permissions.CUSTOMERS_CREATE,
                storefront_permissions.STOREFRONT_READ,
            }
        ),
    ),
    "INVENTORY": RoleDefinition(
        name="INVENTORY",
        description=(
            "An inventory worker. Receives and adjusts stock and scans codes, "
            "without access to sales totals or financial records."
        ),
        permissions=frozenset(
            {
                product_permissions.PRODUCTS_READ,
                inventory_permissions.INVENTORY_READ,
                inventory_permissions.INVENTORY_STOCK_IN,
                inventory_permissions.INVENTORY_ADJUST,
                inventory_permissions.INVENTORY_SCAN,
                storefront_permissions.STOREFRONT_READ,
            }
        ),
    ),
}


def permission_codes_for_role(role_name: str) -> frozenset[str]:
    """Return the permission codes of a system role.

    Raises for an unknown role rather than returning an empty set: an empty set
    would fail closed for authorization, but it would also hide a typo in a role
    name behind a permission denial.
    """
    role = SYSTEM_ROLES.get(role_name.upper())
    if role is None:
        raise KeyError(f"unknown system role: {role_name}")
    return role.permissions


def validate_registry() -> None:
    """Fail loudly when the registry is internally inconsistent.

    Called at startup and asserted by tests. A role that references a permission
    which does not exist is a permission check that can never pass; a duplicate
    code is a bundle that silently shadows another; a code whose module prefix
    does not match its declaration is a permission that cannot be discovered by
    module.
    """
    codes = [permission.code for permission in ALL_PERMISSIONS]
    duplicates = sorted({code for code in codes if codes.count(code) > 1})
    if duplicates:
        raise ValueError(f"duplicate permission codes in the registry: {duplicates}")

    for permission in ALL_PERMISSIONS:
        if CODE_SEPARATOR not in permission.code:
            raise ValueError(f"permission code has no module separator: {permission.code}")

    for role_name, role in SYSTEM_ROLES.items():
        unknown = sorted(role.permissions - PERMISSION_CODES)
        if unknown:
            raise ValueError(f"role {role_name} references unknown permissions: {unknown}")

    if SYSTEM_ROLES["OWNER"].permissions != PERMISSION_CODES:
        raise ValueError("the OWNER role must hold every permission")
