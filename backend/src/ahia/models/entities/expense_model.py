"""An expense: money the business spent, and what it spent it on.

**An expense is a fact, not a record to be tidied.** The money left the business. Deleting
the row would not put it back, and it would leave the ledger entry that recorded it pointing
at nothing. So an expense is never deleted: a mistake is *reversed*, which stamps when and
why and writes the compensating ledger entry. `has_been_reversed` is then a fact a report can
filter on, and the original amount stays visible because the business did spend it and later
got it back.

**The amount is strictly positive for the same reason a ledger entry's is.** A negative
expense is a refund written by whoever is entering data, and a refund is an income event with
its own direction. Allowing the sign to flip here would make "total spent" a number that can
be reduced by typing a minus sign in the wrong place.

**The category is a closed set (see `expense_category`).** Spending reports group by it, so a
free-text category would produce a report whose headings depend on who typed them.

**`operation_id` is how a queued expense is written exactly once.** A phone that records an
expense offline will send it again after a timeout, and the business must not pay twice for
one bag of cement: the unique `(tenant_id, operation_id)` constraint turns the second arrival
into a replay rather than a second expense.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.expense_category import ExpenseCategory
from ahia.models.entities.money import (
    MAXIMUM_MONEY,
    ZERO_MONEY,
    check_money_rules,
    quantise_money,
)
from ahia.models.entities.payment_model import PaymentMethod

MAXIMUM_DESCRIPTION_LENGTH: Final[int] = 500
MAXIMUM_REVERSAL_REASON_LENGTH: Final[int] = 500


@dataclass(frozen=True, slots=True)
class ExpenseModel:
    """One expense a business recorded."""

    id: UUID
    tenant_id: UUID
    category: ExpenseCategory
    amount: Decimal
    payment_method: PaymentMethod
    incurred_at: datetime
    actor_id: UUID
    created_at: datetime
    device_id: UUID | None = None
    operation_id: UUID | None = None
    description: str | None = None
    reversed_at: datetime | None = None
    reversal_reason: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.incurred_at, field_name="incurred_at", expense_id=self.id)
        _require_aware(self.created_at, field_name="created_at", expense_id=self.id)
        _require_positive_money(self.amount, expense_id=self.id)

        if not isinstance(self.category, ExpenseCategory):
            raise EntityInvariantError(
                operation="record_expense",
                entity="expense",
                identifier=str(self.id),
                detail=(f"category must be an ExpenseCategory, not {type(self.category).__name__}"),
            )
        if not isinstance(self.payment_method, PaymentMethod):
            raise EntityInvariantError(
                operation="record_expense",
                entity="expense",
                identifier=str(self.id),
                detail=(
                    "payment_method must be a PaymentMethod, "
                    f"not {type(self.payment_method).__name__}"
                ),
            )

        if self.description is not None:
            if not self.description.strip():
                raise EntityInvariantError(
                    operation="record_expense",
                    entity="expense",
                    identifier=str(self.id),
                    detail="description is empty; use None instead",
                )
            if len(self.description) > MAXIMUM_DESCRIPTION_LENGTH:
                raise EntityInvariantError(
                    operation="record_expense",
                    entity="expense",
                    identifier=str(self.id),
                    detail=f"description exceeds {MAXIMUM_DESCRIPTION_LENGTH} characters",
                )

        self._check_reversal()

    def _check_reversal(self) -> None:
        if self.reversed_at is None:
            if self.reversal_reason is not None:
                raise EntityInvariantError(
                    operation="record_expense",
                    entity="expense",
                    identifier=str(self.id),
                    detail="an expense that has not been reversed cannot carry a reversal reason",
                )
            return

        _require_aware(self.reversed_at, field_name="reversed_at", expense_id=self.id)
        reason = (self.reversal_reason or "").strip()
        if not reason:
            raise EntityInvariantError(
                operation="record_expense",
                entity="expense",
                identifier=str(self.id),
                detail="a reversed expense must record why",
            )
        if len(reason) > MAXIMUM_REVERSAL_REASON_LENGTH:
            raise EntityInvariantError(
                operation="record_expense",
                entity="expense",
                identifier=str(self.id),
                detail=f"reversal_reason exceeds {MAXIMUM_REVERSAL_REASON_LENGTH} characters",
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def record(
        cls,
        *,
        expense_id: UUID,
        tenant_id: UUID,
        category: ExpenseCategory,
        amount: Decimal,
        payment_method: PaymentMethod,
        actor_id: UUID,
        now: datetime,
        description: str | None = None,
        device_id: UUID | None = None,
        operation_id: UUID | None = None,
        incurred_at: datetime | None = None,
    ) -> ExpenseModel:
        """Build an expense, quantising the amount and defaulting when it was incurred.

        `incurred_at` defaults to `now` because most expenses are entered as they are paid,
        and a caller that had to pass `now` twice would eventually pass two different values.
        A back-dated expense passes the day it was actually paid, which is the day the
        spending report should count it in.
        """
        return cls(
            id=expense_id,
            tenant_id=tenant_id,
            category=category,
            amount=quantise_money(_require_decimal(amount, expense_id=expense_id)),
            payment_method=payment_method,
            # A description of spaces is not a description. Storing it would put an empty
            # string in a column the schema promises holds text a person wrote.
            description=(description or "").strip() or None,
            incurred_at=incurred_at or now,
            actor_id=actor_id,
            device_id=device_id,
            operation_id=operation_id,
            created_at=now,
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    def has_been_reversed(self) -> bool:
        """Return True when this expense was undone and its money is accounted for."""
        return self.reversed_at is not None

    def counted_amount(self) -> Decimal:
        """Return what this expense contributes to total spending.

        Zero once reversed: the compensating ledger entry credits the money back, and a
        spending report that added the expense as well would count the same naira twice.
        """
        return ZERO_MONEY if self.has_been_reversed() else self.amount

    def describe_for_audit(self) -> dict[str, str]:
        """Return identifiers, the category and the amount.

        The description is left out: it is free text a person typed and it can contain
        anything, including a customer's name or a bank reference. An audit line needs to
        say which expense moved, not repeat what somebody wrote about it.
        """
        description = {
            "expense_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "category": self.category.value,
            "amount": str(self.amount),
            "payment_method": self.payment_method.value,
            "actor_id": str(self.actor_id),
            "reversed": "true" if self.has_been_reversed() else "false",
        }
        if self.device_id is not None:
            description["device_id"] = str(self.device_id)
        return description

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def reversed(self, *, at: datetime, reason: str) -> ExpenseModel:
        """Return the expense reversed, with the reason it was.

        Idempotent: reversing twice keeps the first reason and the first timestamp, because
        the first reversal is the one that wrote the compensating ledger entry and returned
        the money.
        """
        if self.has_been_reversed():
            return self
        return replace(self, reversed_at=at, reversal_reason=reason.strip())


def _require_decimal(value: object, *, expense_id: UUID) -> Decimal:
    """Return the value as a Decimal, or refuse it naming what arrived instead.

    Called before quantising, not only afterwards: `quantise_money` would raise an
    `AttributeError` on a float, which reads as a defect in this product rather than as a
    caller that passed the wrong type.
    """
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise EntityInvariantError(
            operation="record_expense",
            entity="expense",
            identifier=str(expense_id),
            detail=f"amount must be a Decimal, not {type(value).__name__}",
        )
    return value


def _require_positive_money(value: object, *, expense_id: UUID) -> None:
    amount = _require_decimal(value, expense_id=expense_id)
    try:
        check_money_rules(
            amount,
            field_name="amount",
            minimum=ZERO_MONEY + Decimal("0.01"),
            maximum=MAXIMUM_MONEY,
        )
    except ValueError as invalid:
        raise EntityInvariantError(
            operation="record_expense",
            entity="expense",
            identifier=str(expense_id),
            detail=str(invalid),
        ) from invalid


def _require_aware(moment: datetime, *, field_name: str, expense_id: UUID) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="record_expense",
            entity="expense",
            identifier=str(expense_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
