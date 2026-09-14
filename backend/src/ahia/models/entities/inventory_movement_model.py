"""The movement ledger: the authoritative history of a product's stock.

Stock is not a number that gets edited. It is the sum of everything that has happened to
it, and this entity is one entry in that history. The number a business sees on a screen
is a *projection* - `InventoryModel` - derived from these entries and never the other way
round.

**The invariant, and where it is computed.**

    quantity_after = quantity_before + quantity_delta

The service reads `quantity_before` from the projection row under a lock, hands it to the
factory here, and the entity computes `quantity_after` itself. A caller cannot supply all
three and get them to disagree: two of the values determine the third, so the invariant
holds by construction rather than by a check that somebody might forget to run.

**Why the entries are never deleted or edited.** A correction is another movement. That is
the accounting rule, and it is also the only way a dispute can be settled: "the count was
wrong on Tuesday, here is the correction on Wednesday" is auditable, while an edited row
is a history that cannot be trusted. The table enforces it with a trigger.

**The reference fields point at whatever caused the movement** - a sale, an expense, a
sync operation - without this entity knowing what those are. `reference_type` is a
vocabulary word (`sale`, `expense`, `stock_take`) and `reference_id` identifies the record
in that vocabulary's table. A foreign key per possible cause would make this table depend
on every domain that can move stock, which is the coupling an append-only ledger exists to
avoid.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.money import (
    MAXIMUM_QUANTITY,
    QUANTITY_PLACES,
    ZERO_QUANTITY,
)

MAXIMUM_REFERENCE_TYPE_LENGTH: Final[int] = 64
MAXIMUM_NOTE_LENGTH: Final[int] = 1_000


class MovementType(StrEnum):
    """Every way stock can change, and nothing else.

    A closed set: an unknown movement type means either a feature nobody registered here
    or a value that arrived from somewhere it should not have, and both are worse than a
    refused write.
    """

    STOCK_INITIALIZED = "STOCK_INITIALIZED"
    STOCK_RECEIVED = "STOCK_RECEIVED"
    SALE = "SALE"
    RETURN = "RETURN"
    DAMAGE = "DAMAGE"
    ADJUSTMENT = "ADJUSTMENT"
    TRANSFER = "TRANSFER"
    SHIPMENT_OUT = "SHIPMENT_OUT"
    SHIPMENT_IN = "SHIPMENT_IN"


#: Movements that take stock out of the business rather than bringing it in or correcting
#: it. Used to decide whether a delta's sign makes sense for the type - a receipt with a
#: negative quantity is a mistake even when negative stock is allowed.
_INBOUND_TYPES: Final[frozenset[MovementType]] = frozenset(
    {
        MovementType.STOCK_INITIALIZED,
        MovementType.STOCK_RECEIVED,
        MovementType.RETURN,
        MovementType.SHIPMENT_IN,
    }
)
_OUTBOUND_TYPES: Final[frozenset[MovementType]] = frozenset(
    {
        MovementType.SALE,
        MovementType.DAMAGE,
        MovementType.SHIPMENT_OUT,
    }
)


@dataclass(frozen=True, slots=True)
class InventoryMovementModel:
    """One entry in a product's stock history."""

    id: UUID
    tenant_id: UUID
    product_id: UUID
    movement_type: MovementType
    quantity_delta: Decimal
    quantity_before: Decimal
    quantity_after: Decimal
    actor_id: UUID
    occurred_at: datetime
    created_at: datetime
    reference_type: str | None = None
    reference_id: UUID | None = None
    device_id: UUID | None = None
    operation_id: UUID | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.occurred_at, field_name="occurred_at", movement_id=self.id)
        _require_aware(self.created_at, field_name="created_at", movement_id=self.id)

        for field_name, value in (
            ("quantity_delta", self.quantity_delta),
            ("quantity_before", self.quantity_before),
            ("quantity_after", self.quantity_after),
        ):
            _require_quantity(value, field_name=field_name, movement_id=self.id)

        if self.quantity_after != self.quantity_before + self.quantity_delta:
            # The one invariant of the whole ledger. Reaching here means a caller built
            # the entity by hand with three values that do not agree, because the factory
            # derives the third.
            raise EntityInvariantError(
                operation="record_inventory_movement",
                entity="inventory_movement",
                identifier=str(self.id),
                detail=(
                    "quantity_after must equal quantity_before + quantity_delta: "
                    f"{self.quantity_after} != {self.quantity_before} + {self.quantity_delta}"
                ),
            )

        if self.quantity_delta == ZERO_QUANTITY:
            raise EntityInvariantError(
                operation="record_inventory_movement",
                entity="inventory_movement",
                identifier=str(self.id),
                detail="a movement that changes nothing is not a movement",
            )

        if self.movement_type in _INBOUND_TYPES and self.quantity_delta < ZERO_QUANTITY:
            raise EntityInvariantError(
                operation="record_inventory_movement",
                entity="inventory_movement",
                identifier=str(self.id),
                detail=f"{self.movement_type.value} cannot have a negative quantity",
            )
        if self.movement_type in _OUTBOUND_TYPES and self.quantity_delta > ZERO_QUANTITY:
            raise EntityInvariantError(
                operation="record_inventory_movement",
                entity="inventory_movement",
                identifier=str(self.id),
                detail=f"{self.movement_type.value} cannot have a positive quantity",
            )

        if self.reference_type is not None:
            trimmed = self.reference_type.strip()
            if not trimmed:
                raise EntityInvariantError(
                    operation="record_inventory_movement",
                    entity="inventory_movement",
                    identifier=str(self.id),
                    detail="reference_type is empty; use None instead",
                )
            if len(trimmed) > MAXIMUM_REFERENCE_TYPE_LENGTH:
                raise EntityInvariantError(
                    operation="record_inventory_movement",
                    entity="inventory_movement",
                    identifier=str(self.id),
                    detail=(f"reference_type exceeds {MAXIMUM_REFERENCE_TYPE_LENGTH} characters"),
                )
        if self.reference_id is not None and self.reference_type is None:
            # An identifier with no vocabulary is unreadable a month later: nobody can
            # tell whether it names a sale, an expense or a sync batch.
            raise EntityInvariantError(
                operation="record_inventory_movement",
                entity="inventory_movement",
                identifier=str(self.id),
                detail="reference_id needs a reference_type to be interpretable",
            )

        if self.note is not None and len(self.note) > MAXIMUM_NOTE_LENGTH:
            raise EntityInvariantError(
                operation="record_inventory_movement",
                entity="inventory_movement",
                identifier=str(self.id),
                detail=f"note exceeds {MAXIMUM_NOTE_LENGTH} characters",
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def record(
        cls,
        *,
        movement_id: UUID,
        tenant_id: UUID,
        product_id: UUID,
        movement_type: MovementType,
        quantity_delta: Decimal,
        quantity_before: Decimal,
        actor_id: UUID,
        now: datetime,
        reference_type: str | None = None,
        reference_id: UUID | None = None,
        device_id: UUID | None = None,
        operation_id: UUID | None = None,
        note: str | None = None,
    ) -> InventoryMovementModel:
        """Record a movement, deriving the resulting quantity.

        The caller supplies what happened and where it started; the entity derives where
        it ended. That is the whole reason this factory exists rather than a plain
        constructor call at each call site.
        """
        return cls(
            id=movement_id,
            tenant_id=tenant_id,
            product_id=product_id,
            movement_type=movement_type,
            quantity_delta=quantity_delta,
            quantity_before=quantity_before,
            quantity_after=quantity_before + quantity_delta,
            actor_id=actor_id,
            occurred_at=now,
            created_at=now,
            reference_type=reference_type.strip() if reference_type else None,
            reference_id=reference_id,
            device_id=device_id,
            operation_id=operation_id,
            note=note.strip() if note else None,
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    def is_overdraw(self) -> bool:
        """Return True when this movement took the product below zero.

        Not an error: it is the fact a business with a permissive policy needs to see.
        Flagging it here rather than comparing values at each call site is what makes
        "which sales overdrew stock" answerable from the ledger alone.
        """
        return self.quantity_after < ZERO_QUANTITY

    def describe_for_audit(self) -> dict[str, str]:
        """Return what an audit line needs, and no free text.

        The note is excluded: it is written by a person about their own business, and an
        audit record that copies free text into every log line turns a stock adjustment
        into a place where customer names appear.
        """
        description = {
            "movement_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "product_id": str(self.product_id),
            "movement_type": self.movement_type.value,
            "quantity_delta": str(self.quantity_delta),
            "quantity_after": str(self.quantity_after),
            "actor_id": str(self.actor_id),
            "is_overdraw": "true" if self.is_overdraw() else "false",
        }
        if self.reference_type is not None and self.reference_id is not None:
            description["reference_type"] = self.reference_type
            description["reference_id"] = str(self.reference_id)
        return description


def _require_quantity(value: object, *, field_name: str, movement_id: UUID) -> None:
    """Raise unless the value is a Decimal quantity this table can hold."""
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise EntityInvariantError(
            operation="record_inventory_movement",
            entity="inventory_movement",
            identifier=str(movement_id),
            detail=f"{field_name} must be a Decimal, not {type(value).__name__}",
        )
    if not value.is_finite():
        raise EntityInvariantError(
            operation="record_inventory_movement",
            entity="inventory_movement",
            identifier=str(movement_id),
            detail=f"{field_name} is not a finite number",
        )
    if value.quantize(QUANTITY_PLACES) != value:
        raise EntityInvariantError(
            operation="record_inventory_movement",
            entity="inventory_movement",
            identifier=str(movement_id),
            detail=f"{field_name} has more than three decimal places",
        )
    if abs(value) > MAXIMUM_QUANTITY:
        raise EntityInvariantError(
            operation="record_inventory_movement",
            entity="inventory_movement",
            identifier=str(movement_id),
            detail=f"{field_name} exceeds {MAXIMUM_QUANTITY} in magnitude",
        )


def _require_aware(moment: datetime, *, field_name: str, movement_id: UUID) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="record_inventory_movement",
            entity="inventory_movement",
            identifier=str(movement_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
