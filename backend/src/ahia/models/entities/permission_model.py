"""The permission entity: one application capability, as data.

The registry in `core.permissions` is where a permission is *declared*. This entity
is how that declaration is stored, so an operator can query the capabilities a
deployment has, a role editor can list what exists, and a future admin surface does
not have to read Python to find out.

The two must agree. A test asserts that the seeded rows are exactly the registry, so
a permission that exists in code but not in the database - or the other way round -
fails the build rather than silently changing what a role grants.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError

_CODE_SEPARATOR: Final[str] = "."
_MAXIMUM_MODULE_LENGTH: Final[int] = 64
_MAXIMUM_CODE_LENGTH: Final[int] = 128
_MAXIMUM_DESCRIPTION_LENGTH: Final[int] = 255


@dataclass(frozen=True, slots=True)
class PermissionModel:
    """One application capability."""

    id: UUID
    code: str
    module: str
    description: str

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise EntityInvariantError(
                operation="build_permission",
                entity="permission",
                identifier=str(self.id),
                detail="code is empty",
            )
        if len(self.code) > _MAXIMUM_CODE_LENGTH:
            raise EntityInvariantError(
                operation="build_permission",
                entity="permission",
                identifier=str(self.id),
                detail=f"code exceeds {_MAXIMUM_CODE_LENGTH} characters",
            )
        if not self.module.strip() or len(self.module) > _MAXIMUM_MODULE_LENGTH:
            raise EntityInvariantError(
                operation="build_permission",
                entity="permission",
                identifier=str(self.id),
                detail="module is empty or too long",
            )
        if not self.code.startswith(f"{self.module}{_CODE_SEPARATOR}"):
            raise EntityInvariantError(
                operation="build_permission",
                entity="permission",
                identifier=str(self.id),
                detail=f"code {self.code!r} does not start with its module prefix",
            )
        if len(self.description) > _MAXIMUM_DESCRIPTION_LENGTH:
            raise EntityInvariantError(
                operation="build_permission",
                entity="permission",
                identifier=str(self.id),
                detail=f"description exceeds {_MAXIMUM_DESCRIPTION_LENGTH} characters",
            )

    def describe_for_audit(self) -> dict[str, str]:
        """Return the fields an audit record needs. A permission holds no personal data."""
        return {"permission_id": str(self.id), "permission_code": self.code}
