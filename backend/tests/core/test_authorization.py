"""Tests for the permission registry and the deny-by-default policy.

Authorization is the control that everything else assumes. These tests attack it
the way an attacker would: an unknown permission, an empty permission set, a
role bundle that grants more than intended, and a decision that is not recorded.
"""

from __future__ import annotations

import logging
from dataclasses import FrozenInstanceError
from pathlib import Path
from uuid import uuid4

import pytest

from ahia.core import tenant_context as tenant_context_module
from ahia.core.errors import AuthorizationError
from ahia.core.permissions import (
    customer_permissions,
    device_permissions,
    expense_permissions,
    inventory_permissions,
    product_permissions,
    report_permissions,
    sales_permissions,
    staff_permissions,
)
from ahia.core.permissions.permission_types import PermissionDefinition
from ahia.core.permissions.permissions_registry import (
    ALL_PERMISSIONS,
    PERMISSION_CODES,
    SYSTEM_ROLES,
    permission_codes_for_role,
    validate_registry,
)
from ahia.core.tenant_context import (
    MembershipStatus,
    TenantContext,
    build_tenant_context,
)

USER_ID = uuid4()
TENANT_ID = uuid4()
MEMBERSHIP_ID = uuid4()
ROLE_ID = uuid4()
DEVICE_ID = uuid4()


def build_context(*permission_codes: str, **overrides: object) -> TenantContext:
    parameters: dict[str, object] = {
        "user_id": USER_ID,
        "tenant_id": TENANT_ID,
        "membership_id": MEMBERSHIP_ID,
        "role_id": ROLE_ID,
        "permission_codes": frozenset(permission_codes),
        "device_id": DEVICE_ID,
        "role_name": "SALES",
    }
    parameters.update(overrides)
    return build_tenant_context(**parameters)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_registry_is_internally_consistent() -> None:
    validate_registry()


@pytest.mark.unit
def test_every_permission_code_is_module_dot_action() -> None:
    for permission in ALL_PERMISSIONS:
        module, _, action = permission.code.partition(".")
        assert module == permission.module
        assert action
        assert permission.description
        assert permission.code == permission.code.lower()


@pytest.mark.unit
def test_permission_codes_are_unique() -> None:
    codes = [permission.code for permission in ALL_PERMISSIONS]

    assert len(codes) == len(set(codes))


@pytest.mark.unit
def test_the_specification_permissions_are_all_present() -> None:
    """The set the product specification names verbatim."""
    expected = {
        "products.read",
        "products.create",
        "products.update",
        "products.delete",
        "inventory.read",
        "inventory.stock_in",
        "inventory.adjust",
        "inventory.scan",
        "sales.read",
        "sales.create",
        "sales.cancel",
        "customers.read",
        "customers.create",
        "customers.update",
        "expenses.read",
        "expenses.create",
        "reports.read",
        "staff.read",
        "staff.invite",
        "staff.update",
        "staff.remove",
        "storefront.read",
        "storefront.manage",
    }

    assert expected <= PERMISSION_CODES


@pytest.mark.unit
def test_a_permission_code_must_carry_its_module_prefix() -> None:
    with pytest.raises(ValueError, match="module prefix"):
        PermissionDefinition(code="inventory.read", module="products", description="mislabelled")


@pytest.mark.unit
@pytest.mark.parametrize("role_name", ["unknown", "SUPERUSER", ""])
def test_unknown_role_is_rejected_rather_than_returning_nothing(role_name: str) -> None:
    """An empty set would deny, but it would also hide a typo behind a denial."""
    with pytest.raises(KeyError, match="unknown system role"):
        permission_codes_for_role(role_name)


@pytest.mark.unit
def test_owner_holds_every_permission() -> None:
    assert SYSTEM_ROLES["OWNER"].permissions == PERMISSION_CODES


@pytest.mark.unit
def test_sales_role_cannot_see_reports_staff_or_devices() -> None:
    """The product specification is explicit: a salesperson sees neither."""
    sales_permissions_set = permission_codes_for_role("SALES")

    assert report_permissions.REPORTS_READ not in sales_permissions_set
    assert staff_permissions.STAFF_INVITE not in sales_permissions_set
    assert staff_permissions.STAFF_REMOVE not in sales_permissions_set
    assert device_permissions.DEVICES_REVOKE not in sales_permissions_set
    assert expense_permissions.EXPENSES_READ not in sales_permissions_set


@pytest.mark.unit
def test_sales_role_can_sell_and_record_customers() -> None:
    sales_permissions_set = permission_codes_for_role("SALES")

    assert sales_permissions.SALES_CREATE in sales_permissions_set
    assert customer_permissions.CUSTOMERS_CREATE in sales_permissions_set
    assert product_permissions.PRODUCTS_READ in sales_permissions_set


@pytest.mark.unit
def test_inventory_role_cannot_sell_or_read_financial_data() -> None:
    inventory_permissions_set = permission_codes_for_role("INVENTORY")

    assert inventory_permissions.INVENTORY_STOCK_IN in inventory_permissions_set
    assert inventory_permissions.INVENTORY_ADJUST in inventory_permissions_set
    assert sales_permissions.SALES_CREATE not in inventory_permissions_set
    assert report_permissions.REPORTS_READ not in inventory_permissions_set


@pytest.mark.unit
def test_manager_is_not_a_hidden_superuser() -> None:
    """A manager is a configurable role, not a second owner."""
    manager_permissions = permission_codes_for_role("MANAGER")

    assert staff_permissions.STAFF_REMOVE not in manager_permissions
    assert device_permissions.DEVICES_REVOKE not in manager_permissions
    assert report_permissions.REPORTS_READ in manager_permissions


