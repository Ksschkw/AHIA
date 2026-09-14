"""The inventory projection: what a business believes it has right now.

**This is a projection, not the truth.** The truth is the movement ledger, and this entity
is the running total the ledger produces - kept because summing a year of movements every
time somebody opens a product page is not a screen anybody will use. The moment the two
disagree, the ledger is right and this number is stale.

**Two quantities, and why they are separate.**

    quantity_on_hand     what is physically in the shop
    reserved_quantity    what has been promised but not yet handed over

Subtracting one from the other gives the number a new sale may use. Keeping them apart is
what lets a business sell stock it has promised to somebody else without pretending the
stock is not there - a single "available" number cannot answer "which order is this for".
Reservations are not implemented until sales arrive (M12); the column exists now because a
projection that has to be migrated to hold a second quantity is a projection that was
wrong when it was written.

**The version is not decoration.** Every movement increments it, which is what an offline
client sends back to say "I was working from version 7". A client whose version is stale
learns that somebody else moved stock in the meantime, which is the difference between a
merge and an overwrite.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.money import (
    MAXIMUM_QUANTITY as _MAXIMUM_QUANTITY,
)
from ahia.models.entities.money import (
    QUANTITY_PLACES as _QUANTITY_PLACES,
)
from ahia.models.entities.money import (
    ZERO_QUANTITY as _ZERO_QUANTITY,
)

#: Quantities carry three decimal places, because stock is counted in kilos and litres as
#: well as in units. The rule lives in `money`, beside the one for amounts, so a stock
#: count and a sale quantity cannot disagree about what a thousandth is.
QUANTITY_PLACES: Final[Decimal] = _QUANTITY_PLACES

#: The largest quantity this table accepts, in the same unit as a product's threshold.
MAXIMUM_QUANTITY: Final[Decimal] = _MAXIMUM_QUANTITY

ZERO_QUANTITY: Final[Decimal] = _ZERO_QUANTITY


@dataclass(frozen=True, slots=True)
class InventoryModel:
    """The materialized stock state of one product in one business."""

    id: UUID
    tenant_id: UUID
    product_id: UUID
    quantity_on_hand: Decimal
    created_at: datetime
    updated_at: datetime
    reserved_quantity: Decimal = ZERO_QUANTITY
    version: int = 1

    def __post_init__(self) -> None:
        _require_aware(self.created_at, field_name="created_at", inventory_id=self.id)
        _require_aware(self.updated_at, field_name="updated_at", inventory_id=self.id)
        if self.updated_at < self.created_at:
            raise EntityInvariantError(
                operation="build_inventory",
                entity="inventory",
                identifier=str(self.id),
                detail="updated_at is earlier than created_at",
            )

        for field_name, value in (
            ("quantity_on_hand", self.quantity_on_hand),
            ("reserved_quantity", self.reserved_quantity),
        ):
            _require_quantity(value, field_name=field_name, inventory_id=self.id)

        if self.reserved_quantity < ZERO_QUANTITY:
            # A negative reservation would mean more stock is free than exists, which is
            # the one direction that cannot be explained by a real shop's arithmetic.
            raise EntityInvariantError(
                operation="build_inventory",
                entity="inventory",
                identifier=str(self.id),
                detail="reserved_quantity is negative",
            )

        if self.version < 1:
            raise EntityInvariantError(
                operation="build_inventory",
                entity="inventory",
                identifier=str(self.id),
                detail="version starts at 1 and never goes back",
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def empty(
        cls,
        *,
        inventory_id: UUID,
        tenant_id: UUID,
        product_id: UUID,
        now: datetime,
    ) -> InventoryModel:
        """Return the projection for a product nobody has counted yet.

        Zero on hand is a statement, not a missing value: a product that was just added
        has nothing in the shop, and pretending it is unknown would force every reader to
        handle two states.
        """
        return cls(
            id=inventory_id,
            tenant_id=tenant_id,
            product_id=product_id,
            quantity_on_hand=ZERO_QUANTITY,
            reserved_quantity=ZERO_QUANTITY,
            version=1,
            created_at=now,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    @property
    def available_quantity(self) -> Decimal:
        """Return what a new sale may use: what is on hand, less what is promised."""
        return self.quantity_on_hand - self.reserved_quantity

    def is_out_of_stock(self) -> bool:
        """Return True when nothing is available, which is what a shopkeeper asks first."""
        return self.available_quantity <= ZERO_QUANTITY

    def is_overdrawn(self) -> bool:
        """Return True when the books say the business has sold stock it does not have."""
        return self.quantity_on_hand < ZERO_QUANTITY

    def describe_for_audit(self) -> dict[str, str]:
        """Return the numbers an audit line needs, never anything a person wrote."""
        return {
            "inventory_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "product_id": str(self.product_id),
            "quantity_on_hand": str(self.quantity_on_hand),
            "reserved_quantity": str(self.reserved_quantity),
            "version": str(self.version),
            "is_overdrawn": "true" if self.is_overdrawn() else "false",
        }

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def with_movement(self, *, delta: Decimal, at: datetime) -> InventoryModel:
        """Return the projection after a movement of `delta`.

        Deliberately permissive about the sign: whether a negative result is acceptable
        is the business's decision, applied by the service against the tenant's policy.
        An entity that refused it here would make the permissive policies impossible, and
        an entity that allowed it silently would make the strict one unenforceable.
        """
        if delta == ZERO_QUANTITY:
            return self
        return replace(
            self,
            quantity_on_hand=self.quantity_on_hand + delta,
            version=self.version + 1,
            updated_at=at,
        )

    def with_reservation(self, *, quantity: Decimal, at: datetime) -> InventoryModel:
        """Return the projection with more stock promised to a pending sale."""
        if quantity <= ZERO_QUANTITY:
            raise EntityInvariantError(
                operation="reserve_stock",
                entity="inventory",
                identifier=str(self.id),
                detail="a reservation must be for a positive quantity",
            )
        return replace(
            self,
            reserved_quantity=self.reserved_quantity + quantity,
            version=self.version + 1,
            updated_at=at,
        )

    def with_reservation_released(self, *, quantity: Decimal, at: datetime) -> InventoryModel:
        """Return the projection with a reservation given back."""
        if quantity <= ZERO_QUANTITY:
            raise EntityInvariantError(
                operation="release_stock_reservation",
                entity="inventory",
                identifier=str(self.id),
                detail="a released reservation must be for a positive quantity",
            )
        released = self.reserved_quantity - quantity
        if released < ZERO_QUANTITY:
            raise EntityInvariantError(
                operation="release_stock_reservation",
                entity="inventory",
                identifier=str(self.id),
                detail="releasing more than is reserved would free stock that is not promised",
            )
        return replace(self, reserved_quantity=released, version=self.version + 1, updated_at=at)


def coerce_inventory_quantity(value: object, *, field_name: str = "quantity") -> Decimal:
    """Return the Decimal a stock quantity or delta represents, or raise ValueError.

    For the transport boundary, which shares the entity's rules rather than restating
    them: three decimal places, finite, and inside the column's range. Signed on purpose -
    a stock *delta* may be negative, while an on-hand quantity may not - so the sign is
    checked by the caller that knows which of the two it is holding.

    A float is parsed through its own decimal text rather than its binary value, because
    `Decimal(0.1)` is not the number the client typed. A quantity that arrives as a float
    with more than three decimal places is refused, which is how a client's arithmetic
    error becomes a 422 instead of a stock count nobody can reconcile.
    """
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field_name} must be a number")
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, float):
        parsed = Decimal(str(value))
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{field_name} is empty")
        try:
            parsed = Decimal(text)
        except InvalidOperation as invalid:
            raise ValueError(f"{field_name} is not a number") from invalid
    else:
        raise ValueError(f"{field_name} must be a number, not {type(value).__name__}")

    if not parsed.is_finite():
        raise ValueError(f"{field_name} is not a finite number")
    if parsed.quantize(QUANTITY_PLACES) != parsed:
        raise ValueError(f"{field_name} has more than three decimal places")
    if abs(parsed) > MAXIMUM_QUANTITY:
        raise ValueError(f"{field_name} exceeds {MAXIMUM_QUANTITY} in magnitude")
    return parsed


def _require_quantity(value: object, *, field_name: str, inventory_id: UUID) -> None:
    """Raise unless the value is a Decimal quantity this table can hold."""
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise EntityInvariantError(
            operation="build_inventory",
            entity="inventory",
            identifier=str(inventory_id),
            detail=f"{field_name} must be a Decimal, not {type(value).__name__}",
        )
    if not value.is_finite():
        raise EntityInvariantError(
            operation="build_inventory",
            entity="inventory",
            identifier=str(inventory_id),
            detail=f"{field_name} is not a finite number",
        )
    try:
        quantised = value.quantize(QUANTITY_PLACES)
    except InvalidOperation as unrepresentable:
        raise EntityInvariantError(
            operation="build_inventory",
            entity="inventory",
            identifier=str(inventory_id),
            detail=f"{field_name} cannot be represented with three decimal places",
        ) from unrepresentable
    if quantised != value:
        raise EntityInvariantError(
            operation="build_inventory",
            entity="inventory",
            identifier=str(inventory_id),
            detail=f"{field_name} has more than three decimal places",
        )
    if abs(value) > MAXIMUM_QUANTITY:
        raise EntityInvariantError(
            operation="build_inventory",
            entity="inventory",
            identifier=str(inventory_id),
            detail=f"{field_name} exceeds {MAXIMUM_QUANTITY} in magnitude",
        )


def _require_aware(moment: datetime, *, field_name: str, inventory_id: UUID) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="build_inventory",
            entity="inventory",
            identifier=str(inventory_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
