"""Tests for the inventory entities.

The ledger's arithmetic is the subject: `quantity_after = quantity_before +
quantity_delta` must hold by construction, a movement that changes nothing is not a
movement, and a receipt cannot have a negative quantity. The projection's rules are the
rest: reservations cannot exceed what exists, and the version only moves forward.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.inventory_model import (
    MAXIMUM_QUANTITY,
    InventoryModel,
)
from ahia.models.entities.inventory_movement_model import (
    MAXIMUM_NOTE_LENGTH,
    InventoryMovementModel,
    MovementType,
)
from ahia.models.entities.negative_stock_policy import (
    DEFAULT_NEGATIVE_STOCK_POLICY,
    NegativeStockPolicy,
    parse_negative_stock_policy,
)

NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)


def build_inventory(**overrides: object) -> InventoryModel:
    parameters: dict[str, object] = {
        "inventory_id": uuid4(),
        "tenant_id": uuid4(),
        "product_id": uuid4(),
        "now": NOW,
    }
    parameters.update(overrides)
    return InventoryModel.empty(**parameters)  # type: ignore[arg-type]


def build_movement(**overrides: object) -> InventoryMovementModel:
    parameters: dict[str, object] = {
        "movement_id": uuid4(),
        "tenant_id": uuid4(),
        "product_id": uuid4(),
        "movement_type": MovementType.STOCK_RECEIVED,
        "quantity_delta": Decimal("5.000"),
        "quantity_before": Decimal("10.000"),
        "actor_id": uuid4(),
        "now": NOW,
    }
    parameters.update(overrides)
    return InventoryMovementModel.record(**parameters)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The policy vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_default_policy_refuses_negative_stock() -> None:
    """A shop that oversold has a problem, and this is the cheapest moment to see it."""
    assert DEFAULT_NEGATIVE_STOCK_POLICY is NegativeStockPolicy.BLOCK_NEGATIVE_STOCK
    assert DEFAULT_NEGATIVE_STOCK_POLICY.refuses_the_movement is True


@pytest.mark.unit
@pytest.mark.parametrize("policy", list(NegativeStockPolicy))
def test_every_policy_describes_itself(policy: NegativeStockPolicy) -> None:
    assert policy.describe()


@pytest.mark.unit
def test_a_permissive_policy_is_recognisable_as_such() -> None:
    assert NegativeStockPolicy.ALLOW_WITH_WARNING.flags_the_movement is True
    assert NegativeStockPolicy.ALLOW_WITH_WARNING.refuses_the_movement is False
    assert NegativeStockPolicy.ALLOW_NEGATIVE_STOCK.refuses_the_movement is False
    assert NegativeStockPolicy.ALLOW_NEGATIVE_STOCK.flags_the_movement is False


@pytest.mark.unit
@pytest.mark.parametrize("policy", list(NegativeStockPolicy))
def test_a_policy_round_trips_through_its_stored_name(policy: NegativeStockPolicy) -> None:
    assert parse_negative_stock_policy(policy.value) is policy


@pytest.mark.unit
def test_an_unknown_policy_is_refused_rather_than_defaulted() -> None:
    """Defaulting would apply a policy the business did not choose."""
    with pytest.raises(ValueError, match="not a negative stock policy"):
        parse_negative_stock_policy("MAYBE_LATER")


# ---------------------------------------------------------------------------
# The projection
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_product_nobody_has_counted_starts_at_zero() -> None:
    inventory = build_inventory()

    assert inventory.quantity_on_hand == Decimal("0.000")
    assert inventory.reserved_quantity == Decimal("0.000")
    assert inventory.version == 1
    assert inventory.is_out_of_stock() is True
    assert inventory.is_overdrawn() is False


@pytest.mark.unit
def test_a_movement_changes_the_quantity_and_the_version() -> None:
    inventory = build_inventory().with_movement(delta=Decimal("12.000"), at=LATER)

    assert inventory.quantity_on_hand == Decimal("12.000")
    assert inventory.version == 2
    assert inventory.updated_at == LATER


@pytest.mark.unit
def test_a_movement_of_nothing_changes_nothing() -> None:
    """Including the version: a no-op that bumped it would invalidate every client."""
    inventory = build_inventory()

    assert inventory.with_movement(delta=Decimal("0.000"), at=LATER) == inventory


@pytest.mark.unit
def test_available_quantity_excludes_what_is_promised() -> None:
    inventory = build_inventory().with_movement(delta=Decimal("10.000"), at=LATER)

    promised = inventory.with_reservation(quantity=Decimal("4.000"), at=LATER)

    assert promised.quantity_on_hand == Decimal("10.000"), "the stock is still there"
    assert promised.available_quantity == Decimal("6.000")
    assert promised.is_out_of_stock() is False


@pytest.mark.unit
def test_a_reservation_can_be_given_back() -> None:
    inventory = build_inventory().with_movement(delta=Decimal("10.000"), at=LATER)
    promised = inventory.with_reservation(quantity=Decimal("4.000"), at=LATER)

    released = promised.with_reservation_released(quantity=Decimal("4.000"), at=LATER)

    assert released.reserved_quantity == Decimal("0.000")
    assert released.available_quantity == Decimal("10.000")


@pytest.mark.unit
def test_releasing_more_than_is_reserved_is_refused() -> None:
    """It would free stock that was never promised, which is a miscount dressed as a release."""
    inventory = build_inventory().with_movement(delta=Decimal("10.000"), at=LATER)

    with pytest.raises(EntityInvariantError, match="more than is reserved"):
        inventory.with_reservation_released(quantity=Decimal("1.000"), at=LATER)


@pytest.mark.unit
@pytest.mark.parametrize("quantity", [Decimal("0.000"), Decimal("-1.000")])
def test_a_reservation_must_be_positive(quantity: Decimal) -> None:
    inventory = build_inventory()

    with pytest.raises(EntityInvariantError, match="positive quantity"):
        inventory.with_reservation(quantity=quantity, at=LATER)


@pytest.mark.unit
def test_the_projection_permits_a_negative_result_and_says_so() -> None:
    """Whether that is acceptable is the business's decision, applied by the service."""
    overdrawn = build_inventory().with_movement(delta=Decimal("-3.000"), at=LATER)

    assert overdrawn.quantity_on_hand == Decimal("-3.000")
    assert overdrawn.is_overdrawn() is True


