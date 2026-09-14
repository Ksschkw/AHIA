"""A ledger entry: what a transaction did to the business's money.

The ledger is the financial counterpart of the stock movement table, and it follows the
same rules for the same reasons: entries are appended, never edited, and a correction is
another entry. A business's revenue for a month is the sum of its entries, and a sum that
can be edited is not a fact anybody can rely on. The table carries a trigger that refuses
UPDATE and DELETE.

**Every entry names what caused it.** `reference_type` and `reference_id` point at the sale,
the expense or the refund, and both are required: an entry that cannot be attributed is a
number somebody has to explain by memory. This is the difference between a ledger and a
running total.

**The direction is explicit, and the amount is always positive.** `CREDIT` is money coming
in to the business and `DEBIT` is money going out, so a reader who sorts by amount is not
misled by signs that depend on which side of the books they are standing. It also means an
amount can never be accidentally negated twice - once by the sign and once by the type.

**Entries are derived, not chosen.** The specification says the ledger should be derived
from transactional facts where possible. Nothing in this product writes an entry by hand:
the service writes them inside the transaction that writes the sale, the payment and the
movement, which is what keeps the four in agreement.
"""

from __future__ import annotations

from dataclasses import dataclass
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

MAXIMUM_REFERENCE_TYPE_LENGTH: Final[int] = 64
MAXIMUM_DESCRIPTION_LENGTH: Final[int] = 500


class LedgerEntryType(StrEnum):
    """What kind of financial event this is.

    A closed set. An unknown type means either a feature nobody registered here or a value
    that arrived from somewhere it should not have, and both are worse than a refused write.
    """

    SALE_REVENUE = "SALE_REVENUE"
    SALE_DISCOUNT = "SALE_DISCOUNT"
    REFUND = "REFUND"
    EXPENSE = "EXPENSE"
    STOCK_PURCHASE = "STOCK_PURCHASE"
    ADJUSTMENT = "ADJUSTMENT"


class LedgerDirection(StrEnum):
    """Which way the money moved, from the business's point of view."""

    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


#: What each entry type means for the business's money, so a report does not have to guess
#: and a caller cannot file revenue as a debit by mistake.
_EXPECTED_DIRECTION: Final[dict[LedgerEntryType, LedgerDirection]] = {
    LedgerEntryType.SALE_REVENUE: LedgerDirection.CREDIT,
    LedgerEntryType.SALE_DISCOUNT: LedgerDirection.DEBIT,
    LedgerEntryType.REFUND: LedgerDirection.DEBIT,
    LedgerEntryType.EXPENSE: LedgerDirection.DEBIT,
    LedgerEntryType.STOCK_PURCHASE: LedgerDirection.DEBIT,
    # An adjustment may go either way: it corrects a figure that was wrong, and which way
    # it moves depends on which way the mistake went.
}


@dataclass(frozen=True, slots=True)
class LedgerEntryModel:
    """One entry in the financial ledger."""

    id: UUID
    tenant_id: UUID
    entry_type: LedgerEntryType
    direction: LedgerDirection
    amount: Decimal
    reference_type: str
    reference_id: UUID
    occurred_at: datetime
    created_at: datetime
    description: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.occurred_at, field_name="occurred_at", entry_id=self.id)
        _require_aware(self.created_at, field_name="created_at", entry_id=self.id)

        # Strictly positive: the direction carries the sign, and a zero entry records
        # nothing while looking like it does.
        _require_positive_money(self.amount, field_name="amount", entry_id=self.id)

        reference = self.reference_type.strip()
        if not reference:
            raise EntityInvariantError(
                operation="record_ledger_entry",
                entity="ledger_entry",
                identifier=str(self.id),
                detail="reference_type is required: an entry has to say what caused it",
            )
        if len(reference) > MAXIMUM_REFERENCE_TYPE_LENGTH:
            raise EntityInvariantError(
                operation="record_ledger_entry",
                entity="ledger_entry",
                identifier=str(self.id),
                detail=f"reference_type exceeds {MAXIMUM_REFERENCE_TYPE_LENGTH} characters",
            )

        expected = _EXPECTED_DIRECTION.get(self.entry_type)
        if expected is not None and self.direction is not expected:
            raise EntityInvariantError(
                operation="record_ledger_entry",
                entity="ledger_entry",
                identifier=str(self.id),
                detail=(
                    f"{self.entry_type.value} is always {expected.value}, "
                    f"not {self.direction.value}"
                ),
            )

        if self.description is not None:
            if not self.description.strip():
                raise EntityInvariantError(
                    operation="record_ledger_entry",
                    entity="ledger_entry",
                    identifier=str(self.id),
                    detail="description is empty; use None instead",
                )
            if len(self.description) > MAXIMUM_DESCRIPTION_LENGTH:
                raise EntityInvariantError(
                    operation="record_ledger_entry",
                    entity="ledger_entry",
                    identifier=str(self.id),
                    detail=f"description exceeds {MAXIMUM_DESCRIPTION_LENGTH} characters",
                )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def record(
        cls,
        *,
        entry_id: UUID,
        tenant_id: UUID,
        entry_type: LedgerEntryType,
        amount: Decimal,
        reference_type: str,
        reference_id: UUID,
        now: datetime,
        direction: LedgerDirection | None = None,
        description: str | None = None,
    ) -> LedgerEntryModel:
        """Build an entry, taking the direction its type implies unless told otherwise.

        The override exists for the one type that can go either way - an adjustment - and is
        refused for every other, so a caller cannot file revenue as a debit by passing a
        direction by accident.
        """
        resolved_direction = direction or _EXPECTED_DIRECTION.get(entry_type)
        if resolved_direction is None:
            raise EntityInvariantError(
                operation="record_ledger_entry",
                entity="ledger_entry",
                identifier=str(entry_id),
                detail=(
                    f"{entry_type.value} can move money either way; "
                    "say which direction this one moves"
                ),
            )
        return cls(
            id=entry_id,
            tenant_id=tenant_id,
            entry_type=entry_type,
            direction=resolved_direction,
            amount=amount,
            reference_type=reference_type.strip(),
            reference_id=reference_id,
            occurred_at=now,
            created_at=now,
            description=description.strip() if description else None,
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    def signed_amount(self) -> Decimal:
        """Return the amount as it affects the business's money.

        The one place the direction becomes a sign, so a report does not implement it three
        times and disagree with itself in one of them.
        """
        return self.amount if self.direction is LedgerDirection.CREDIT else -self.amount

    def describe_for_audit(self) -> dict[str, str]:
        """Return identifiers, the type, the direction and the amount."""
        return {
            "ledger_entry_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "entry_type": self.entry_type.value,
            "direction": self.direction.value,
            "amount": str(self.amount),
            "reference_type": self.reference_type,
            "reference_id": str(self.reference_id),
        }


def _require_positive_money(value: object, *, field_name: str, entry_id: UUID) -> None:
    """Raise unless the value is a Decimal amount greater than zero."""
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise EntityInvariantError(
            operation="record_ledger_entry",
            entity="ledger_entry",
            identifier=str(entry_id),
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
            operation="record_ledger_entry",
            entity="ledger_entry",
            identifier=str(entry_id),
            detail=str(invalid),
        ) from invalid


def _require_aware(moment: datetime, *, field_name: str, entry_id: UUID) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="record_ledger_entry",
            entity="ledger_entry",
            identifier=str(entry_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
