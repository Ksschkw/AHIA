"""Transport contracts for inventory.

**Quantities on the wire follow the same rule as money**: accepted as a JSON number or as a
decimal string, always returned as a decimal string. A stock count is a number a business
reconciles against, and a client that receives `12.5` as a double and sends back
`12.499999999999998` has corrupted a count without anybody typing anything wrong.

Three decimals, not two: stock is counted in kilos and litres as well as in units, and a
half-kilo of rice is a real quantity.

**A reason is part of the contract, not a note.** `adjust_stock` and `record_damage` carry
a required `reason`, because the ledger is the only place the answer to "why is there less
rice than yesterday" is recorded, and it is recorded on a row that cannot be edited.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

from ahia.models.entities.inventory_model import InventoryModel, coerce_inventory_quantity
from ahia.models.entities.inventory_movement_model import (
    MAXIMUM_NOTE_LENGTH,
    MAXIMUM_REFERENCE_TYPE_LENGTH,
    InventoryMovementModel,
)
from ahia.models.entities.product_model import ProductModel

StockReason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAXIMUM_NOTE_LENGTH)
]
StockNote = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAXIMUM_NOTE_LENGTH)
]
ReferenceType = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=MAXIMUM_REFERENCE_TYPE_LENGTH
    ),
]


def _parse_quantity(value: Any) -> Decimal:
    """Parse a stock quantity from the wire, keeping the failure a 422."""
    return coerce_inventory_quantity(value, field_name="quantity")


def _parse_delta(value: Any) -> Decimal:
    """Parse a signed stock adjustment from the wire."""
    return coerce_inventory_quantity(value, field_name="delta")


#: A quantity: three decimal places, and never negative on its own.
Quantity = Annotated[Decimal, BeforeValidator(_parse_quantity)]

#: A signed adjustment: three decimal places, either direction.
SignedQuantity = Annotated[Decimal, BeforeValidator(_parse_delta)]


def quantity_text(value: Decimal) -> str:
    """Render a quantity exactly as it is stored, for the wire.

    Quantised to three places so `12` and `12.000` reach a client identically - the
    entity accepts both from a caller, and the column stores three places, so echoing the
    shorter form would disagree with the next read.
    """
    return format(value.quantize(Decimal("0.001")), "f")


class StockReceiveSchema(BaseModel):
    """Stock arriving."""

    model_config = ConfigDict(extra="forbid")

    quantity: Quantity
    note: StockNote | None = None
    reference_type: ReferenceType | None = None
    reference_id: UUID | None = None


class StockAdjustmentSchema(BaseModel):
    """A correction after a count, in either direction, with its reason."""

    model_config = ConfigDict(extra="forbid")

    delta: SignedQuantity
    reason: StockReason
    reference_type: ReferenceType | None = None
    reference_id: UUID | None = None


class StockDamageSchema(BaseModel):
    """Stock that can no longer be sold."""

    model_config = ConfigDict(extra="forbid")

    quantity: Quantity
    reason: StockReason
    note: StockNote | None = None


class StockTransferSchema(BaseModel):
    """Stock moving from one product record to another inside one business."""

    model_config = ConfigDict(extra="forbid")

    source_product_id: UUID
    destination_product_id: UUID
    quantity: Quantity
    reason: StockReason
    note: StockNote | None = None


class InventoryStateResponseSchema(BaseModel):
    """One product's stock numbers, without the product."""

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    quantity_on_hand: str
    reserved_quantity: str
    available_quantity: str
    version: int
    is_out_of_stock: bool
    is_overdrawn: bool
    updated_at: datetime

    @classmethod
    def from_entity(cls, inventory: InventoryModel) -> InventoryStateResponseSchema:
        return cls(
            product_id=inventory.product_id,
            quantity_on_hand=quantity_text(inventory.quantity_on_hand),
            reserved_quantity=quantity_text(inventory.reserved_quantity),
            available_quantity=quantity_text(inventory.available_quantity),
            version=inventory.version,
            is_out_of_stock=inventory.is_out_of_stock(),
            is_overdrawn=inventory.is_overdrawn(),
            updated_at=inventory.updated_at,
        )


class InventoryLevelResponseSchema(BaseModel):
    """A product and its stock, which is the shape a stock screen reads."""

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    product_name: str
    product_slug: str
    sku: str | None
    is_published: bool
    quantity_on_hand: str
    reserved_quantity: str
    available_quantity: str
    version: int
    is_out_of_stock: bool
    is_overdrawn: bool
    updated_at: datetime

    @classmethod
    def from_entities(
        cls,
        product: ProductModel,
        inventory: InventoryModel,
    ) -> InventoryLevelResponseSchema:
        """Shape a product and its stock together.

        Two entities rather than the service's combined view: a schema that imported the
        service would depend on the layer above it, which the architecture contract
        forbids and which the contract test caught the first time this was written.
        """
        return cls(
            product_id=product.id,
            product_name=product.name,
            product_slug=product.slug,
            sku=product.sku,
            is_published=product.is_published,
            **InventoryStateResponseSchema.from_entity(inventory).model_dump(
                exclude={"product_id"}
            ),
        )


class InventoryMovementResponseSchema(BaseModel):
    """One ledger entry, as a business sees it.

    `is_overdraw` is published because it is the fact a business with a permissive policy
    needs to find: the movements that took stock below zero, without reading every row.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    product_id: UUID
    movement_type: str
    quantity_delta: str
    quantity_before: str
    quantity_after: str
    is_overdraw: bool
    reference_type: str | None
    reference_id: UUID | None
    note: str | None
    actor_id: UUID
    occurred_at: datetime

    @classmethod
    def from_entity(cls, movement: InventoryMovementModel) -> InventoryMovementResponseSchema:
        return cls(
            id=movement.id,
            product_id=movement.product_id,
            movement_type=movement.movement_type.value,
            quantity_delta=quantity_text(movement.quantity_delta),
            quantity_before=quantity_text(movement.quantity_before),
            quantity_after=quantity_text(movement.quantity_after),
            is_overdraw=movement.is_overdraw(),
            reference_type=movement.reference_type,
            reference_id=movement.reference_id,
            note=movement.note,
            actor_id=movement.actor_id,
            occurred_at=movement.occurred_at,
        )


class StockChangeResponseSchema(BaseModel):
    """A movement and the state it produced."""

    model_config = ConfigDict(extra="forbid")

    inventory: InventoryStateResponseSchema
    movement: InventoryMovementResponseSchema


class StockTransferResponseSchema(BaseModel):
    """Both sides of a transfer."""

    model_config = ConfigDict(extra="forbid")

    source: InventoryStateResponseSchema
    destination: InventoryStateResponseSchema


#: A field limit used by the listing query. Declared here so the transport contract owns
#: its own bounds rather than borrowing a service default.
MovementLimit = Annotated[int, Field(ge=1, le=500)]
