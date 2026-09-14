"""Tests for the sales entities.

Money is the subject. A line total, a sale total and a payment have to agree, and the tests
below are mostly about the ways they could disagree: a rounding rule that loses a kobo, a
discount larger than what it discounts, a total that is not the sum of its lines, and a
payment status that claims more was received than the payments say.

The second subject is what a cancelled sale keeps. It keeps everything - its number, its
lines, its reasons - because the money and the stock still moved, and deleting the record
would erase the fact that they moved back.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.ledger_entry_model import (
    LedgerDirection,
    LedgerEntryModel,
    LedgerEntryType,
)
from ahia.models.entities.money import line_total_for, quantise_money
from ahia.models.entities.payment_model import (
    PaymentMethod,
    PaymentModel,
    PaymentStatus,
)
from ahia.models.entities.sale_item_model import SaleItemModel
from ahia.models.entities.sale_model import (
    PaymentStatus as SalePaymentStatus,
)
from ahia.models.entities.sale_model import (
    SaleModel,
    SaleStatus,
    payment_status_for,
)

NOW = datetime(2026, 9, 13, 10, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)


def build_item(**overrides: object) -> SaleItemModel:
    parameters: dict[str, object] = {
        "item_id": uuid4(),
        "tenant_id": uuid4(),
        "sale_id": uuid4(),
        "product_id": uuid4(),
        "product_name": "Rice 50kg",
        "unit_price": Decimal("45000.00"),
        "quantity": Decimal("2.000"),
        "now": NOW,
    }
    parameters.update(overrides)
    return SaleItemModel.for_product(**parameters)  # type: ignore[arg-type]


def build_sale(**overrides: object) -> SaleModel:
    parameters: dict[str, object] = {
        "sale_id": uuid4(),
        "tenant_id": uuid4(),
        "receipt_number": "OBI-000001",
        "seller_id": uuid4(),
        "subtotal": Decimal("85000.00"),
        "now": NOW,
    }
    parameters.update(overrides)
    return SaleModel.issue(**parameters)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Line arithmetic
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_line_total_is_price_times_quantity_less_the_discount() -> None:
    item = build_item(
        unit_price=Decimal("45000.00"),
        quantity=Decimal("2.000"),
        discount_amount=Decimal("5000.00"),
    )

    assert item.line_total == Decimal("85000.00")
    assert item.gross_amount() == Decimal("90000.00")


@pytest.mark.unit
def test_a_fractional_quantity_rounds_half_up() -> None:
    """A kobo lost to banker's rounding is a kobo the shopkeeper cannot explain."""
    # 3 * 0.005 = 0.015 -> 0.02 half-up, where ROUND_HALF_EVEN would give 0.02 as well.
    # This one distinguishes them: 0.125 -> 0.13, where half-even gives 0.12.
    item = build_item(unit_price=Decimal("0.25"), quantity=Decimal("0.500"))

    assert item.line_total == Decimal("0.13")
    assert line_total_for(
        unit_price=Decimal("0.25"), quantity=Decimal("0.500"), discount=Decimal("0.00")
    ) == Decimal("0.13")


@pytest.mark.unit
def test_the_line_total_is_rounded_once_at_the_line() -> None:
    """A receipt prints two decimals per line, so the total is the sum of what is printed."""
    item = build_item(unit_price=Decimal("10.00"), quantity=Decimal("0.333"))

    assert item.line_total == Decimal("3.33")
    assert quantise_money(item.unit_price * item.quantity) == Decimal("3.33")


@pytest.mark.unit
def test_a_line_total_that_does_not_add_up_is_refused() -> None:
    item = build_item()
    with pytest.raises(EntityInvariantError, match="line_total must equal"):
        SaleItemModel(
            id=item.id,
            tenant_id=item.tenant_id,
            sale_id=item.sale_id,
            product_id=item.product_id,
            product_name_snapshot=item.product_name_snapshot,
            unit_price=item.unit_price,
            quantity=item.quantity,
            line_total=Decimal("1.00"),
            created_at=NOW,
        )


@pytest.mark.unit
def test_a_discount_larger_than_the_line_is_refused() -> None:
    """That is a refund, not a discount, and recording it as one hides the money."""
    with pytest.raises(EntityInvariantError, match="cannot exceed the line"):
        build_item(
            unit_price=Decimal("10.00"),
            quantity=Decimal("1.000"),
            discount_amount=Decimal("11.00"),
        )


