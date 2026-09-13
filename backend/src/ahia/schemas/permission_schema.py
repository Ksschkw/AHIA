"""Transport contracts for roles and permissions.

The catalogue is read-only reference data; roles are the editable surface. A system
role cannot be edited through the API, so the update contract only ever applies to
a business's own roles, and the service refuses the rest.
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from ahia.models.entities.permission_model import PermissionModel
from ahia.models.entities.role_model import RoleModel

RoleName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, min_length=2, max_length=32),
]

_MAXIMUM_DESCRIPTION_LENGTH: Final[int] = 255


class PermissionResponseSchema(BaseModel):
    """One capability."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    code: str
    module: str
    description: str

    @classmethod
    def from_entity(cls, permission: PermissionModel) -> PermissionResponseSchema:
        return cls(
            id=permission.id,
            code=permission.code,
            module=permission.module,
            description=permission.description,
        )


class RoleResponseSchema(BaseModel):
    """One role and the capabilities it grants.

    The permission codes are included rather than the identifiers, because a
    client renders a role by what it can do.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    description: str
    is_system_role: bool
    permission_codes: list[str]


class CustomRoleCreateSchema(BaseModel):
    """A business's own role."""

    model_config = ConfigDict(extra="forbid")

    name: RoleName
    description: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=_MAXIMUM_DESCRIPTION_LENGTH
        ),
    ]
    permission_codes: list[str]

    @field_validator("permission_codes")
    @classmethod
    def _require_at_least_one(cls, value: list[str]) -> list[str]:
        """A role that grants nothing is not a role; it is a mistake."""
        if not value:
            raise ValueError("a role must grant at least one permission")
        return sorted(set(value))


class RolePermissionsUpdateSchema(BaseModel):
    """A replacement permission set for a role."""

    model_config = ConfigDict(extra="forbid")

    permission_codes: list[str]

    @field_validator("permission_codes")
    @classmethod
    def _normalize(cls, value: list[str]) -> list[str]:
        return sorted(set(value))


def build_role_response(role: RoleModel, *, permission_codes: frozenset[str]) -> RoleResponseSchema:
    """Serialise a role. The mapping lives here because both layers need it."""
    return RoleResponseSchema(
        id=role.id,
        name=role.name,
        description=role.description,
        is_system_role=role.is_system_role,
        permission_codes=sorted(permission_codes),
    )