@pytest.mark.unit
def test_a_negative_reservation_is_refused() -> None:
    inventory = build_inventory()
    with pytest.raises(EntityInvariantError, match="reserved_quantity is negative"):
        InventoryModel(
            id=inventory.id,
            tenant_id=inventory.tenant_id,
            product_id=inventory.product_id,
            quantity_on_hand=Decimal("1.000"),
            reserved_quantity=Decimal("-1.000"),
            version=2,
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.unit
def test_the_version_only_moves_forward() -> None:
    inventory = build_inventory()
    with pytest.raises(EntityInvariantError, match="version starts at 1"):
        InventoryModel(
            id=inventory.id,
            tenant_id=inventory.tenant_id,
            product_id=inventory.product_id,
            quantity_on_hand=Decimal("1.000"),
            version=0,
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.unit
def test_a_quantity_with_too_many_places_is_refused() -> None:
    inventory = build_inventory()
    with pytest.raises(EntityInvariantError, match="more than three decimal places"):
        InventoryModel(
            id=inventory.id,
            tenant_id=inventory.tenant_id,
            product_id=inventory.product_id,
            quantity_on_hand=Decimal("1.0001"),
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.unit
def test_a_float_quantity_is_refused() -> None:
    inventory = build_inventory()
    with pytest.raises(EntityInvariantError, match="must be a Decimal"):
        InventoryModel(
            id=inventory.id,
            tenant_id=inventory.tenant_id,
            product_id=inventory.product_id,
            quantity_on_hand=1.5,  # type: ignore[arg-type]
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.unit
def test_an_absurd_quantity_is_refused() -> None:
    inventory = build_inventory()
    with pytest.raises(EntityInvariantError, match="exceeds"):
        InventoryModel(
            id=inventory.id,
            tenant_id=inventory.tenant_id,
            product_id=inventory.product_id,
            quantity_on_hand=MAXIMUM_QUANTITY + Decimal("1"),
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.unit
@pytest.mark.parametrize("field_name", ["created_at", "updated_at"])
def test_naive_timestamps_are_rejected(field_name: str) -> None:
    inventory = build_inventory()
    timestamps: dict[str, datetime] = {"created_at": NOW, "updated_at": NOW}
    timestamps[field_name] = datetime(2026, 9, 13, 9, 30)  # noqa: DTZ001 - under test

    with pytest.raises(EntityInvariantError, match="naive datetime"):
        InventoryModel(
            id=inventory.id,
            tenant_id=inventory.tenant_id,
            product_id=inventory.product_id,
            quantity_on_hand=Decimal("1.000"),
            created_at=timestamps["created_at"],
            updated_at=timestamps["updated_at"],
        )


@pytest.mark.unit
def test_the_projection_is_immutable() -> None:
    inventory = build_inventory()
    with pytest.raises(FrozenInstanceError):
        inventory.quantity_on_hand = Decimal("99.000")  # type: ignore[misc]


@pytest.mark.unit
def test_the_audit_description_carries_numbers_and_no_note() -> None:
    inventory = build_inventory().with_movement(delta=Decimal("5.000"), at=LATER)

    description = inventory.describe_for_audit()

    assert set(description) == {
        "inventory_id",
        "tenant_id",
        "product_id",
        "quantity_on_hand",
        "reserved_quantity",
        "version",
        "is_overdrawn",
    }


# ---------------------------------------------------------------------------
# The movement
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_factory_derives_the_resulting_quantity() -> None:
    movement = build_movement(quantity_before=Decimal("10.000"), quantity_delta=Decimal("5.000"))

    assert movement.quantity_after == Decimal("15.000")
    assert movement.quantity_after == movement.quantity_before + movement.quantity_delta


@pytest.mark.unit
def test_a_negative_delta_derives_a_smaller_result() -> None:
    movement = build_movement(
        movement_type=MovementType.SALE,
        quantity_before=Decimal("10.000"),
        quantity_delta=Decimal("-3.000"),
    )

    assert movement.quantity_after == Decimal("7.000")


@pytest.mark.unit
def test_the_invariant_is_enforced_on_a_hand_built_movement() -> None:
    """The factory cannot produce a disagreement, so this is the mapper's guard."""
    with pytest.raises(EntityInvariantError, match="must equal quantity_before"):
        InventoryMovementModel(
            id=uuid4(),
            tenant_id=uuid4(),
            product_id=uuid4(),
            movement_type=MovementType.STOCK_RECEIVED,
            quantity_delta=Decimal("5.000"),
            quantity_before=Decimal("10.000"),
            quantity_after=Decimal("99.000"),
            actor_id=uuid4(),
            occurred_at=NOW,
            created_at=NOW,
        )


@pytest.mark.unit
def test_a_movement_that_changes_nothing_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="not a movement"):
        build_movement(quantity_delta=Decimal("0.000"))


@pytest.mark.unit
@pytest.mark.parametrize(
    "movement_type",
    [
        MovementType.STOCK_INITIALIZED,
        MovementType.STOCK_RECEIVED,
        MovementType.RETURN,
        MovementType.SHIPMENT_IN,
    ],
)
def test_an_inbound_movement_cannot_be_negative(movement_type: MovementType) -> None:
    with pytest.raises(EntityInvariantError, match="cannot have a negative quantity"):
        build_movement(movement_type=movement_type, quantity_delta=Decimal("-1.000"))


@pytest.mark.unit
@pytest.mark.parametrize(
    "movement_type",
    [MovementType.SALE, MovementType.DAMAGE, MovementType.SHIPMENT_OUT],
)
def test_an_outbound_movement_cannot_be_positive(movement_type: MovementType) -> None:
    with pytest.raises(EntityInvariantError, match="cannot have a positive quantity"):
        build_movement(movement_type=movement_type, quantity_delta=Decimal("1.000"))


@pytest.mark.unit
@pytest.mark.parametrize("movement_type", [MovementType.ADJUSTMENT, MovementType.TRANSFER])
def test_a_correcting_movement_may_go_either_way(movement_type: MovementType) -> None:
    """A correction is not a direction: a count can come out higher or lower."""
    assert build_movement(
        movement_type=movement_type, quantity_delta=Decimal("2.000")
    ).quantity_delta == Decimal("2.000")
    assert build_movement(
        movement_type=movement_type, quantity_delta=Decimal("-2.000")
    ).quantity_delta == Decimal("-2.000")


@pytest.mark.unit
def test_the_overdraw_is_visible_on_the_movement() -> None:
    movement = build_movement(
        movement_type=MovementType.SALE,
        quantity_before=Decimal("2.000"),
        quantity_delta=Decimal("-3.000"),
    )

    assert movement.is_overdraw() is True
    assert movement.describe_for_audit()["is_overdraw"] == "true"


@pytest.mark.unit
def test_a_reference_needs_a_type_to_be_interpretable() -> None:
    """An identifier with no vocabulary is unreadable a month later."""
    with pytest.raises(EntityInvariantError, match="needs a reference_type"):
        build_movement(reference_id=uuid4())


@pytest.mark.unit
def test_a_reference_type_alone_is_allowed() -> None:
    """A batch reference can exist before the batch has an identifier."""
    movement = build_movement(reference_type="stock_take")

    assert movement.reference_type == "stock_take"
    assert movement.reference_id is None


@pytest.mark.unit
def test_a_blank_reference_type_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="reference_type is empty"):
        build_movement(reference_type="   ")


@pytest.mark.unit
def test_an_overlong_note_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="note exceeds"):
        build_movement(note="x" * (MAXIMUM_NOTE_LENGTH + 1))


@pytest.mark.unit
def test_a_note_is_trimmed() -> None:
    assert build_movement(note="  counted by hand  ").note == "counted by hand"


@pytest.mark.unit
def test_the_audit_description_carries_the_reference_but_never_the_note() -> None:
    reference_id = uuid4()
    movement = build_movement(
        reference_type="sale",
        reference_id=reference_id,
        note="customer asked for a discount",
    )

    description = movement.describe_for_audit()

    assert description["reference_type"] == "sale"
    assert description["reference_id"] == str(reference_id)
    assert "discount" not in repr(description)


@pytest.mark.unit
def test_every_movement_type_the_specification_names_exists() -> None:
    """A missing member would make a real movement impossible to record."""
    assert {member.value for member in MovementType} == {
        "STOCK_INITIALIZED",
        "STOCK_RECEIVED",
        "SALE",
        "RETURN",
        "DAMAGE",
        "ADJUSTMENT",
        "TRANSFER",
        "SHIPMENT_OUT",
        "SHIPMENT_IN",
    }


@pytest.mark.unit
def test_a_movement_carries_the_tenant_and_the_actor() -> None:
    tenant_id = uuid4()
    actor_id = uuid4()
    movement = build_movement(tenant_id=tenant_id, actor_id=actor_id)

    assert movement.tenant_id == tenant_id
    assert movement.actor_id == actor_id
    assert isinstance(movement.product_id, UUID)
