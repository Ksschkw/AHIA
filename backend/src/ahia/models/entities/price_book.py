"""The price book's arithmetic: what applies to an item, and where it came from.

A trader thinks in groups. "All of the 21D are 350" is one number, and the exceptions are the items
that carry their own - Hot 8 and Camon 21 at 370, Camon 30 at 400. So every item's price is either
**its own** or **its group's**, and the difference matters: a shop owner looking at a list of prices
needs to see at a glance which models are the exceptions, because those are the ones he has to keep
in his head when the market moves.

This module is that rule and nothing else. It is a pure function over values - no database, no
configuration, no service - so it can be tested on its own and called from the grid, from a list,
from a sale and from the shop page without any of them re-implementing it. A rule stated twice is a
rule that drifts, and this one is stated in the trade's own words by the person who runs the trade.

Three outcomes, all of them visible to a caller:

- **own** - the item carries a price, and that price applies.
- **group** - the item carries none, so its group's applies.
- **normal** - nobody set a wholesale price, so the normal price is used, because a list that shows
  no price for something the shop sells is a list the customer cannot act on. That is reported
  separately rather than hidden inside the wholesale figure: he should be able to see that a list
  price is not the price he meant to give, and set one.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final


@dataclass(frozen=True, slots=True)
class PriceDefaults:
    """The prices and pack size a group gives to the items under it.

    Every field is optional, because a group may be nothing but a heading - "Charging cords" with no
    price of its own - and a business that never opens the price book has groups with nothing set.
    """

    normal_price: Decimal | None = None
    wholesale_price: Decimal | None = None
    pieces_per_pack: int | None = None

    @property
    def is_empty(self) -> bool:
        """Return True when the group sets nothing, which is the state every group starts in."""
        return (
            self.normal_price is None
            and self.wholesale_price is None
            and self.pieces_per_pack is None
        )


#: A group that offers nothing: the default for an item that belongs to no group.
NO_DEFAULTS: Final[PriceDefaults] = PriceDefaults()


@dataclass(frozen=True, slots=True)
class ResolvedPrice:
    """The prices that apply to one item, and which of them came from its group.

    `normal_price` and `wholesale_price` are None only when neither the item nor its group has one,
    which the caller turns into whatever its own contract says. A product being created without any
    price anywhere is refused by the service and not here, because "an item with no price at all" is
    a business rule and this module is arithmetic.
    """

    normal_price: Decimal | None
    wholesale_price: Decimal | None
    pieces_per_pack: int | None
    normal_price_from_group: bool = False
    wholesale_price_from_group: bool = False
    wholesale_price_used_the_normal_price: bool = False
    pieces_per_pack_from_group: bool = False

    @property
    def is_priced(self) -> bool:
        """Return True when the item can be sold at all: it has a price from somewhere."""
        return self.normal_price is not None


def resolve_price(
    *,
    own_normal_price: Decimal | None,
    own_wholesale_price: Decimal | None = None,
    own_pieces_per_pack: int | None = None,
    defaults: PriceDefaults = NO_DEFAULTS,
) -> ResolvedPrice:
    """Return what applies to one item, and which parts of it came from the group.

    The order is always the same, and it is the order a trader would say it in: what this one costs,
    or else what the rest of them cost. Nothing here decides whether a price is *reasonable* - that
    is his business, and the product's whole position is that it does not restrict him.
    """
    normal_price = own_normal_price if own_normal_price is not None else defaults.normal_price
    normal_from_group = own_normal_price is None and defaults.normal_price is not None

    wholesale_price: Decimal | None
    if own_wholesale_price is not None:
        wholesale_price = own_wholesale_price
        wholesale_from_group = False
        used_normal = False
    elif defaults.wholesale_price is not None:
        wholesale_price = defaults.wholesale_price
        wholesale_from_group = True
        used_normal = False
    else:
        # Nobody set a wholesale price, so the item is offered to a list at what it sells for at the
        # counter. Flagged, so a screen can say "this one has no wholesale price of its own" rather
        # than presenting a retail figure as though he had chosen it.
        wholesale_price = normal_price
        wholesale_from_group = False
        used_normal = normal_price is not None

    pieces_per_pack = (
        own_pieces_per_pack if own_pieces_per_pack is not None else defaults.pieces_per_pack
    )

    return ResolvedPrice(
        normal_price=normal_price,
        wholesale_price=wholesale_price,
        pieces_per_pack=pieces_per_pack,
        normal_price_from_group=normal_from_group,
        wholesale_price_from_group=wholesale_from_group,
        wholesale_price_used_the_normal_price=used_normal,
        pieces_per_pack_from_group=(
            own_pieces_per_pack is None and defaults.pieces_per_pack is not None
        ),
    )
