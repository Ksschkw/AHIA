"""Sales permissions.

Cancelling a sale is separate from creating one: it is the operation most often
used to conceal a discrepancy, so it is granted deliberately and audited.
"""

from __future__ import annotations

from typing import Final

from ahia.core.permissions.permission_types import PermissionDefinition

SALES_READ: Final[str] = "sales.read"
SALES_CREATE: Final[str] = "sales.create"
SALES_CANCEL: Final[str] = "sales.cancel"

PERMISSIONS: Final[tuple[PermissionDefinition, ...]] = (
    PermissionDefinition(
        code=SALES_READ,
        module="sales",
        description="View sales, receipts and payment records",
    ),
    PermissionDefinition(
        code=SALES_CREATE,
        module="sales",
        description="Record a sale and take a payment against it",
    ),
    PermissionDefinition(
        code=SALES_CANCEL,
        module="sales",
        description="Cancel a sale, writing compensating inventory and financial events",
    ),
)