@pytest.mark.unit
def test_a_free_line_is_a_full_discount() -> None:
    item = build_item(
        unit_price=Decimal("10.00"), quantity=Decimal("1.000"), discount_amount=Decimal("10.00")
    )

    assert item.line_total == Decimal("0.00")


@pytest.mark.unit
@pytest.mark.parametrize("quantity", [Decimal("0.000"), Decimal("-1.000")])
def test_a_line_has_to_be_for_something(quantity: Decimal) -> None:
    """A line of nothing would write a movement that changes nothing, which the ledger refuses."""
    with pytest.raises(EntityInvariantError, match="greater than zero"):
        build_item(quantity=quantity)


@pytest.mark.unit
def test_a_negative_price_is_refused() -> None:
    with pytest.raises(EntityInvariantError):
        build_item(unit_price=Decimal("-1.00"))


@pytest.mark.unit
def test_a_price_with_more_than_two_places_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="two decimal places"):
        build_item(unit_price=Decimal("10.005"))


@pytest.mark.unit
def test_the_product_name_is_a_snapshot() -> None:
    """A receipt keeps saying what was sold after the product is renamed."""
    item = build_item(product_name="Rice 50kg")

    assert item.product_name_snapshot == "Rice 50kg"


@pytest.mark.unit
def test_an_empty_product_name_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="product_name_snapshot is empty"):
        build_item(product_name="   ")


@pytest.mark.unit
def test_the_item_audit_description_carries_amounts_and_identifiers() -> None:
    item = build_item()

    description = item.describe_for_audit()

    assert set(description) == {
        "sale_item_id",
        "tenant_id",
        "sale_id",
        "product_id",
        "quantity",
        "unit_price",
        "line_total",
    }


# ---------------------------------------------------------------------------
# Sale totals
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_sale_total_is_its_subtotal_less_its_discount() -> None:
    sale = build_sale(subtotal=Decimal("85000.00"), discount_amount=Decimal("5000.00"))

    assert sale.total_amount == Decimal("80000.00")
    assert sale.status is SaleStatus.COMPLETED
    assert sale.payment_status is SalePaymentStatus.UNPAID


@pytest.mark.unit
def test_a_sale_total_that_does_not_add_up_is_refused() -> None:
    sale = build_sale()
    with pytest.raises(EntityInvariantError, match="total_amount must equal"):
        SaleModel(
            id=sale.id,
            tenant_id=sale.tenant_id,
            receipt_number=sale.receipt_number,
            seller_id=sale.seller_id,
            subtotal=sale.subtotal,
            discount_amount=sale.discount_amount,
            total_amount=Decimal("1.00"),
            occurred_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.unit
def test_a_sale_discount_larger_than_the_subtotal_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="cannot exceed the subtotal"):
        build_sale(subtotal=Decimal("100.00"), discount_amount=Decimal("101.00"))


@pytest.mark.unit
def test_a_receipt_number_is_required() -> None:
    with pytest.raises(EntityInvariantError, match="receipt_number is empty"):
        build_sale(receipt_number="   ")


@pytest.mark.unit
def test_an_overlong_receipt_number_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="receipt_number exceeds"):
        build_sale(receipt_number="R" * 41)


@pytest.mark.unit
def test_a_sale_starts_with_nothing_paid() -> None:
    assert build_sale().payment_status is SalePaymentStatus.UNPAID
    assert build_sale().is_settled() is False


# ---------------------------------------------------------------------------
# Payment status is derived
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("paid", "expected"),
    [
        (Decimal("0.00"), SalePaymentStatus.UNPAID),
        (Decimal("100.00"), SalePaymentStatus.PARTIALLY_PAID),
        (Decimal("79999.99"), SalePaymentStatus.PARTIALLY_PAID),
        (Decimal("80000.00"), SalePaymentStatus.PAID),
        (Decimal("90000.00"), SalePaymentStatus.PAID),
    ],
)
def test_the_payment_status_follows_the_money(paid: Decimal, expected: SalePaymentStatus) -> None:
    assert payment_status_for(amount_paid=paid, total_amount=Decimal("80000.00")) is expected


@pytest.mark.unit
def test_a_sale_of_nothing_is_settled() -> None:
    """Calling a free item unpaid would leave it outstanding for ever."""
    assert (
        payment_status_for(amount_paid=Decimal("0.00"), total_amount=Decimal("0.00"))
        is SalePaymentStatus.PAID
    )


