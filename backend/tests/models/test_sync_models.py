"""Tests for the offline synchronisation entities.

Three subjects, one per entity.

The change feed's order. A sequence is what lets a device catch up without trusting a clock, so
the entity refuses a sequence that could not have come from the server, and the vocabulary is
shaped so a client cannot be told about an entity under a name the feed has never used.

The cursor's direction. A cursor moves forward or not at all: moving it back makes a device
re-apply changes it has already applied, which on a sales device means the expensive kind of
mistake.

The operation's answer. An applied operation must name the record it produced, or a retry cannot
be told what already happened, and the detail it carries is bounded short strings - there is no
place in this record for a payload.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.sync_change_model import (
    MAXIMUM_ENTITY_TYPE_LENGTH,
    ChangeType,
    SyncChangeModel,
)
from ahia.models.entities.sync_cursor_model import (
    FIRST_SEQUENCE,
    SyncCursorModel,
)
from ahia.models.entities.sync_operation_model import (
    MAXIMUM_DETAIL_KEYS,
    SyncOperationModel,
    SyncOperationStatus,
)

NOW = datetime(2026, 9, 14, 16, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)


def build_change(**overrides: object) -> SyncChangeModel:
    parameters: dict[str, object] = {
        "change_id": uuid4(),
        "tenant_id": uuid4(),
        "change_sequence": 1001,
        "entity_type": "product",
        "entity_id": uuid4(),
        "change_type": ChangeType.CREATED,
        "now": NOW,
    }
    parameters.update(overrides)
    return SyncChangeModel.for_record(**parameters)  # type: ignore[arg-type]


def build_cursor(**overrides: object) -> SyncCursorModel:
    parameters: dict[str, object] = {
        "cursor_id": uuid4(),
        "tenant_id": uuid4(),
        "device_id": uuid4(),
        "now": NOW,
    }
    parameters.update(overrides)
    return SyncCursorModel.starting_at(**parameters)  # type: ignore[arg-type]


def build_operation(**overrides: object) -> SyncOperationModel:
    parameters: dict[str, object] = {
        "operation_id": uuid4(),
        "tenant_id": uuid4(),
        "operation_type": "complete_sale",
        "status": SyncOperationStatus.APPLIED,
        "now": NOW,
        "device_id": uuid4(),
        "entity_type": "sale",
        "entity_id": uuid4(),
    }
    parameters.update(overrides)
    return SyncOperationModel.record(**parameters)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The change feed
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_change_carries_the_order_the_server_assigned() -> None:
    change = build_change(change_sequence=1001)

    assert change.change_sequence == 1001
    assert change.occurred_at == NOW
    assert change.describe_for_audit()["change_sequence"] == "1001"


@pytest.mark.unit
def test_a_sequence_that_could_not_have_come_from_the_server_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="must be positive"):
        build_change(change_sequence=0)


@pytest.mark.unit
def test_an_entity_type_that_is_not_a_vocabulary_word_is_refused() -> None:
    """The feed and the trail name entities the same way, or a client misses changes."""
    with pytest.raises(EntityInvariantError, match="lower-case words"):
        build_change(entity_type="Product")

    with pytest.raises(EntityInvariantError, match="exceeds"):
        build_change(entity_type="p" * (MAXIMUM_ENTITY_TYPE_LENGTH + 1))


@pytest.mark.unit
def test_a_change_type_outside_the_vocabulary_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="ChangeType"):
        build_change(change_type="CREATED")


@pytest.mark.unit
def test_a_deletion_is_a_change_like_any_other() -> None:
    change = build_change(change_type=ChangeType.DELETED)

    assert change.change_type is ChangeType.DELETED


@pytest.mark.unit
def test_a_naive_timestamp_is_refused() -> None:
    naive = datetime(2026, 9, 14, 16, 0)  # noqa: DTZ001 - the value under test

    with pytest.raises(EntityInvariantError, match="naive datetime"):
        build_change(now=naive)


@pytest.mark.unit
def test_a_change_is_immutable() -> None:
    change = build_change()

    with pytest.raises(FrozenInstanceError):
        change.change_sequence = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# The cursor
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_device_that_has_never_synchronized_starts_at_zero() -> None:
    cursor = build_cursor()

    assert cursor.last_server_sequence == FIRST_SEQUENCE
    assert cursor.updated_at == NOW


@pytest.mark.unit
def test_a_cursor_advances_and_keeps_the_moment_it_did() -> None:
    cursor = build_cursor()

    advanced = cursor.advanced_to(sequence=1001, at=LATER)

    assert advanced.last_server_sequence == 1001
    assert advanced.updated_at == LATER
    assert cursor.last_server_sequence == FIRST_SEQUENCE, "the original is unchanged"


@pytest.mark.unit
def test_a_cursor_cannot_move_backwards() -> None:
    """Moving it back makes a device apply changes it has already applied."""
    cursor = build_cursor(last_server_sequence=1001)

    with pytest.raises(EntityInvariantError, match="cannot move backwards"):
        cursor.advanced_to(sequence=1000, at=LATER)


@pytest.mark.unit
def test_advancing_to_the_same_sequence_changes_nothing() -> None:
    cursor = build_cursor(last_server_sequence=1001)

    again = cursor.advanced_to(sequence=1001, at=LATER)

    assert again.updated_at == NOW, "an unchanged cursor is not touched"


@pytest.mark.unit
def test_a_negative_sequence_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="cannot be negative"):
        build_cursor(last_server_sequence=-1)


@pytest.mark.unit
def test_a_naive_cursor_timestamp_is_refused() -> None:
    naive = datetime(2026, 9, 14, 16, 0)  # noqa: DTZ001 - the value under test

    with pytest.raises(EntityInvariantError, match="naive datetime"):
        build_cursor(now=naive)


# ---------------------------------------------------------------------------
# The operation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_an_applied_operation_names_the_record_it_produced() -> None:
    operation = build_operation()

    assert operation.is_settled() is True
    assert operation.entity_type == "sale"
    assert operation.describe_for_audit()["status"] == "APPLIED"


@pytest.mark.unit
def test_an_applied_operation_without_a_record_is_refused() -> None:
    """Otherwise a retry cannot be told what the first attempt already did."""
    with pytest.raises(EntityInvariantError, match="must name the kind of record"):
        build_operation(entity_type=None, entity_id=None)


@pytest.mark.unit
def test_a_rejected_operation_needs_no_record() -> None:
    operation = build_operation(
        status=SyncOperationStatus.REJECTED,
        entity_type=None,
        entity_id=None,
        detail={"reason": "permission_absent"},
    )

    assert operation.is_settled() is False
    assert operation.detail == {"reason": "permission_absent"}


@pytest.mark.unit
def test_a_replayed_operation_is_settled() -> None:
    assert build_operation(status=SyncOperationStatus.REPLAYED).is_settled() is True


@pytest.mark.unit
def test_an_operation_type_that_is_not_a_use_case_name_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="lower-case words"):
        build_operation(operation_type="Complete Sale")


@pytest.mark.unit
def test_a_status_outside_the_vocabulary_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="SyncOperationStatus"):
        build_operation(status="APPLIED")


@pytest.mark.unit
def test_the_detail_is_bounded_and_shaped() -> None:
    with pytest.raises(EntityInvariantError, match="exceeds"):
        build_operation(
            detail={f"key_{index}": "value" for index in range(MAXIMUM_DETAIL_KEYS + 1)}
        )

    with pytest.raises(EntityInvariantError, match="must be a string"):
        build_operation(detail={"amount": 3500})

    with pytest.raises(EntityInvariantError, match="lower-case words"):
        build_operation(detail={"Sale Id": "abc"})


@pytest.mark.unit
def test_the_log_fields_carry_no_payload() -> None:
    operation = build_operation(detail={"receipt_number": "OBI-000001"})

    fields = operation.describe_for_audit()

    assert "receipt_number" not in str(fields)
    assert fields["operation_type"] == "complete_sale"
    assert fields["entity_type"] == "sale"


@pytest.mark.unit
def test_a_naive_operation_timestamp_is_refused() -> None:
    naive = datetime(2026, 9, 14, 16, 0)  # noqa: DTZ001 - the value under test

    with pytest.raises(EntityInvariantError, match="naive datetime"):
        build_operation(now=naive)
