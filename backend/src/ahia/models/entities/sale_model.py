"""A sale: one completed transaction, and what it came to.

**Totals are checked against their parts.** `total_amount = subtotal - discount_amount`,
and the subtotal is the sum of the lines the service hands over. A caller cannot write a
sale whose total disagrees with what its lines add up to, and the service cannot compute
one total while the receipt prints another.

**Cancellation is a state, never a deletion.** A cancelled sale keeps its number, its lines,
its payments and its customer, because the money that moved still moved: the stock came
back and the cash went back, and both are recorded as their own events. Deleting the sale
would erase the fact that the refund happened. `cancelled` therefore sets a status, stamps
when it happened, and requires a reason - "why was this sale cancelled" is a question a
business asks before it asks anything else about a cancellation.

**Payment status is derived, never set by hand.** `with_payment_status_for(amount_paid)`
decides UNPAID, PARTIALLY_PAID or PAID from the money actually received, so a sale cannot
claim to be paid while its payments say otherwise. The service calls it after it has
summed the payments it is writing in the same transaction.

**The receipt number is per business and never reused.** Uniqueness is a database
constraint; this entity only refuses an empty one.
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
    quantise_money,
)

MAXIMUM_RECEIPT_NUMBER_LENGTH: Final[int] = 40
MAXIMUM_CANCELLATION_REASON_LENGTH: Final[int] = 500


class SaleStatus(StrEnum):
    """What happened to the sale as a whole."""

    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatus(StrEnum):
    """How much of the sale has been paid. Derived from the payments, never chosen."""

    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


def payment_status_for(*, amount_paid: Decimal, total_amount: Decimal) -> PaymentStatus:
    """Return the payment status the money received implies.

    A sale of nothing is paid: a zero total with nothing received is settled, and calling it
    unpaid would leave a free item permanently outstanding.
    """
    if amount_paid <= ZERO_MONEY and total_amount > ZERO_MONEY:
        return PaymentStatus.UNPAID
    if amount_paid < total_amount:
        return PaymentStatus.PARTIALLY_PAID
    return PaymentStatus.PAID


@dataclass(frozen=True, slots=True)
class SaleModel:
    """One sale."""

    id: UUID
    tenant_id: UUID
    receipt_number: str
    seller_id: UUID
    subtotal: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    occurred_at: datetime
    created_at: datetime
    updated_at: datetime
    customer_id: UUID | None = None
    device_id: UUID | None = None
    operation_id: UUID | None = None
    status: SaleStatus = SaleStatus.COMPLETED
    payment_status: PaymentStatus = PaymentStatus.UNPAID
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None

    def __post_init__(self) -> None:
        for field_name, moment in (
            ("occurred_at", self.occurred_at),
            ("created_at", self.created_at),
            ("updated_at", self.updated_at),
        ):
            _require_aware(moment, field_name=field_name, sale_id=self.id)
        if self.updated_at < self.created_at:
            raise EntityInvariantError(
                operation="build_sale",
                entity="sale",
                identifier=str(self.id),
                detail="updated_at is earlier than created_at",
            )

        receipt = self.receipt_number.strip()
        if not receipt:
            raise EntityInvariantError(
                operation="build_sale",
                entity="sale",
                identifier=str(self.id),
                detail="receipt_number is empty",
            )
        if len(receipt) > MAXIMUM_RECEIPT_NUMBER_LENGTH:
            raise EntityInvariantError(
                operation="build_sale",
                entity="sale",
                identifier=str(self.id),
                detail=f"receipt_number exceeds {MAXIMUM_RECEIPT_NUMBER_LENGTH} characters",
            )

        # Shape first, then the rule that relates the parts, then the bound on the derived
        # total: a discount larger than the subtotal should be reported as that, not as a
        # total below zero.
        for field_name, value in (
            ("subtotal", self.subtotal),
            ("discount_amount", self.discount_amount),
        ):
            _require_money(value, field_name=field_name, sale_id=self.id)
        _require_money_shape(self.total_amount, field_name="total_amount", sale_id=self.id)

        if self.discount_amount > self.subtotal:
            raise EntityInvariantError(
                operation="build_sale",
                entity="sale",
                identifier=str(self.id),
                detail="a discount cannot exceed the subtotal it discounts",
            )
        if self.total_amount < ZERO_MONEY:
            raise EntityInvariantError(
                operation="build_sale",
                entity="sale",
                identifier=str(self.id),
                detail="total_amount cannot be negative; a discount is not a refund",
            )
        expected_total = quantise_money(self.subtotal - self.discount_amount)
        if self.total_amount != expected_total:
            raise EntityInvariantError(
                operation="build_sale",
                entity="sale",
                identifier=str(self.id),
                detail=(
                    "total_amount must equal subtotal - discount_amount: "
                    f"{self.total_amount} != {expected_total}"
                ),
            )

        self._check_cancellation()

    def _check_cancellation(self) -> None:
        if self.status is SaleStatus.CANCELLED:
            if self.cancelled_at is None:
                raise EntityInvariantError(
                    operation="build_sale",
                    entity="sale",
                    identifier=str(self.id),
                    detail="a cancelled sale must record when it was cancelled",
                )
            _require_aware(self.cancelled_at, field_name="cancelled_at", sale_id=self.id)
            if not (self.cancellation_reason or "").strip():
                raise EntityInvariantError(
                    operation="build_sale",
                    entity="sale",
                    identifier=str(self.id),
                    detail="a cancelled sale must record why",
                )
            if len(self.cancellation_reason or "") > MAXIMUM_CANCELLATION_REASON_LENGTH:
                raise EntityInvariantError(
                    operation="build_sale",
                    entity="sale",
                    identifier=str(self.id),
                    detail=(
                        "cancellation_reason exceeds "
                        f"{MAXIMUM_CANCELLATION_REASON_LENGTH} characters"
                    ),
                )
            return

        if self.cancelled_at is not None or self.cancellation_reason is not None:
            raise EntityInvariantError(
                operation="build_sale",
                entity="sale",
                identifier=str(self.id),
                detail="a sale that is not cancelled cannot carry cancellation details",
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def issue(
        cls,
        *,
        sale_id: UUID,
        tenant_id: UUID,
        receipt_number: str,
        seller_id: UUID,
        subtotal: Decimal,
        now: datetime,
        discount_amount: Decimal = ZERO_MONEY,
        customer_id: UUID | None = None,
        device_id: UUID | None = None,
        operation_id: UUID | None = None,
        payment_status: PaymentStatus = PaymentStatus.UNPAID,
    ) -> SaleModel:
        """Build a sale, deriving the total from the subtotal and the discount."""
        quantised_subtotal = quantise_money(subtotal)
        quantised_discount = quantise_money(discount_amount)
        return cls(
            id=sale_id,
            tenant_id=tenant_id,
            receipt_number=receipt_number.strip(),
            seller_id=seller_id,
            subtotal=quantised_subtotal,
            discount_amount=quantised_discount,
            total_amount=quantise_money(quantised_subtotal - quantised_discount),
            customer_id=customer_id,
            device_id=device_id,
            operation_id=operation_id,
            status=SaleStatus.COMPLETED,
            payment_status=payment_status,
            occurred_at=now,
            created_at=now,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    def is_cancelled(self) -> bool:
        return self.status is SaleStatus.CANCELLED

    def is_settled(self) -> bool:
        """Return True when nothing is outstanding on this sale."""
        return self.payment_status is PaymentStatus.PAID

    def describe_for_audit(self) -> dict[str, str]:
        """Return identifiers, the receipt number and the totals.

        The customer's identifier travels; their name does not, because it belongs to a
        person who never signed up for this product. A receipt number is included because
        it is what a person quotes when they ask about a sale.
        """
        description = {
            "sale_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "receipt_number": self.receipt_number,
            "seller_id": str(self.seller_id),
            "status": self.status.value,
            "payment_status": self.payment_status.value,
            "total_amount": str(self.total_amount),
        }
        if self.customer_id is not None:
            description["customer_id"] = str(self.customer_id)
        return description

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def with_payment_status_for(self, *, amount_paid: Decimal, at: datetime) -> SaleModel:
        """Return the sale whose payment status matches the money received."""
        return replace(
            self,
            payment_status=payment_status_for(
                amount_paid=amount_paid, total_amount=self.total_amount
            ),
            updated_at=at,
        )

    def cancelled(self, *, at: datetime, reason: str) -> SaleModel:
        """Return the sale cancelled, with the reason it was.

        Idempotent: cancelling twice keeps the first reason and the first timestamp, because
        the first cancellation is the one that moved the stock and the money.
        """
        if self.is_cancelled():
            return self
        return replace(
            self,
            status=SaleStatus.CANCELLED,
            cancelled_at=at,
            cancellation_reason=reason.strip(),
            updated_at=at,
        )


def _require_money_shape(value: object, *, field_name: str, sale_id: UUID) -> None:
    """Check a derived amount's shape without bounding it, so the cause is reported first."""
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise EntityInvariantError(
            operation="build_sale",
            entity="sale",
            identifier=str(sale_id),
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
            operation="build_sale",
            entity="sale",
            identifier=str(sale_id),
            detail=str(invalid),
        ) from invalid


def _require_money(value: object, *, field_name: str, sale_id: UUID) -> None:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise EntityInvariantError(
            operation="build_sale",
            entity="sale",
            identifier=str(sale_id),
            detail=f"{field_name} must be a Decimal, not {type(value).__name__}",
        )
    try:
        check_money_rules(value, field_name=field_name, minimum=ZERO_MONEY, maximum=MAXIMUM_MONEY)
    except ValueError as invalid:
        raise EntityInvariantError(
            operation="build_sale",
            entity="sale",
            identifier=str(sale_id),
            detail=str(invalid),
        ) from invalid


def _require_aware(moment: datetime, *, field_name: str, sale_id: UUID) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="build_sale",
            entity="sale",
            identifier=str(sale_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
