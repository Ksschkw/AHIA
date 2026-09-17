"""The price book's rule: a group's price, and the exceptions that carry their own.

These tests are written in the trade's terms because that is what the rule is about. The product
owner's own example is the fixture: 21D at 350 for everything, with Hot 8 and Camon 21 at 370 and
Camon 30 at 400 as the exceptions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from ahia.models.entities.category_model import CategoryModel
from ahia.models.entities.price_book import NO_DEFAULTS, PriceDefaults, resolve_price

TWENTY_ONE_D = PriceDefaults(
    normal_price=Decimal("500.00"),
    wholesale_price=Decimal("350.00"),
    pieces_per_pack=10,
)


@pytest.mark.unit
def test_an_item_with_no_price_of_its_own_takes_its_group_s_price() -> None:
    """The common case: one number for the grade, which is how a trader thinks about it."""
    resolved = resolve_price(own_normal_price=None, defaults=TWENTY_ONE_D)

    assert resolved.normal_price == Decimal("500.00")
    assert resolved.wholesale_price == Decimal("350.00")
    assert resolved.pieces_per_pack == 10
    assert resolved.normal_price_from_group is True
    assert resolved.wholesale_price_from_group is True
    assert resolved.pieces_per_pack_from_group is True


@pytest.mark.unit
def test_an_item_with_its_own_price_is_the_exception_and_says_so() -> None:
    """Hot 8 at 370 inside a grade that is otherwise 350; a screen can see the exception."""
    resolved = resolve_price(
        own_normal_price=Decimal("520.00"),
        own_wholesale_price=Decimal("370.00"),
        own_pieces_per_pack=12,
        defaults=TWENTY_ONE_D,
    )

    assert resolved.wholesale_price == Decimal("370.00")
    assert resolved.normal_price == Decimal("520.00")
    assert resolved.pieces_per_pack == 12
    assert resolved.normal_price_from_group is False
    assert resolved.wholesale_price_from_group is False
    assert resolved.pieces_per_pack_from_group is False


@pytest.mark.unit
def test_a_list_price_falls_back_to_the_normal_price_and_says_so() -> None:
    """A list with no price is a list nobody can act on, so the counter price is used - flagged.

    The flag is the substance here: presenting a retail figure as a wholesale price would look like
    a price he chose, and he never chose it.
    """
    resolved = resolve_price(
        own_normal_price=Decimal("250.00"),
        own_wholesale_price=None,
        defaults=PriceDefaults(normal_price=Decimal("200.00")),
    )

    assert resolved.normal_price == Decimal("250.00")
    assert resolved.wholesale_price == Decimal("250.00")
    assert resolved.wholesale_price_used_the_normal_price is True
    assert resolved.wholesale_price_from_group is False


@pytest.mark.unit
def test_an_item_outside_any_group_still_works() -> None:
    """A product with no category: its own price, no pack, and nothing claimed as inherited."""
    resolved = resolve_price(own_normal_price=Decimal("99.00"))

    assert resolved.normal_price == Decimal("99.00")
    assert resolved.wholesale_price == Decimal("99.00")
    assert resolved.pieces_per_pack is None
    assert resolved.normal_price_from_group is False
    assert resolved.is_priced is True


@pytest.mark.unit
def test_an_item_with_no_price_anywhere_is_reported_as_unpriced() -> None:
    """Nothing here refuses it: the service does, because "no price at all" is a business rule."""
    resolved = resolve_price(own_normal_price=None)

    assert resolved.is_priced is False
    assert resolved.normal_price is None
    assert resolved.wholesale_price is None
    assert resolved.wholesale_price_used_the_normal_price is False


@pytest.mark.unit
def test_a_group_with_nothing_set_is_empty() -> None:
    """Every group starts with nothing set, and that has to be a state rather than an absence."""
    assert NO_DEFAULTS.is_empty is True
    assert PriceDefaults(normal_price=Decimal("1.00")).is_empty is False
    assert PriceDefaults(pieces_per_pack=1).is_empty is False


@pytest.mark.unit
def test_a_group_hands_over_what_it_offers() -> None:
    """The group is the one place its prices are read from, so no caller reassembles the rule."""
    group = CategoryModel.create(
        category_id=uuid4(),
        tenant_id=uuid4(),
        name="21D",
        now=datetime(2026, 9, 17, 9, 0, tzinfo=UTC),
        default_normal_price=Decimal("500.00"),
        default_wholesale_price=Decimal("350.00"),
        default_pieces_per_pack=10,
    )

    defaults = group.price_defaults()

    assert defaults == TWENTY_ONE_D
    assert defaults.is_empty is False
