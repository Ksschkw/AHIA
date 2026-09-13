"""Expense permissions.

Expenses affect the profit figure, so recording one is separate from reading the
expense list, which in turn is separate from reading reports.
"""

from __future__ import annotations

from typing import Final

from ahia.core.permissions.permission_types import PermissionDefinition

EXPENSES_READ: Final[str] = "expenses.read"
EXPENSES_CREATE: Final[str] = "expenses.create"

PERMISSIONS: Final[tuple[PermissionDefinition, ...]] = (
    PermissionDefinition(
        code=EXPENSES_READ,
        module="expenses",
        description="View recorded business expenses",
    ),
    PermissionDefinition(
        code=EXPENSES_CREATE,
        module="expenses",
        description="Record a business expense",
    ),
)
