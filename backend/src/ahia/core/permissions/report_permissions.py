"""Reporting permissions.

Reports expose revenue, margin and staff performance. This is the capability a
salesperson must not hold by default, which is why it is its own permission
rather than a consequence of reading sales.
"""

from __future__ import annotations

from typing import Final

from ahia.core.permissions.permission_types import PermissionDefinition

REPORTS_READ: Final[str] = "reports.read"

PERMISSIONS: Final[tuple[PermissionDefinition, ...]] = (
    PermissionDefinition(
        code=REPORTS_READ,
        module="reports",
        description="View business reports, the ledger and audit history",
    ),
)
