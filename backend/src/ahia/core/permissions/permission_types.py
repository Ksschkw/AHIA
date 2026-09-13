"""The value objects shared by every permission module.

Kept in its own module so a domain permission file can import the definition
type without importing the registry that aggregates it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

CODE_SEPARATOR: Final[str] = "."


@dataclass(frozen=True, slots=True)
class PermissionDefinition:
    """One application capability."""

    code: str
    module: str
    description: str

    def __post_init__(self) -> None:
        expected_prefix = f"{self.module}{CODE_SEPARATOR}"
        if not self.code.startswith(expected_prefix):
            raise ValueError(
                f"permission {self.code!r} must start with its module prefix {expected_prefix!r}"
            )


@dataclass(frozen=True, slots=True)
class RoleDefinition:
    """A named bundle of permissions.

    These are the system roles provisioned by the platform. A tenant may later
    define custom roles, which are rows in the database; these are the ones that
    must exist in every deployment.
    """

    name: str
    description: str
    permissions: frozenset[str]