@pytest.mark.unit
def test_a_sale_can_be_settled_by_its_payments() -> None:
    sale = build_sale(subtotal=Decimal("85000.00"), discount_amount=Decimal("5000.00"))

    settled = sale.with_payment_status_for(amount_paid=Decimal("80000.00"), at=LATER)

    assert settled.payment_status is SalePaymentStatus.PAID
    assert settled.is_settled() is True
    assert settled.updated_at == LATER


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cancelling_keeps_everything_and_records_why() -> None:
    sale = build_sale(customer_id=uuid4())

    cancelled = sale.cancelled(at=LATER, reason="customer changed their mind")

    assert cancelled.status is SaleStatus.CANCELLED
    assert cancelled.is_cancelled() is True
    assert cancelled.cancelled_at == LATER
    assert cancelled.cancellation_reason == "customer changed their mind"
    assert cancelled.receipt_number == sale.receipt_number, "the number is not reused"
    assert cancelled.customer_id == sale.customer_id
    assert cancelled.total_amount == sale.total_amount


@pytest.mark.unit
def test_cancelling_twice_keeps_the_first_reason() -> None:
    """The first cancellation is the one that moved the stock and the money."""
    first = build_sale().cancelled(at=LATER, reason="wrong item")
    second = first.cancelled(at=LATER + timedelta(hours=1), reason="something else")

    assert second.cancellation_reason == "wrong item"
    assert second.cancelled_at == LATER


@pytest.mark.unit
def test_a_cancelled_sale_must_say_why() -> None:
    sale = build_sale()
    with pytest.raises(EntityInvariantError, match="must record why"):
        SaleModel(
            id=sale.id,
            tenant_id=sale.tenant_id,
            receipt_number=sale.receipt_number,
            seller_id=sale.seller_id,
            subtotal=sale.subtotal,
            discount_amount=sale.discount_amount,
            total_amount=sale.total_amount,
            occurred_at=NOW,
            created_at=NOW,
            updated_at=NOW,
            status=SaleStatus.CANCELLED,
            cancelled_at=LATER,
        )


@pytest.mark.unit
def test_a_cancelled_sale_must_say_when() -> None:
    sale = build_sale()
    with pytest.raises(EntityInvariantError, match="must record when"):
        SaleModel(
            id=sale.id,
            tenant_id=sale.tenant_id,
            receipt_number=sale.receipt_number,
            seller_id=sale.seller_id,
            subtotal=sale.subtotal,
            discount_amount=sale.discount_amount,
            total_amount=sale.total_amount,
            occurred_at=NOW,
            created_at=NOW,
            updated_at=NOW,
            status=SaleStatus.CANCELLED,
            cancellation_reason="wrong item",
        )


@pytest.mark.unit
def test_a_live_sale_cannot_carry_cancellation_details() -> None:
    sale = build_sale()
    with pytest.raises(EntityInvariantError, match="cannot carry cancellation details"):
        SaleModel(
            id=sale.id,
            tenant_id=sale.tenant_id,
            receipt_number=sale.receipt_number,
            seller_id=sale.seller_id,
            subtotal=sale.subtotal,
            discount_amount=sale.discount_amount,
            total_amount=sale.total_amount,
            occurred_at=NOW,
            created_at=NOW,
            updated_at=NOW,
            cancellation_reason="not cancelled though",
        )


@pytest.mark.unit
def test_the_sale_audit_description_carries_the_customer_identifier_and_not_a_name() -> None:
    sale = build_sale(customer_id=uuid4())

    description = sale.describe_for_audit()

    assert description["receipt_number"] == "OBI-000001"
    assert "customer_id" in description
    assert len(description) == 8
    assert sale.describe_for_audit()["total_amount"] == "85000.00"


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_payment_records_money_that_arrived() -> None:
    payment = PaymentModel.received(
        payment_id=uuid4(),
        tenant_id=uuid4(),
        sale_id=uuid4(),
        amount=Decimal("80000.00"),
        method=PaymentMethod.CASH,
        now=NOW,
    )

    assert payment.status is PaymentStatus.COMPLETED
    assert payment.counts_towards_the_sale() is True
    assert payment.is_refunded() is False
    assert payment.received_at == NOW


@pytest.mark.unit
@pytest.mark.parametrize("amount", [Decimal("0.00"), Decimal("-1.00")])
def test_a_payment_has_to_be_for_money(amount: Decimal) -> None:
    with pytest.raises(EntityInvariantError, match="below"):
        PaymentModel.received(
            payment_id=uuid4(),
            tenant_id=uuid4(),
            sale_id=uuid4(),
            amount=amount,
            method=PaymentMethod.CASH,
            now=NOW,
        )


