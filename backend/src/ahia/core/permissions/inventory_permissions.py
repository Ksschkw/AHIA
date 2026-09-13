"""Inventory permissions.

Stock quantities are money. Adjusting them is a separate capability from selling,
because the people who count stock and the people who sell it are often not the
same person, and the audit trail depends on that distinction.
"""

from __future__ import annotations

from typing import Final

from ahia.core.permissions.permission_types import PermissionDefinition

INVENTORY_READ: Final[str] = "inventory.read"
INVENTORY_STOCK_IN: Final[str] = "inventory.stock_in"
INVENTORY_ADJUST: Final[str] = "inventory.adjust"
INVENTORY_SCAN: Final[str] = "inventory.scan"

PERMISSIONS: Final[tuple[PermissionDefinition, ...]] = (
    PermissionDefinition(
        code=INVENTORY_READ,
        module="inventory",
        description="View stock levels and inventory movement history",
    ),
    PermissionDefinition(
        code=INVENTORY_STOCK_IN,
        module="inventory",
        description="Receive stock against a product, optionally from a supplier",
    ),
    PermissionDefinition(
        code=INVENTORY_ADJUST,
        module="inventory",
        description="Record a stock adjustment, damage or correction with a reason",
    ),
    PermissionDefinition(
        code=INVENTORY_SCAN,
        module="inventory",
        description="Scan a product or carton code to identify or move stock",
    ),
)
