"""Tests for the role, permission and role-permission entities.

These three entities are reference data rather than tenant-owned records, so the
tests are about the invariants that keep a permission model coherent: a code that
belongs to the module it claims, a role that is unambiguously either a system role
or a business's own, and a link whose two sides are distinct.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.permission_model import PermissionModel
from ahia.models.entities.role_model import RoleModel
from ahia.models.entities.role_permission_model import RolePermissionModel

NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)


def build_permission(**overrides: object) -> PermissionModel:
    parameters: dict[str, object] = {
        "id": uuid4(),
        "code": "products.read",
        "module": "products",
        "description": "View products in the catalogue",
    }
    parameters.update(overrides)
    return PermissionModel(**parameters)  # type: ignore[arg-type]


def build_system_role(**overrides: object) -> RoleModel:
    parameters: dict[str, object] = {
        "role_id": uuid4(),
        "name": "OWNER",
        "description": "The business owner",
        "now": NOW,
    }
    parameters.update(overrides)
    return RoleModel.system_role(**parameters)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Permission
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_well_formed_permission_is_accepted() -> None:
    permission = build_permission()

    assert permission.module == "products"
    assert permission.code == "products.read"
    assert permission.describe_for_audit()["permission_code"] == "products.read"


@pytest.mark.unit
def test_a_code_must_carry_its_module_prefix() -> None:
    """A mislabelled capability is a permission nobody can find by module."""
    with pytest.raises(EntityInvariantError, match="module prefix"):
        build_permission(code="inventory.read", module="products")


@pytest.mark.unit
def test_an_empty_code_is_rejected() -> None:
    with pytest.raises(EntityInvariantError, match="code is empty"):
        build_permission(code="  ")


@pytest.mark.unit
def test_an_empty_module_is_rejected() -> None:
    with pytest.raises(EntityInvariantError, match="module is empty"):
        build_permission(code=".read", module="")


@pytest.mark.unit
def test_an_overlong_description_is_rejected() -> None:
    with pytest.raises(EntityInvariantError, match="description exceeds"):
        build_permission(description="x" * 256)


@pytest.mark.unit
def test_a_permission_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        build_permission().code = "other.read"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Role
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_system_role_belongs_to_no_tenant() -> None:
    role = build_system_role()

    assert role.is_system_role is True
    assert role.is_custom is False
    assert role.tenant_id is None


@pytest.mark.unit
def test_a_custom_role_belongs_to_exactly_one_tenant() -> None:
    tenant_id = uuid4()
    role = RoleModel.custom_role(
        role_id=uuid4(),
        tenant_id=tenant_id,
        name="SUPERVISOR",
        description="A role this business invented",
        now=NOW,
    )

    assert role.is_custom is True
    assert role.tenant_id == tenant_id


@pytest.mark.unit
def test_a_system_role_cannot_be_given_a_tenant() -> None:
    """Otherwise OWNER would mean something different in every business."""
    with pytest.raises(EntityInvariantError, match="cannot belong to a tenant"):
        RoleModel(
            id=uuid4(),
            name="OWNER",
            description="The business owner",
            is_system_role=True,
            tenant_id=uuid4(),
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.unit
def test_a_custom_role_must_name_its_tenant() -> None:
    with pytest.raises(EntityInvariantError, match="must belong to a tenant"):
        RoleModel(
            id=uuid4(),
            name="SUPERVISOR",
            description="A role nobody owns",
            is_system_role=False,
            tenant_id=None,
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.unit
@pytest.mark.parametrize("name", ["owner", "Owner", "1OWNER", "OWN-ER", "", "A"])
def test_a_role_name_must_be_narrow(name: str) -> None:
    with pytest.raises(EntityInvariantError, match="must be uppercase letters"):
        build_system_role(name=name)


@pytest.mark.unit
def test_timestamps_must_carry_a_timezone() -> None:
    with pytest.raises(EntityInvariantError, match="naive datetime"):
        build_system_role(now=datetime(2026, 9, 13, 9, 30))  # noqa: DTZ001 - the input under test


@pytest.mark.unit
def test_update_cannot_predate_creation() -> None:
    with pytest.raises(EntityInvariantError, match="updated_at is earlier"):
        RoleModel(
            id=uuid4(),
            name="SUPERVISOR",
            description="A role",
            is_system_role=False,
            tenant_id=uuid4(),
            created_at=NOW,
            updated_at=NOW - timedelta(hours=1),
        )


@pytest.mark.unit
def test_a_custom_role_description_can_change_but_its_name_cannot() -> None:
    role = RoleModel.custom_role(
        role_id=uuid4(),
        tenant_id=uuid4(),
        name="SUPERVISOR",
        description="Before",
        now=NOW,
    )

    renamed = role.with_description(description="After", at=NOW + timedelta(minutes=1))

    assert renamed.description == "After"
    assert renamed.name == "SUPERVISOR", "memberships reference the name"
    assert not hasattr(role, "with_name")


@pytest.mark.unit
def test_a_system_role_cannot_be_edited() -> None:
    """It is provisioned from code, so an edit here would be overwritten anyway."""
    with pytest.raises(EntityInvariantError, match="cannot be edited"):
        build_system_role().with_description(description="Changed", at=NOW)


@pytest.mark.unit
def test_audit_description_distinguishes_the_two_kinds() -> None:
    system = build_system_role().describe_for_audit()
    custom = RoleModel.custom_role(
        role_id=uuid4(),
        tenant_id=uuid4(),
        name="SUPERVISOR",
        description="A role this business invented",
        now=NOW,
    ).describe_for_audit()

    assert system["is_system_role"] == "true"
    assert "tenant_id" not in system
    assert custom["is_system_role"] == "false"
    assert "tenant_id" in custom


# ---------------------------------------------------------------------------
# Role-permission link
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_link_records_both_sides() -> None:
    role_id = uuid4()
    permission_id = uuid4()

    link = RolePermissionModel(role_id=role_id, permission_id=permission_id)

    assert link.describe_for_audit() == {
        "role_id": str(role_id),
        "permission_id": str(permission_id),
    }


@pytest.mark.unit
def test_a_link_whose_sides_are_the_same_identifier_is_rejected() -> None:
    """It means something upstream confused a role for a permission."""
    shared_id = uuid4()

    with pytest.raises(EntityInvariantError, match="cannot share an identifier"):
        RolePermissionModel(role_id=shared_id, permission_id=shared_id)
