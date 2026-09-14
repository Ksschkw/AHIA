"""A payment: money that arrived against a sale.

**A payment is a fact about money that moved, so it is not edited.** Its amount is what was
handed over, and its status records what has since happened to that money - nothing else
about it changes. A correction is a second payment in the opposite direction, or a refund
of this one; there is no "set the amount to what it should have been", because that would
erase the fact that the wrong amount was taken.

**Method is a closed set, and only the methods the product supports are in it.** The
specification lists card and two Nigerian processors as future work. Naming them now would
let a client store a payment that claims to have gone through a gateway this product cannot
verify, which is a claim the business would then trust.

**A reference is optional and is never an identifier we control.** A transfer has a bank
reference; cash has none. It is stored for a reconciliation a person does by hand, so it is
free text with a length bound rather than a parsed value - and it is never used as a
credential.
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
)

MAXIMUM_REFERENCE_LENGTH: Final[int] = 64


class PaymentMethod(StrEnum):
    """How the money arrived. Only what this product can actually accept."""

    CASH = "CASH"
    BANK_TRANSFER = "BANK_TRANSFER"
    OTHER = "OTHER"


class PaymentStatus(StrEnum):
    """What has happened to the money since it arrived."""

    COMPLETED = "COMPLETED"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class PaymentModel:
    """One payment against one sale."""

    id: UUID
    tenant_id: UUID
    sale_id: UUID
    amount: Decimal
    method: PaymentMethod
    received_at: datetime
    created_at: datetime
    reference: str | None = None
    status: PaymentStatus = PaymentStatus.COMPLETED
    refunded_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name, moment in (
            ("received_at", self.received_at),
            ("created_at", self.created_at),
        ):
            _require_aware(moment, field_name=field_name, payment_id=self.id)
        if self.refunded_at is not None:
            _require_aware(self.refunded_at, field_name="refunded_at", payment_id=self.id)

        # Strictly positive: a payment of nothing is not a payment, and a negative one is a
        # refund recorded through the wrong door.
        _require_positive_money(self.amount, field_name="amount", payment_id=self.id)

        if self.reference is not None:
            if not self.reference.strip():
                raise EntityInvariantError(
                    operation="build_payment",
                    entity="payment",
                    identifier=str(self.id),
                    detail="reference is empty; use None instead",
                )
            if len(self.reference) > MAXIMUM_REFERENCE_LENGTH:
                raise EntityInvariantError(
                    operation="build_payment",
                    entity="payment",
                    identifier=str(self.id),
                    detail=f"reference exceeds {MAXIMUM_REFERENCE_LENGTH} characters",
                )

        if (self.status is PaymentStatus.REFUNDED) != (self.refunded_at is not None):
            raise EntityInvariantError(
                operation="build_payment",
                entity="payment",
                identifier=str(self.id),
                detail="a payment is refunded exactly when it records when it was refunded",
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def received(
        cls,
        *,
        payment_id: UUID,
        tenant_id: UUID,
        sale_id: UUID,
        amount: Decimal,
        method: PaymentMethod,
        now: datetime,
        reference: str | None = None,
    ) -> PaymentModel:
        """Build a payment for money that has been taken."""
        return cls(
            id=payment_id,
            tenant_id=tenant_id,
            sale_id=sale_id,
            amount=amount,
            method=method,
            reference=(reference.strip() or None) if reference else None,
            status=PaymentStatus.COMPLETED,
            received_at=now,
            created_at=now,
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    def is_refunded(self) -> bool:
        return self.status is PaymentStatus.REFUNDED

    def counts_towards_the_sale(self) -> bool:
        """Return True when this money is still held against the sale.

        A refunded payment no longer settles anything, which is what makes a cancelled
        sale's payment status come out as unpaid without anybody setting it.
        """
        return self.status is PaymentStatus.COMPLETED

    def describe_for_audit(self) -> dict[str, str]:
        """Return identifiers and the amount, never the reference.

        A bank reference is the closest thing here to a sensitive value - it can carry an
        account fragment - so it stays on the row and out of the logs. Support can read it
        from the record.
        """
        return {
            "payment_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "sale_id": str(self.sale_id),
            "amount": str(self.amount),
            "method": self.method.value,
            "status": self.status.value,
        }

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def refunded(self, *, at: datetime) -> PaymentModel:
        """Return the payment refunded.

        The amount does not change: what was taken is a fact, and the refund is a second
        fact recorded against it. Idempotent, because the first refund is the one that
        moved the money.
        """
        if self.is_refunded():
            return self
        return replace(self, status=PaymentStatus.REFUNDED, refunded_at=at)

    def failed(self) -> PaymentModel:
        """Return the payment marked as failed, for money that never arrived."""
        if self.status is PaymentStatus.FAILED:
            return self
        return replace(self, status=PaymentStatus.FAILED)


def _require_positive_money(value: object, *, field_name: str, payment_id: UUID) -> None:
    """Raise unless the value is a Decimal amount greater than zero.

    Typed as `object` because this is the check that makes the field's annotation true:
    Python does not enforce annotations, and a caller can pass anything.
    """
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise EntityInvariantError(
            operation="build_payment",
            entity="payment",
            identifier=str(payment_id),
            detail=f"{field_name} must be a Decimal, not {type(value).__name__}",
        )
    try:
        check_money_rules(
            value,
            field_name=field_name,
            minimum=ZERO_MONEY + Decimal("0.01"),
            maximum=MAXIMUM_MONEY,
        )
    except ValueError as invalid:
        raise EntityInvariantError(
            operation="build_payment",
            entity="payment",
            identifier=str(payment_id),
            detail=str(invalid),
        ) from invalid


def _require_aware(moment: datetime, *, field_name: str, payment_id: UUID) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="build_payment",
            entity="payment",
            identifier=str(payment_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
