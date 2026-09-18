"""A customer's list: what it holds, and what it refuses to be.

The fixtures are the product owner's own example, because the rule is about his trade: a list is a
wish
until the trader confirms it, a line is either something in the catalogue or something somebody
asked
for in words, and a price may genuinely be absent until he has gone and found the thing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.request_line_model import (
    RequestLineModel,
    RequestLineState,
    RequestLineUnit,
)
from ahia.models.entities.request_model import RequestModel, RequestStatus

NOW = datetime(2026, 9, 17, 18, 0, tzinfo=UTC)


def a_list(**overrides: object) -> RequestModel:
    parameters: dict[str, object] = {
        "request_id": uuid4(),
        "tenant_id": uuid4(),
        "customer_phone": "08031234567",
        "now": NOW,
    }
    parameters.update(overrides)
    return RequestModel.submitted_by_customer(**parameters)  # type: ignore[arg-type]


def a_line(**overrides: object) -> RequestLineModel:
    parameters: dict[str, object] = {
        "id": uuid4(),
        "request_id": uuid4(),
        "tenant_id": uuid4(),
        "position": 0,
        "quantity": Decimal("20"),
        "created_at": NOW,
        "product_id": uuid4(),
    }
    parameters.update(overrides)
    return RequestLineModel(**parameters)  # type: ignore[arg-type]


@pytest.mark.unit
def test_the_number_asked_for_is_stored_in_one_form() -> None:
    """The customer writes it however they like; the list keeps it one way, as the account does."""
    for written in ("08031234567", "8031234567", "+2348031234567", "2348031234567"):
        assert a_list(customer_phone=written).customer_phone == "+2348031234567"


@pytest.mark.unit
def test_a_list_cannot_be_taken_without_a_number() -> None:
    """The number is the only identity a customer has, and the reason they are asked for it."""
    with pytest.raises(EntityInvariantError):
        a_list(customer_phone="not a number at all")


@pytest.mark.unit
def test_a_list_starts_as_something_a_customer_sent() -> None:
    taken = a_list()
    assert taken.status is RequestStatus.SUBMITTED
    assert taken.is_open is True
    assert taken.is_confirmed is False


@pytest.mark.unit
def test_a_confirmed_list_is_a_sale_and_cannot_be_confirmed_again() -> None:
    """Confirmation is the one moment money exists; doing it twice would create it twice."""
    confirmed = a_list().confirmed(at=NOW)
    assert confirmed.is_confirmed is True
    assert confirmed.is_open is False
    with pytest.raises(EntityInvariantError):
        confirmed.confirmed(at=NOW)


@pytest.mark.unit
def test_a_cancelled_list_cannot_come_back() -> None:
    cancelled = a_list().moved_to(status=RequestStatus.CANCELLED, at=NOW)
    with pytest.raises(EntityInvariantError):
        cancelled.moved_to(status=RequestStatus.SUBMITTED, at=NOW)


@pytest.mark.unit
def test_a_line_is_either_catalogued_or_in_words() -> None:
    """Both or neither is a line nobody can act on."""
    with pytest.raises(EntityInvariantError):
        a_line(free_text="screenguard for iPhone 15, the matte one")
    with pytest.raises(EntityInvariantError):
        a_line(product_id=None, free_text=None)


@pytest.mark.unit
def test_a_free_text_line_can_carry_the_words_they_used() -> None:
    asked = a_line(product_id=None, free_text="screenguard for iPhone 15, the matte one")
    assert asked.free_text is not None
    assert asked.is_priced is False


@pytest.mark.unit
def test_a_line_asks_for_something() -> None:
    with pytest.raises(EntityInvariantError):
        a_line(quantity=Decimal("0"))


@pytest.mark.unit
def test_a_pack_counts_pieces_and_says_how_many() -> None:
    """The calculator is the feature: 2 packs of 10 is 20 pieces, and a pack with no size is
    refused."""
    packed = a_line(quantity=Decimal("2"), unit=RequestLineUnit.PACK, pieces_per_pack=10)
    assert packed.pieces == Decimal("20")
    with pytest.raises(EntityInvariantError):
        a_line(quantity=Decimal("2"), unit=RequestLineUnit.PACK)


@pytest.mark.unit
def test_an_unpriced_line_has_no_total_rather_than_a_zero() -> None:
    """A total quietly missing money is a total nobody trusts, so it says nothing yet."""
    unpriced = a_line(customer_price=Decimal("350.00"))
    assert unpriced.line_total is None


@pytest.mark.unit
def test_a_priced_line_totals_per_piece() -> None:
    """350 a piece for 20 pieces is 7000, whatever the customer thought it would be."""
    priced = a_line(customer_price=Decimal("300.00")).priced_at(unit_price=Decimal("350.00"))
    assert priced.is_priced is True
    assert priced.line_total == Decimal("7000.00")


@pytest.mark.unit
def test_what_it_cost_him_is_recorded_when_he_buys_it_in() -> None:
    """The one number paper cannot give him: what he made on a list he partly went and bought."""
    bought = a_line().sourced_for(cost_price=Decimal("280.00"), state=RequestLineState.BUY_IT)
    assert bought.state is RequestLineState.BUY_IT
    assert bought.cost_price == Decimal("280.00")
