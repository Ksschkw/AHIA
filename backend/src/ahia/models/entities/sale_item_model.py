"""A sale line: what was sold, at what price, and what it came to.

**The name is a snapshot.** `product_name_snapshot` is copied at the moment of sale,
because a receipt has to keep saying what was sold even after the product is renamed or
withdrawn. Reading today's product name from a two-year-old receipt is the bug this column
exists to prevent, and it is why the entity carries the name rather than a reference the
reader resolves later.

**The unit price is a snapshot too.** A product's price changes; a sale's price does not.
Storing the price that was charged means a report can be recomputed from the rows rather
than from today's catalogue, and a dispute can be settled by reading the receipt.

**The arithmetic is checked, not trusted.** `line_total` must equal
`quantise(unit_price * quantity) - discount`, and the discount cannot exceed the line. A
caller cannot write a row whose parts do not add up, and the same rule is enforced on the
dataclass because the persistence mapper builds the entity field by field.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.money import (
    MAXIMUM_MONEY,
    MAXIMUM_QUANTITY,
    ZERO_MONEY,
    ZERO_QUANTITY,
    check_money_rules,
    check_quantity_rules,
    line_total_for,
    quantise_money,
)

MAXIMUM_PRODUCT_NAME_LENGTH: Final[int] = 200


@dataclass(frozen=True, slots=True)
class SaleItemModel:
    """One line of a sale."""

    id: UUID
    tenant_id: UUID
    sale_id: UUID
    product_id: UUID
    product_name_snapshot: str
    unit_price: Decimal
    quantity: Decimal
    line_total: Decimal
    created_at: datetime
    discount_amount: Decimal = ZERO_MONEY

    def __post_init__(self) -> None:
        _require_aware(self.created_at, field_name="created_at", item_id=self.id)

        name = self.product_name_snapshot.strip()
        if not name:
            raise EntityInvariantError(
                operation="build_sale_item",
                entity="sale_item",
                identifier=str(self.id),
                detail="product_name_snapshot is empty",
            )
        if len(name) > MAXIMUM_PRODUCT_NAME_LENGTH:
            raise EntityInvariantError(
                operation="build_sale_item",
                entity="sale_item",
                identifier=str(self.id),
                detail=f"product_name_snapshot exceeds {MAXIMUM_PRODUCT_NAME_LENGTH} characters",
            )

        # Order matters for the message a caller reads. The shape of each field is checked
        # first, then the rules that relate them, and only then the bounds on the derived
        # total - otherwise a discount larger than its line would be reported as "the line
        # total is below zero", which is true and tells the caller nothing about the cause.
        for field_name, value in (
            ("unit_price", self.unit_price),
            ("discount_amount", self.discount_amount),
        ):
            _require_money(value, field_name=field_name, item_id=self.id)
        _require_money_shape(self.line_total, field_name="line_total", item_id=self.id)
        _require_quantity(self.quantity, field_name="quantity", item_id=self.id)

        if self.quantity <= ZERO_QUANTITY:
            # A line for nothing is not a sale line. Refusing it keeps the movement the
            # sale will write from being a movement that changes nothing, which the ledger
            # refuses in turn - better to say so here, where the caller can fix it.
            raise EntityInvariantError(
                operation="build_sale_item",
                entity="sale_item",
                identifier=str(self.id),
                detail="quantity must be greater than zero",
            )

        gross = quantise_money(self.unit_price * self.quantity)
        if self.discount_amount > gross:
            raise EntityInvariantError(
                operation="build_sale_item",
                entity="sale_item",
                identifier=str(self.id),
                detail="a discount cannot exceed the line it discounts",
            )
        if self.line_total < ZERO_MONEY:
            raise EntityInvariantError(
                operation="build_sale_item",
                entity="sale_item",
                identifier=str(self.id),
                detail="line_total cannot be negative; a discount is not a refund",
            )

        expected_total = line_total_for(
            unit_price=self.unit_price,
            quantity=self.quantity,
            discount=self.discount_amount,
        )
        if self.line_total != expected_total:
            raise EntityInvariantError(
                operation="build_sale_item",
                entity="sale_item",
                identifier=str(self.id),
                detail=(
                    "line_total must equal unit_price * quantity - discount: "
                    f"{self.line_total} != {expected_total}"
                ),
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def for_product(
        cls,
        *,
        item_id: UUID,
        tenant_id: UUID,
        sale_id: UUID,
        product_id: UUID,
        product_name: str,
        unit_price: Decimal,
        quantity: Decimal,
        now: datetime,
        discount_amount: Decimal = ZERO_MONEY,
    ) -> SaleItemModel:
        """Build a line, deriving the total from the price, the quantity and the discount.

        The product's name and price arrive as values rather than as a product entity: this
        is a *snapshot*, and taking them from the product would invite a caller to read
        them later and get a different answer.
        """
        return cls(
            id=item_id,
            tenant_id=tenant_id,
            sale_id=sale_id,
            product_id=product_id,
            product_name_snapshot=product_name.strip(),
            unit_price=unit_price,
            quantity=quantity,
            discount_amount=discount_amount,
            line_total=line_total_for(
                unit_price=unit_price,
                quantity=quantity,
                discount=discount_amount,
            ),
            created_at=now,
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    def gross_amount(self) -> Decimal:
        """Return the line before its discount, which is what a customer compares."""
        return quantise_money(self.unit_price * self.quantity)

    def describe_for_audit(self) -> dict[str, str]:
        """Return what an audit line needs: identifiers, amounts and the snapshot."""
        return {
            "sale_item_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "sale_id": str(self.sale_id),
            "product_id": str(self.product_id),
            "quantity": str(self.quantity),
            "unit_price": str(self.unit_price),
            "line_total": str(self.line_total),
        }


def _require_money(value: object, *, field_name: str, item_id: UUID) -> None:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise EntityInvariantError(
            operation="build_sale_item",
            entity="sale_item",
            identifier=str(item_id),
            detail=f"{field_name} must be a Decimal, not {type(value).__name__}",
        )
    try:
        check_money_rules(value, field_name=field_name, minimum=ZERO_MONEY, maximum=MAXIMUM_MONEY)
    except ValueError as invalid:
        raise EntityInvariantError(
            operation="build_sale_item",
            entity="sale_item",
            identifier=str(item_id),
            detail=str(invalid),
        ) from invalid


def _require_money_shape(value: object, *, field_name: str, item_id: UUID) -> None:
    """Check a derived amount's shape without bounding it, so the cause is reported first.

    A negative line total is a consequence of the discount, and the message that explains
    the discount is more useful than the one that says a total is below zero.
    """
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise EntityInvariantError(
            operation="build_sale_item",
            entity="sale_item",
            identifier=str(item_id),
            detail=f"{field_name} must be a Decimal, not {type(value).__name__}",
        )
    try:
        check_money_rules(
            value,
            field_name=field_name,
            minimum=-MAXIMUM_MONEY,
            maximum=MAXIMUM_MONEY,
        )
    except ValueError as invalid:
        raise EntityInvariantError(
            operation="build_sale_item",
            entity="sale_item",
            identifier=str(item_id),
            detail=str(invalid),
        ) from invalid


def _require_quantity(value: object, *, field_name: str, item_id: UUID) -> None:
    """Check a quantity's shape, allowing a negative one so the caller hears the real cause."""
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise EntityInvariantError(
            operation="build_sale_item",
            entity="sale_item",
            identifier=str(item_id),
            detail=f"{field_name} must be a Decimal, not {type(value).__name__}",
        )
    try:
        check_quantity_rules(
            value,
            field_name=field_name,
            minimum=-MAXIMUM_QUANTITY,
            maximum=MAXIMUM_QUANTITY,
        )
    except ValueError as invalid:
        raise EntityInvariantError(
            operation="build_sale_item",
            entity="sale_item",
            identifier=str(item_id),
            detail=str(invalid),
        ) from invalid


def _require_aware(moment: datetime, *, field_name: str, item_id: UUID) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="build_sale_item",
            entity="sale_item",
            identifier=str(item_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