@pytest.mark.unit
def test_a_payment_of_a_float_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="must be a Decimal"):
        PaymentModel.received(
            payment_id=uuid4(),
            tenant_id=uuid4(),
            sale_id=uuid4(),
            amount=80000.0,  # type: ignore[arg-type]
            method=PaymentMethod.CASH,
            now=NOW,
        )


@pytest.mark.unit
def test_only_the_methods_the_product_accepts_exist() -> None:
    """A gateway this product cannot verify is not a method it may claim."""
    assert {method.value for method in PaymentMethod} == {"CASH", "BANK_TRANSFER", "OTHER"}


@pytest.mark.unit
def test_a_transfer_reference_is_kept_for_reconciliation() -> None:
    payment = PaymentModel.received(
        payment_id=uuid4(),
        tenant_id=uuid4(),
        sale_id=uuid4(),
        amount=Decimal("5000.00"),
        method=PaymentMethod.BANK_TRANSFER,
        now=NOW,
        reference="  GTB-88231  ",
    )

    assert payment.reference == "GTB-88231"
    assert "GTB-88231" not in repr(payment.describe_for_audit())


@pytest.mark.unit
def test_an_empty_reference_becomes_absent() -> None:
    payment = PaymentModel.received(
        payment_id=uuid4(),
        tenant_id=uuid4(),
        sale_id=uuid4(),
        amount=Decimal("5000.00"),
        method=PaymentMethod.CASH,
        now=NOW,
        reference="   ",
    )

    assert payment.reference is None


@pytest.mark.unit
def test_refunding_keeps_the_amount_and_records_when() -> None:
    """What was taken is a fact; the refund is a second fact recorded against it."""
    payment = PaymentModel.received(
        payment_id=uuid4(),
        tenant_id=uuid4(),
        sale_id=uuid4(),
        amount=Decimal("80000.00"),
        method=PaymentMethod.CASH,
        now=NOW,
    )

    refunded = payment.refunded(at=LATER)

    assert refunded.amount == payment.amount
    assert refunded.status is PaymentStatus.REFUNDED
    assert refunded.refunded_at == LATER
    assert refunded.counts_towards_the_sale() is False
    assert refunded.refunded(at=LATER) == refunded, "refunding twice changes nothing"


@pytest.mark.unit
def test_a_refunded_amount_cannot_settle_a_sale() -> None:
    sale = build_sale(subtotal=Decimal("80000.00"))
    payment = PaymentModel.received(
        payment_id=uuid4(),
        tenant_id=sale.tenant_id,
        sale_id=sale.id,
        amount=Decimal("80000.00"),
        method=PaymentMethod.CASH,
        now=NOW,
    ).refunded(at=LATER)

    standing = sum(
        (entry.amount for entry in [payment] if entry.counts_towards_the_sale()),
        Decimal("0.00"),
    )

    assert sale.with_payment_status_for(amount_paid=standing, at=LATER).payment_status is (
        SalePaymentStatus.UNPAID
    )


@pytest.mark.unit
def test_a_payment_is_immutable() -> None:
    payment = PaymentModel.received(
        payment_id=uuid4(),
        tenant_id=uuid4(),
        sale_id=uuid4(),
        amount=Decimal("100.00"),
        method=PaymentMethod.CASH,
        now=NOW,
    )
    with pytest.raises(FrozenInstanceError):
        payment.amount = Decimal("200.00")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Ledger entries
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_revenue_is_a_credit_and_takes_its_direction_from_its_type() -> None:
    entry = LedgerEntryModel.record(
        entry_id=uuid4(),
        tenant_id=uuid4(),
        entry_type=LedgerEntryType.SALE_REVENUE,
        amount=Decimal("80000.00"),
        reference_type="sale",
        reference_id=uuid4(),
        now=NOW,
    )

    assert entry.direction is LedgerDirection.CREDIT
    assert entry.signed_amount() == Decimal("80000.00")


@pytest.mark.unit
def test_a_refund_is_a_debit() -> None:
    entry = LedgerEntryModel.record(
        entry_id=uuid4(),
        tenant_id=uuid4(),
        entry_type=LedgerEntryType.REFUND,
        amount=Decimal("80000.00"),
        reference_type="sale",
        reference_id=uuid4(),
        now=NOW,
    )

    assert entry.direction is LedgerDirection.DEBIT
    assert entry.signed_amount() == Decimal("-80000.00")


