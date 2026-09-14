"""Tests for the expense entity and the category vocabulary.

Three subjects.

The amount. An expense is money that left the business, so it is strictly positive and
quantised to two places. A negative expense would be a refund typed by whoever is entering
data, and a report that sums the column would silently reduce the total it claims to report.

The category. It comes from a closed set because a spending report groups by it, and the
tests below hold that line: an unknown value is refused rather than filed under `OTHER`, and
every member fits the column the database stores it in.

The reversal. An expense is never deleted; it is reversed, with a moment and a reason. A
report that counts a reversed expense as spending counts the same naira twice, because the
compensating ledger entry already brought the money back.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.expense_category import (
    MAXIMUM_VALUE_LENGTH,
    ExpenseCategory,
    parse_expense_category,
)
from ahia.models.entities.expense_model import (
    MAXIMUM_DESCRIPTION_LENGTH,
    MAXIMUM_REVERSAL_REASON_LENGTH,
    ExpenseModel,
)
from ahia.models.entities.money import ZERO_MONEY
from ahia.models.entities.payment_model import PaymentMethod

NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=1)


def build_expense(**overrides: object) -> ExpenseModel:
    parameters: dict[str, object] = {
        "expense_id": uuid4(),
        "tenant_id": uuid4(),
        "category": ExpenseCategory.TRANSPORT,
        "amount": Decimal("3500.00"),
        "payment_method": PaymentMethod.CASH,
        "actor_id": uuid4(),
        "now": NOW,
        "description": "Keke to the market and back",
    }
    parameters.update(overrides)
    return ExpenseModel.record(**parameters)  # type: ignore[arg-type]


def build_stored_expense(**overrides: object) -> ExpenseModel:
    """Build an expense with reversal state set directly.

    `record` is how an expense is created and it has no reversal parameters, because an
    expense is never born reversed. The reversal invariants live in `__post_init__`, so they
    are exercised by constructing the stored shape.
    """
    return replace(build_expense(), **overrides)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The category vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_every_category_fits_the_column_the_database_stores_it_in() -> None:
    for category in ExpenseCategory:
        assert len(category.value) <= MAXIMUM_VALUE_LENGTH


@pytest.mark.unit
def test_a_category_reads_as_a_heading_a_person_recognises() -> None:
    assert ExpenseCategory.STOCK_PURCHASE.label() == "Stock Purchase"
    assert ExpenseCategory.FEES_AND_LEVIES.label() == "Fees And Levies"


@pytest.mark.unit
def test_other_is_the_only_category_that_does_not_say_what_the_money_was_for() -> None:
    assert ExpenseCategory.OTHER.is_known_spending is False
    assert ExpenseCategory.RENT.is_known_spending is True


@pytest.mark.unit
def test_an_unknown_category_is_refused_rather_than_filed_as_other() -> None:
    with pytest.raises(ValueError, match="is not an expense category"):
        parse_expense_category("transport")


@pytest.mark.unit
def test_a_known_category_parses_from_its_stored_value() -> None:
    assert parse_expense_category("STOCK_PURCHASE") is ExpenseCategory.STOCK_PURCHASE


# ---------------------------------------------------------------------------
# The amount
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_an_expense_is_quantised_to_two_places() -> None:
    expense = build_expense(amount=Decimal("3500.005"))

    assert expense.amount == Decimal("3500.01")


@pytest.mark.unit
def test_a_negative_expense_is_refused() -> None:
    with pytest.raises(EntityInvariantError) as raised:
        build_expense(amount=Decimal("-3500.00"))

    assert "amount" in str(raised.value)


@pytest.mark.unit
def test_a_zero_expense_is_refused() -> None:
    with pytest.raises(EntityInvariantError) as raised:
        build_expense(amount=ZERO_MONEY)

    assert "amount" in str(raised.value)


@pytest.mark.unit
def test_an_amount_that_is_not_a_decimal_is_refused() -> None:
    with pytest.raises(EntityInvariantError) as raised:
        build_expense(amount=3500.0)

    assert "must be a Decimal" in str(raised.value)


# ---------------------------------------------------------------------------
# Shape and vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_category_outside_the_vocabulary_is_refused() -> None:
    with pytest.raises(EntityInvariantError) as raised:
        build_expense(category="TRANSPORT")

    assert "ExpenseCategory" in str(raised.value)


@pytest.mark.unit
def test_a_payment_method_outside_the_vocabulary_is_refused() -> None:
    with pytest.raises(EntityInvariantError) as raised:
        build_expense(payment_method="CASH")

    assert "PaymentMethod" in str(raised.value)


@pytest.mark.unit
def test_an_expense_defaults_to_being_incurred_when_it_is_recorded() -> None:
    expense = build_expense()

    assert expense.incurred_at == NOW
    assert expense.created_at == NOW


@pytest.mark.unit
def test_a_back_dated_expense_keeps_the_day_it_was_paid() -> None:
    paid_on = datetime(2026, 9, 1, 8, 30, tzinfo=UTC)

    expense = build_expense(incurred_at=paid_on)

    assert expense.incurred_at == paid_on
    assert expense.created_at == NOW


@pytest.mark.unit
def test_a_naive_incurred_at_is_refused() -> None:
    """A naive timestamp has no meaning across the clients this product serves."""
    naive = datetime(2026, 9, 14, 9, 0)  # noqa: DTZ001 - the value under test

    with pytest.raises(EntityInvariantError, match="naive datetime"):
        build_expense(incurred_at=naive)


@pytest.mark.unit
def test_a_description_longer_than_the_bound_is_refused() -> None:
    with pytest.raises(EntityInvariantError) as raised:
        build_expense(description="x" * (MAXIMUM_DESCRIPTION_LENGTH + 1))

    assert "description exceeds" in str(raised.value)


@pytest.mark.unit
def test_an_empty_description_is_stored_as_absent() -> None:
    assert build_expense(description="   ").description is None
    assert build_expense(description=None).description is None


@pytest.mark.unit
def test_an_expense_is_immutable() -> None:
    expense = build_expense()

    with pytest.raises(FrozenInstanceError):
        expense.amount = Decimal("1.00")  # type: ignore[misc]


@pytest.mark.unit
def test_an_audit_line_carries_identifiers_and_no_free_text() -> None:
    expense = build_expense(description="Bought cement from Alhaji Musa, 08031234567")

    described = expense.describe_for_audit()

    assert described["expense_id"] == str(expense.id)
    assert described["category"] == "TRANSPORT"
    assert described["amount"] == "3500.00"
    assert described["reversed"] == "false"
    assert "Musa" not in str(described)
    assert "08031234567" not in str(described)


# ---------------------------------------------------------------------------
# Reversal
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_reversing_an_expense_records_when_and_why() -> None:
    expense = build_expense()

    reversed_expense = expense.reversed(at=LATER, reason="paid twice by mistake")

    assert reversed_expense.has_been_reversed() is True
    assert reversed_expense.reversed_at == LATER
    assert reversed_expense.reversal_reason == "paid twice by mistake"
    assert expense.has_been_reversed() is False


@pytest.mark.unit
def test_a_reversed_expense_contributes_nothing_to_total_spending() -> None:
    expense = build_expense(amount=Decimal("12000.00"))

    assert expense.counted_amount() == Decimal("12000.00")
    assert expense.reversed(at=LATER, reason="wrong amount").counted_amount() == ZERO_MONEY


@pytest.mark.unit
def test_reversing_twice_keeps_the_first_reason_and_moment() -> None:
    expense = build_expense().reversed(at=LATER, reason="paid twice")

    again = expense.reversed(at=LATER + timedelta(hours=1), reason="something else")

    assert again.reversed_at == LATER
    assert again.reversal_reason == "paid twice"


@pytest.mark.unit
def test_a_reversal_without_a_reason_is_refused() -> None:
    with pytest.raises(EntityInvariantError) as raised:
        build_stored_expense(reversed_at=LATER, reversal_reason="  ")

    assert "must record why" in str(raised.value)


@pytest.mark.unit
def test_a_reversal_reason_without_a_moment_is_refused() -> None:
    with pytest.raises(EntityInvariantError) as raised:
        build_stored_expense(reversal_reason="paid twice")

    assert "cannot carry a reversal reason" in str(raised.value)


@pytest.mark.unit
def test_a_reversal_reason_longer_than_the_bound_is_refused() -> None:
    with pytest.raises(EntityInvariantError) as raised:
        build_stored_expense(
            reversed_at=LATER,
            reversal_reason="x" * (MAXIMUM_REVERSAL_REASON_LENGTH + 1),
        )

    assert "reversal_reason exceeds" in str(raised.value)
