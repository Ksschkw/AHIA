"""Tests for the audit event entity.

The subject is what a trail may contain. An audit trail earns its place by being the record
that survives, which means two things have to hold: every event carries the context that makes
it answerable later, and nothing enters it that would make the trail itself a liability.

Secrets never enter the trail
    `detail` is a mapping of short strings, and a key that names a credential - password, token,
    secret, key - is refused at construction. The trail is read by more people than the table it
    describes, so a secret in it is a secret with a wider audience and a longer retention.

Vocabulary is shaped, not free text
    `action` and `entity_type` are lower-case words joined by underscores, because a trail is
    grouped and filtered by them and `Record Expense` beside `record_expense` is two actions to
    every report that reads it.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.audit_event_model import (
    MAXIMUM_ACTION_LENGTH,
    MAXIMUM_DETAIL_KEYS,
    MAXIMUM_DETAIL_VALUE_LENGTH,
    AuditEventModel,
    AuditOutcome,
)

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def build_event(**overrides: object) -> AuditEventModel:
    parameters: dict[str, object] = {
        "event_id": uuid4(),
        "tenant_id": uuid4(),
        "action": "record_expense",
        "entity_type": "expense",
        "now": NOW,
        "actor_id": uuid4(),
        "detail": {"expense_id": str(uuid4()), "category": "TRANSPORT"},
    }
    parameters.update(overrides)
    return AuditEventModel.record(**parameters)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# What an event carries
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_an_event_carries_the_tenant_the_actor_the_device_and_the_moment() -> None:
    actor_id = uuid4()
    tenant_id = uuid4()
    device_id = uuid4()
    operation_id = uuid4()

    event = build_event(
        actor_id=actor_id,
        tenant_id=tenant_id,
        device_id=device_id,
        operation_id=operation_id,
    )

    assert event.actor_id == actor_id
    assert event.tenant_id == tenant_id
    assert event.device_id == device_id
    assert event.operation_id == operation_id
    assert event.occurred_at == NOW
    assert event.outcome is AuditOutcome.SUCCEEDED


@pytest.mark.unit
def test_an_event_without_an_actor_is_allowed_because_the_system_acts_too() -> None:
    """The permission registry being provisioned has no person behind it."""
    event = build_event(actor_id=None)

    assert event.actor_id is None
    assert "actor_id" not in event.as_log_fields()


@pytest.mark.unit
def test_a_refusal_is_an_event_with_an_outcome_not_a_missing_row() -> None:
    event = build_event(outcome=AuditOutcome.DENIED, entity_id=None)

    assert event.is_refusal() is True
    assert event.outcome is AuditOutcome.DENIED


@pytest.mark.unit
def test_a_successful_event_is_not_a_refusal() -> None:
    assert build_event().is_refusal() is False


@pytest.mark.unit
def test_the_log_fields_carry_identifiers_and_no_detail() -> None:
    event = build_event(detail={"expense_id": "abc"})

    fields = event.as_log_fields()

    assert fields["action"] == "record_expense"
    assert fields["outcome"] == "SUCCEEDED"
    assert "detail" not in fields
    assert "expense_id" not in str(fields)


# ---------------------------------------------------------------------------
# What must never enter the trail
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "key",
    ["password", "user_password", "refresh_token", "api_key", "authorization_header", "pin"],
)
def test_a_detail_key_that_names_a_credential_is_refused(key: str) -> None:
    with pytest.raises(EntityInvariantError, match="names a credential"):
        build_event(detail={key: "value"})


@pytest.mark.unit
def test_a_detail_value_that_is_not_a_short_string_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="must be a string"):
        build_event(detail={"amount": 3500})

    with pytest.raises(EntityInvariantError, match="exceeds"):
        build_event(detail={"note": "x" * (MAXIMUM_DETAIL_VALUE_LENGTH + 1)})


@pytest.mark.unit
def test_detail_is_bounded() -> None:
    too_many = {f"key_{index}": "value" for index in range(MAXIMUM_DETAIL_KEYS + 1)}

    with pytest.raises(EntityInvariantError, match="exceeds"):
        build_event(detail=too_many)


@pytest.mark.unit
def test_a_detail_key_that_is_not_shaped_like_a_name_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="lower-case words"):
        build_event(detail={"Expense ID": "abc"})


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_an_action_that_is_not_a_use_case_name_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="lower-case words"):
        build_event(action="Record Expense")


@pytest.mark.unit
def test_an_empty_action_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="action is required"):
        build_event(action="   ")


@pytest.mark.unit
def test_an_action_longer_than_the_bound_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="exceeds"):
        build_event(action="a" * (MAXIMUM_ACTION_LENGTH + 1))


@pytest.mark.unit
def test_an_outcome_outside_the_vocabulary_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="AuditOutcome"):
        build_event(outcome="SUCCEEDED")


@pytest.mark.unit
def test_a_naive_timestamp_is_refused() -> None:
    """A naive timestamp has no meaning across the clients this product serves."""
    naive = datetime(2026, 9, 14, 12, 0)  # noqa: DTZ001 - the value under test

    with pytest.raises(EntityInvariantError, match="naive datetime"):
        build_event(now=naive)


@pytest.mark.unit
def test_an_event_is_immutable() -> None:
    event = build_event()

    with pytest.raises(FrozenInstanceError):
        event.action = "something_else"  # type: ignore[misc]
