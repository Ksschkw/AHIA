"""Tests for the membership entity.

The membership is where multi-tenancy becomes concrete, so the tests are about
the lifecycle: what grants access, what does not, which transitions are legal, and
what the last-owner rule depends on.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ahia.core.errors import EntityInvariantError
from ahia.core.permissions.permissions_registry import SYSTEM_ROLES
from ahia.models.entities.tenant_membership_model import (
    ALLOWED_TRANSITIONS,
    MembershipStatus,
    TenantMembershipModel,
)

NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)


def build_invitation(**overrides: object) -> TenantMembershipModel:
    parameters: dict[str, object] = {
        "membership_id": uuid4(),
        "tenant_id": uuid4(),
        "user_id": uuid4(),
        "role_name": "SALES",
        "now": NOW,
    }
    parameters.update(overrides)
    return TenantMembershipModel.invite(**parameters)  # type: ignore[arg-type]


def build_active(**overrides: object) -> TenantMembershipModel:
    parameters: dict[str, object] = {
        "membership_id": uuid4(),
        "tenant_id": uuid4(),
        "user_id": uuid4(),
        "role_name": "SALES",
        "now": NOW,
    }
    parameters.update(overrides)
    return TenantMembershipModel.activate_immediately(**parameters)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_an_invitation_grants_nothing_until_it_is_accepted() -> None:
    invitation = build_invitation()

    assert invitation.status is MembershipStatus.INVITED
    assert invitation.grants_access is False
    assert invitation.joined_at is None
    assert invitation.invited_at == NOW


@pytest.mark.unit
def test_an_immediately_active_membership_records_the_join() -> None:
    """The owner created with a business has already proven who they are."""
    owner = build_active(role_name="OWNER")

    assert owner.status is MembershipStatus.ACTIVE
    assert owner.grants_access is True
    assert owner.joined_at == NOW
    assert owner.is_owner is True


@pytest.mark.unit
def test_the_role_is_normalized_and_validated() -> None:
    membership = build_invitation(role_name="  sales  ")

    assert membership.role_name == "SALES"


@pytest.mark.unit
@pytest.mark.parametrize("role_name", ["SUPERUSER", "root", "", "OWNERS"])
def test_an_unknown_role_is_rejected(role_name: str) -> None:
    """An unknown role resolves to no permissions, which looks like a bug."""
    with pytest.raises(EntityInvariantError, match="unknown role"):
        build_invitation(role_name=role_name)


@pytest.mark.unit
def test_permissions_come_from_the_role_registry_not_the_row() -> None:
    """A change to what a role means applies to everyone holding it."""
    membership = build_active(role_name="SALES")

    assert membership.permission_codes == SYSTEM_ROLES["SALES"].permissions
    assert "sales.create" in membership.permission_codes
    assert "reports.read" not in membership.permission_codes


@pytest.mark.unit
def test_an_active_membership_must_record_when_the_person_joined() -> None:
    with pytest.raises(EntityInvariantError, match="must record when the person joined"):
        TenantMembershipModel(
            id=uuid4(),
            tenant_id=uuid4(),
            user_id=uuid4(),
            role_name="SALES",
            status=MembershipStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.unit
def test_a_removed_membership_must_record_when_it_ended() -> None:
    with pytest.raises(EntityInvariantError, match="must record when it ended"):
        TenantMembershipModel(
            id=uuid4(),
            tenant_id=uuid4(),
            user_id=uuid4(),
            role_name="SALES",
            status=MembershipStatus.REMOVED,
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.unit
def test_a_removal_timestamp_on_a_live_membership_is_rejected() -> None:
    """An inconsistent record is rejected wherever it came from, not only from a transition."""
    with pytest.raises(EntityInvariantError, match="removed_at is set"):
        _build_with_removed_at()


def _build_with_removed_at() -> TenantMembershipModel:
    """Build an inconsistent record on purpose, to prove the invariant fires."""
    return TenantMembershipModel(
        id=uuid4(),
        tenant_id=uuid4(),
        user_id=uuid4(),
        role_name="SALES",
        status=MembershipStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
        joined_at=NOW,
        removed_at=NOW,
    )


@pytest.mark.unit
def test_timestamps_must_carry_a_timezone() -> None:
    with pytest.raises(EntityInvariantError, match="naive datetime"):
        build_invitation(now=datetime(2026, 9, 13, 9, 30))  # noqa: DTZ001 - the input under test


@pytest.mark.unit
def test_the_entity_is_immutable() -> None:
    membership = build_active()

    with pytest.raises(FrozenInstanceError):
        membership.role_name = "MANAGER"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_accepting_an_invitation_activates_it_and_records_the_join() -> None:
    invitation = build_invitation()
    later = NOW + timedelta(hours=2)

    accepted = invitation.activate(at=later)

    assert accepted.status is MembershipStatus.ACTIVE
    assert accepted.joined_at == later
    assert accepted.grants_access is True
    assert invitation.grants_access is False, "the original is untouched"


@pytest.mark.unit
def test_reactivating_keeps_the_original_join_date() -> None:
    """A suspension that is lifted does not make the person new."""
    active = build_active()
    suspended_at = NOW + timedelta(days=1)
    reactivated_at = NOW + timedelta(days=2)

    reactivated = active.suspend(at=suspended_at).activate(at=reactivated_at)

    assert reactivated.joined_at == NOW
    assert reactivated.updated_at == reactivated_at


@pytest.mark.unit
def test_suspension_and_removal_take_access_away() -> None:
    active = build_active()

    suspended = active.suspend(at=NOW + timedelta(hours=1))
    removed = active.remove(at=NOW + timedelta(hours=1))

    assert suspended.grants_access is False
    assert removed.grants_access is False
    assert removed.removed_at == NOW + timedelta(hours=1)


@pytest.mark.unit
def test_removal_is_terminal_for_ordinary_actions() -> None:
    """Reinstating would silently restore whatever access existed before."""
    removed = build_active().remove(at=NOW + timedelta(hours=1))

    assert removed.status.is_terminal is True
    with pytest.raises(EntityInvariantError, match="cannot move from removed to active"):
        removed.activate(at=NOW + timedelta(hours=2))
    with pytest.raises(EntityInvariantError, match="cannot move from removed to suspended"):
        removed.suspend(at=NOW + timedelta(hours=2))
    with pytest.raises(EntityInvariantError, match="cannot move from removed to removed"):
        removed.remove(at=NOW + timedelta(hours=2))


@pytest.mark.unit
def test_an_invitation_cannot_be_suspended_directly() -> None:
    """There is nothing to suspend until access has been granted."""
    with pytest.raises(EntityInvariantError, match="cannot move from invited to suspended"):
        build_invitation().suspend(at=NOW)


@pytest.mark.unit
def test_the_allowed_transitions_are_the_declared_ones() -> None:
    """The lifecycle is data, so an illegal transition is a refusal and not a surprise."""
    for from_status, allowed in ALLOWED_TRANSITIONS.items():
        for to_status in MembershipStatus:
            if to_status is MembershipStatus.INVITED:
                # There is no transition back to invited: an invitation is a
                # creation act, and reinstating would need a new membership.
                continue
            membership = _membership_in_status(from_status)
            if to_status in allowed and to_status is not from_status:
                _apply_transition(membership, to_status, at=NOW + timedelta(hours=1))
            elif to_status not in allowed:
                with pytest.raises(EntityInvariantError):
                    _apply_transition(membership, to_status, at=NOW + timedelta(hours=1))


def _membership_in_status(status: MembershipStatus) -> TenantMembershipModel:
    if status is MembershipStatus.INVITED:
        return build_invitation()
    if status is MembershipStatus.ACTIVE:
        return build_active()
    if status is MembershipStatus.SUSPENDED:
        return build_active().suspend(at=NOW + timedelta(hours=1))
    return build_active().remove(at=NOW + timedelta(hours=1))


def _apply_transition(
    membership: TenantMembershipModel, to_status: MembershipStatus, *, at: datetime
) -> TenantMembershipModel:
    if to_status is MembershipStatus.ACTIVE:
        return membership.activate(at=at)
    if to_status is MembershipStatus.SUSPENDED:
        return membership.suspend(at=at)
    if to_status is MembershipStatus.REMOVED:
        return membership.remove(at=at)
    return membership.activate(at=at)


# ---------------------------------------------------------------------------
# Role changes
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_changing_a_role_is_recorded_and_normalized() -> None:
    membership = build_active(role_name="SALES")
    later = NOW + timedelta(days=7)

    promoted = membership.change_role(role_name="manager", at=later)

    assert promoted.role_name == "MANAGER"
    assert promoted.updated_at == later
    assert membership.role_name == "SALES"


@pytest.mark.unit
def test_an_unknown_role_change_is_rejected() -> None:
    with pytest.raises(EntityInvariantError, match="unknown role"):
        build_active().change_role(role_name="SUPERUSER", at=NOW)


@pytest.mark.unit
def test_a_removed_membership_cannot_be_given_a_role() -> None:
    removed = build_active().remove(at=NOW + timedelta(hours=1))

    with pytest.raises(EntityInvariantError, match="cannot be given a role"):
        removed.change_role(role_name="MANAGER", at=NOW + timedelta(hours=2))


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_audit_description_carries_the_decision_and_no_personal_data() -> None:
    description = build_active(role_name="INVENTORY").describe_for_audit()

    assert set(description) == {
        "membership_id",
        "tenant_id",
        "user_id",
        "role_name",
        "status",
    }
    assert description["role_name"] == "INVENTORY"
    assert description["status"] == "active"