@pytest.mark.unit
def test_a_direction_that_contradicts_the_type_is_refused() -> None:
    """Revenue filed as a debit would make a month's report wrong by twice the amount."""
    with pytest.raises(EntityInvariantError, match="is always CREDIT"):
        LedgerEntryModel.record(
            entry_id=uuid4(),
            tenant_id=uuid4(),
            entry_type=LedgerEntryType.SALE_REVENUE,
            amount=Decimal("100.00"),
            reference_type="sale",
            reference_id=uuid4(),
            now=NOW,
            direction=LedgerDirection.DEBIT,
        )


@pytest.mark.unit
def test_an_adjustment_must_say_which_way_it_moves() -> None:
    with pytest.raises(EntityInvariantError, match="either way"):
        LedgerEntryModel.record(
            entry_id=uuid4(),
            tenant_id=uuid4(),
            entry_type=LedgerEntryType.ADJUSTMENT,
            amount=Decimal("100.00"),
            reference_type="stock_take",
            reference_id=uuid4(),
            now=NOW,
        )


@pytest.mark.unit
def test_an_adjustment_may_go_either_way() -> None:
    for direction in (LedgerDirection.CREDIT, LedgerDirection.DEBIT):
        entry = LedgerEntryModel.record(
            entry_id=uuid4(),
            tenant_id=uuid4(),
            entry_type=LedgerEntryType.ADJUSTMENT,
            amount=Decimal("100.00"),
            reference_type="stock_take",
            reference_id=uuid4(),
            now=NOW,
            direction=direction,
        )
        assert entry.direction is direction


@pytest.mark.unit
def test_an_entry_must_say_what_caused_it() -> None:
    with pytest.raises(EntityInvariantError, match="what caused it"):
        LedgerEntryModel.record(
            entry_id=uuid4(),
            tenant_id=uuid4(),
            entry_type=LedgerEntryType.EXPENSE,
            amount=Decimal("100.00"),
            reference_type="   ",
            reference_id=uuid4(),
            now=NOW,
        )


@pytest.mark.unit
@pytest.mark.parametrize("amount", [Decimal("0.00"), Decimal("-100.00")])
def test_an_entry_has_to_be_for_money(amount: Decimal) -> None:
    """The direction carries the sign, so a zero or negative amount records nothing."""
    with pytest.raises(EntityInvariantError, match="below"):
        LedgerEntryModel.record(
            entry_id=uuid4(),
            tenant_id=uuid4(),
            entry_type=LedgerEntryType.EXPENSE,
            amount=amount,
            reference_type="expense",
            reference_id=uuid4(),
            now=NOW,
        )


@pytest.mark.unit
def test_the_ledger_audit_description_carries_the_reference() -> None:
    reference_id = uuid4()
    entry = LedgerEntryModel.record(
        entry_id=uuid4(),
        tenant_id=uuid4(),
        entry_type=LedgerEntryType.SALE_REVENUE,
        amount=Decimal("80000.00"),
        reference_type="sale",
        reference_id=reference_id,
        now=NOW,
    )

    description = entry.describe_for_audit()

    assert description["reference_id"] == str(reference_id)
    assert description["entry_type"] == "SALE_REVENUE"
    assert set(description) == {
        "ledger_entry_id",
        "tenant_id",
        "entry_type",
        "direction",
        "amount",
        "reference_type",
        "reference_id",
    }


@pytest.mark.unit
def test_the_ledger_entry_has_no_transitions() -> None:
    """Append-only: a correction is another entry, so this entity has nothing to change."""
    entry_methods = {
        name
        for name in dir(LedgerEntryModel)
        if not name.startswith("_") and callable(getattr(LedgerEntryModel, name))
    }

    assert entry_methods == {"record", "signed_amount", "describe_for_audit"}


@pytest.mark.unit
def test_every_entity_in_the_sale_slice_carries_its_tenant() -> None:
    tenant_id = uuid4()
    sale = build_sale(tenant_id=tenant_id)
    item = build_item(tenant_id=tenant_id, sale_id=sale.id)
    payment = PaymentModel.received(
        payment_id=uuid4(),
        tenant_id=tenant_id,
        sale_id=sale.id,
        amount=Decimal("100.00"),
        method=PaymentMethod.CASH,
        now=NOW,
    )
    entry = LedgerEntryModel.record(
        entry_id=uuid4(),
        tenant_id=tenant_id,
        entry_type=LedgerEntryType.SALE_REVENUE,
        amount=Decimal("100.00"),
        reference_type="sale",
        reference_id=sale.id,
        now=NOW,
    )

    assert {sale.tenant_id, item.tenant_id, payment.tenant_id, entry.tenant_id} == {tenant_id}
    assert isinstance(sale.id, UUID)
