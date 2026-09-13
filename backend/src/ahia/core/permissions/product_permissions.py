"""Product and catalogue permissions."""

from __future__ import annotations

from typing import Final

from ahia.core.permissions.permission_types import PermissionDefinition

PRODUCTS_READ: Final[str] = "products.read"
PRODUCTS_CREATE: Final[str] = "products.create"
PRODUCTS_UPDATE: Final[str] = "products.update"
PRODUCTS_DELETE: Final[str] = "products.delete"

PERMISSIONS: Final[tuple[PermissionDefinition, ...]] = (
    PermissionDefinition(
        code=PRODUCTS_READ,
        module="products",
        description="View products in the catalogue, including inactive ones",
    ),
    PermissionDefinition(
        code=PRODUCTS_CREATE,
        module="products",
        description="Add a product to the catalogue",
    ),
    PermissionDefinition(
        code=PRODUCTS_UPDATE,
        module="products",
        description="Change a product's details, price or images",
    ),
    PermissionDefinition(
        code=PRODUCTS_DELETE,
        module="products",
        description="Deactivate a product so it is no longer sold or published",
    ),
)