@pytest.mark.unit
def test_no_role_grants_a_permission_outside_the_registry() -> None:
    for role in SYSTEM_ROLES.values():
        assert role.permissions <= PERMISSION_CODES


@pytest.mark.unit
def test_unknown_permission_codes_are_dropped_when_building_a_context() -> None:
    context = build_context("sales.create", "admin.everything")

    assert context.has_permission("sales.create")
    assert not context.has_permission("admin.everything")
    assert context.permissions == frozenset({"sales.create"})


# ---------------------------------------------------------------------------
# Deny by default
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_an_empty_permission_set_denies_everything() -> None:
    context = build_context()

    with pytest.raises(AuthorizationError):
        context.require_permission("sales.create", operation="complete_sale")

    for code in PERMISSION_CODES:
        assert context.has_permission(code) is False


@pytest.mark.unit
def test_a_permitted_action_is_allowed_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    context = build_context("sales.create")

    with caplog.at_level(logging.INFO, logger="ahia.core.authorization"):
        context.require_permission(
            "sales.create",
            operation="complete_sale",
            resource_type="sale",
            resource_id="8f3a",
        )

    record = caplog.records[0]
    assert record.getMessage() == "authorization_allowed"
    assert record.decision == "allowed"
    assert record.action == "sales.create"
    assert record.actor_id == str(USER_ID)
    assert record.tenant_id == str(TENANT_ID)
    assert record.resource_type == "sale"


@pytest.mark.unit
def test_a_denied_action_raises_and_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    context = build_context("sales.create")

    with (
        caplog.at_level(logging.WARNING, logger="ahia.core.authorization"),
        pytest.raises(AuthorizationError) as captured,
    ):
        context.require_permission("inventory.adjust", operation="adjust_stock")

    record = caplog.records[0]
    assert record.getMessage() == "authorization_denied"
    assert record.decision == "denied"
    assert record.reason == "permission_absent"
    assert record.action == "inventory.adjust"

    # The external view states the denial and nothing about what the caller
    # holds or what would have been enough.
    external = captured.value.external()
    assert external.code == "FORBIDDEN"
    # The message states the denial and nothing that helps the caller work out
    # what to ask for next: not the required code, not the held role.
    assert "inventory.adjust" not in external.message
    assert "inventory" not in external.message
    assert "SALES" not in external.message


@pytest.mark.unit
def test_a_denial_does_not_reveal_whether_the_resource_exists() -> None:
    context = build_context("products.read")

    with pytest.raises(AuthorizationError) as captured:
        context.require_permission(
            "products.delete",
            operation="deactivate_product",
            resource_type="product",
            resource_id="a-real-looking-identifier",
        )

    payload = captured.value.external().to_payload()["error"]
    assert "a-real-looking-identifier" not in payload["message"]


@pytest.mark.unit
def test_holding_an_unrelated_permission_does_not_grant_another() -> None:
    context = build_context("products.read", "storefront.read")

    with pytest.raises(AuthorizationError):
        context.require_permission("storefront.manage", operation="publish_storefront")


@pytest.mark.unit
def test_every_denial_produces_a_log_record() -> None:
    """A denial that leaves no trace is a denial an investigation cannot see."""
    context = build_context("sales.create")
    denials: list[str] = []

    logger = logging.getLogger("ahia.core.authorization")

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.getMessage() == "authorization_denied":
                denials.append(record.action)

    handler = CaptureHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        for code in ("inventory.adjust", "staff.remove", "reports.read"):
            with pytest.raises(AuthorizationError):
                context.require_permission(code, operation="attempt")
    finally:
        logger.removeHandler(handler)

    assert denials == ["inventory.adjust", "staff.remove", "reports.read"]


# ---------------------------------------------------------------------------
# Context construction and audit fields
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_context_carries_the_resolved_identity() -> None:
    context = build_context("sales.create")

    assert context.user_id == USER_ID
    assert context.tenant_id == TENANT_ID
    assert context.membership_id == MEMBERSHIP_ID
    assert context.role_id == ROLE_ID
    assert context.device_id == DEVICE_ID
    assert context.role_name == "SALES"


@pytest.mark.unit
def test_context_is_immutable() -> None:
    context = build_context("sales.create")

    with pytest.raises(FrozenInstanceError):
        context.permissions = frozenset()  # type: ignore[misc]


@pytest.mark.unit
def test_audit_description_contains_identifiers_and_no_names() -> None:
    description = build_context("sales.create").describe_for_audit()

    assert description["tenant_id"] == str(TENANT_ID)
    assert description["actor_id"] == str(USER_ID)
    assert description["device_id"] == str(DEVICE_ID)
    # Identifiers only: an audit record does not need a person's name to be
    # useful, and a name is personal data.
    assert set(description) == {"tenant_id", "actor_id", "membership_id", "role_id", "device_id"}


@pytest.mark.unit
def test_a_context_without_a_device_still_authorizes() -> None:
    """A browser session is not always bound to a registered device."""
    context = build_context("sales.create", device_id=None)

    context.require_permission("sales.create", operation="complete_sale")

    assert "device_id" not in context.describe_for_audit()


# ---------------------------------------------------------------------------
# Membership status
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("status", "grants"),
    [
        (MembershipStatus.ACTIVE, True),
        (MembershipStatus.INVITED, False),
        (MembershipStatus.SUSPENDED, False),
        (MembershipStatus.REMOVED, False),
    ],
)
def test_only_an_active_membership_grants_access(status: MembershipStatus, grants: bool) -> None:
    assert status.grants_access is grants


@pytest.mark.unit
def test_no_third_party_permission_library_is_needed() -> None:
    """A policy engine is not required; the rules are a dozen lines and auditable."""
    source = Path(tenant_context_module.__file__).read_text(encoding="utf-8").lower()

    assert "casbin" not in source
    assert "policy_engine" not in source
