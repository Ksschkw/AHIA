"""One line of a customer's list: what they want, how many, and who has priced it.

A line is either **something in the catalogue** or **free text** - "screenguard for iPhone 15, the
matte
one" - because in real life nothing stops a customer asking for something the shop has not got, and
a
list that cannot hold the request gets written on paper again. A free-text line can carry a picture,
which is how a request gets precise without either side finding the words.

Three prices can appear on a line, and they are deliberately different things:

- `customer_price` - what the customer was shown when they built the list, so there is a record of
what
  they saw. It is **not** necessarily what they pay.
- `shop_price` - what the trader set. An unpriced line is normal: the customer does not price what
the
  trader has to go and find, and the trader works it out when he has it.
- `cost_price` - what he paid for it in the market that morning, which is the one number paper can
never
  give him: at the end of a mixed list he knows what he actually made on it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.money import (
    MAXIMUM_MONEY,
    ZERO_MONEY,
    check_money_rules,
    check_quantity_rules,
)

MAXIMUM_FREE_TEXT_LENGTH: Final[int] = 400
MAXIMUM_NOTE_LENGTH: Final[int] = 400
MAXIMUM_PACK_PIECES: Final[int] = 1_000


class RequestLineUnit(StrEnum):
    """How a line is counted. A piece or a pack of them, and nothing in between."""

    PIECE = "piece"
    PACK = "pack"


class RequestLineState(StrEnum):
    """What the trader found when he went looking.

    `SOMEWHERE` is the state everything starts in and it is not a promise of stock: an Igbo trader
    is
    never truly out of stock, and a customer is never shown whether something is on the shelf.
    """

    SOMEWHERE = "somewhere"
    HAVE_IT = "have_it"
    BUY_IT = "buy_it"
    CANNOT_GET = "cannot_get"


@dataclass(frozen=True, slots=True)
class RequestLineModel:
    """One item on one customer's list."""

    id: UUID
    request_id: UUID
    tenant_id: UUID
    position: int
    quantity: Decimal
    created_at: datetime
    unit: RequestLineUnit = RequestLineUnit.PIECE
    product_id: UUID | None = None
    free_text: str | None = None
    note: str | None = None
    pieces_per_pack: int | None = None
    customer_price: Decimal | None = None
    shop_price: Decimal | None = None
    cost_price: Decimal | None = None
    state: RequestLineState = RequestLineState.SOMEWHERE
    image_key: str | None = None

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise EntityInvariantError(
                operation="build_request_line",
                entity="request_line",
                identifier=str(self.id),
                detail="created_at must carry a timezone",
            )
        if (self.product_id is None) == (self.free_text is None):
            # Both or neither is a line that cannot be acted on: the first has nothing to price, the
            # second is ambiguous about what is being asked for.
            raise EntityInvariantError(
                operation="build_request_line",
                entity="request_line",
                identifier=str(self.id),
                detail=(
                    "a line is either a catalogued item or free text, never both and never neither"
                ),
            )
        if self.free_text is not None and len(self.free_text) > MAXIMUM_FREE_TEXT_LENGTH:
            raise EntityInvariantError(
                operation="build_request_line",
                entity="request_line",
                identifier=str(self.id),
                detail=f"free_text exceeds {MAXIMUM_FREE_TEXT_LENGTH} characters",
            )
        if self.note is not None and len(self.note) > MAXIMUM_NOTE_LENGTH:
            raise EntityInvariantError(
                operation="build_request_line",
                entity="request_line",
                identifier=str(self.id),
                detail=f"note exceeds {MAXIMUM_NOTE_LENGTH} characters",
            )
        if self.position < 0:
            raise EntityInvariantError(
                operation="build_request_line",
                entity="request_line",
                identifier=str(self.id),
                detail="position cannot be negative",
            )
        try:
            check_quantity_rules(
                self.quantity,
                field_name="quantity",
                minimum=ZERO_MONEY,
                maximum=MAXIMUM_MONEY,
            )
        except ValueError as invalid_quantity:
            raise EntityInvariantError(
                operation="build_request_line",
                entity="request_line",
                identifier=str(self.id),
                detail=str(invalid_quantity),
            ) from invalid_quantity
        if self.quantity <= ZERO_MONEY:
            raise EntityInvariantError(
                operation="build_request_line",
                entity="request_line",
                identifier=str(self.id),
                detail="a line asks for something: quantity must be more than zero",
            )
        for field_name, price in (
            ("customer_price", self.customer_price),
            ("shop_price", self.shop_price),
            ("cost_price", self.cost_price),
        ):
            if price is None:
                continue
            try:
                check_money_rules(
                    price, field_name=field_name, minimum=ZERO_MONEY, maximum=MAXIMUM_MONEY
                )
            except ValueError as invalid_money:
                raise EntityInvariantError(
                    operation="build_request_line",
                    entity="request_line",
                    identifier=str(self.id),
                    detail=str(invalid_money),
                ) from invalid_money
        if self.unit is RequestLineUnit.PACK and self.pieces_per_pack is None:
            raise EntityInvariantError(
                operation="build_request_line",
                entity="request_line",
                identifier=str(self.id),
                detail="a line counted in packs must say how many pieces are in one",
            )
        if (
            self.pieces_per_pack is not None
            and not 1 <= self.pieces_per_pack <= MAXIMUM_PACK_PIECES
        ):
            raise EntityInvariantError(
                operation="build_request_line",
                entity="request_line",
                identifier=str(self.id),
                detail=(
                    f"pieces_per_pack must be between 1 and {MAXIMUM_PACK_PIECES}, "
                    f"received {self.pieces_per_pack}"
                ),
            )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    @property
    def pieces(self) -> Decimal:
        """Return how many pieces this line is, whichever unit it was counted in."""
        if self.unit is RequestLineUnit.PACK and self.pieces_per_pack is not None:
            return self.quantity * self.pieces_per_pack
        return self.quantity

    @property
    def is_priced(self) -> bool:
        """Return True when the trader has said what this line costs."""
        return self.shop_price is not None

    @property
    def line_total(self) -> Decimal | None:
        """Return what this line comes to, or None while nobody has priced it.

        None rather than zero, and the caller shows it as "to be priced": a total quietly missing
        money
        is a total nobody trusts.
        """
        if self.shop_price is None:
            return None
        return self.shop_price * self.pieces

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def priced_at(self, *, unit_price: Decimal) -> RequestLineModel:
        """Return the line with the price the trader set, per piece."""
        try:
            check_money_rules(
                unit_price, field_name="shop_price", minimum=ZERO_MONEY, maximum=MAXIMUM_MONEY
            )
        except ValueError as invalid_money:
            raise EntityInvariantError(
                operation="price_request_line",
                entity="request_line",
                identifier=str(self.id),
                detail=str(invalid_money),
            ) from invalid_money
        return replace(self, shop_price=unit_price)

    def sourced_for(
        self, *, cost_price: Decimal | None, state: RequestLineState
    ) -> RequestLineModel:
        """Return the line with what it cost him and where he found it."""
        return replace(self, cost_price=cost_price, state=state)

    def describe_for_audit(self) -> dict[str, str]:
        """Return identifiers only: a customer's list is their business, not the log's."""
        return {
            "request_line_id": str(self.id),
            "request_id": str(self.request_id),
            "tenant_id": str(self.tenant_id),
            "state": self.state.value,
        }
