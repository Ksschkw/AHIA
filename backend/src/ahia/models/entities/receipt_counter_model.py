"""The receipt counter: the next number one business will issue.

A receipt number is what a customer quotes when they come back, so it has to be readable,
short enough to say aloud, and unique inside the business that issued it. This entity is the
row that knows the last number issued; the printing rule lives here with it, because a number
is only useful if the person holding the receipt can read it back.

**The prefix is set once and kept.** It comes from the business's slug on the first sale and
is stored with the counter afterwards, so a receipt reprinted a year later carries the same
prefix as the slip that was handed over - even if the business has since renamed itself.

**Numbers only go up.** `with_next_number` is the only transition, and it refuses to go
backwards: a counter that moved back would issue a number that is already on a receipt, and
the unique constraint would then reject a legitimate sale instead of a bug.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError

MAXIMUM_PREFIX_LENGTH: Final[int] = 12

#: How many digits the numeric part carries. Six is a million sales before the format
#: widens, and a fixed width keeps numbers sorted as text - which is how they appear in a
#: list, on a printed book, and in a customer's memory.
RECEIPT_NUMBER_DIGITS: Final[int] = 6

#: The prefix used when a business's slug yields nothing usable. A receipt number with no
#: prefix at all would be a bare number, which is ambiguous the moment a customer has
#: receipts from two businesses.
FALLBACK_PREFIX: Final[str] = "R"


def clean_receipt_prefix(prefix: str) -> str:
    """Return the prefix as it is stored: the first word of the slug, uppercase and short.

    A receipt number is read aloud over a counter, so it has to be a word rather than a
    fragment: the slug `obi-electronics` gives `OBI`, where truncating the whole slug to
    twelve characters would give `OBIELECTRONI`, which is neither a word nor a
    recognisable abbreviation. Anything that is not a letter or a digit is dropped, because
    punctuation in a number somebody reads aloud is eventually misheard.
    """
    # Split on the first separator a name is written with, so a prefix derived from a
    # business name and one derived from its slug produce the same tag.
    first_word = re.split(r"[\s-]+", prefix.strip())[0]
    cleaned = "".join(character for character in first_word.upper() if character.isalnum())
    return (cleaned or FALLBACK_PREFIX)[:MAXIMUM_PREFIX_LENGTH]


def render_receipt_number(*, prefix: str, number: int) -> str:
    """Return the receipt number a person reads: `OBI-000123`.

    The numeric part is padded, and a number wider than the padding widens rather than
    truncating: a business that has issued more than a million receipts should see a longer
    number, not a wrong one.
    """
    return f"{prefix}-{number:0{RECEIPT_NUMBER_DIGITS}d}"


@dataclass(frozen=True, slots=True)
class ReceiptCounterModel:
    """The highest receipt number one business has issued."""

    tenant_id: UUID
    last_receipt_number: int
    receipt_prefix: str
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.last_receipt_number < 0:
            raise EntityInvariantError(
                operation="build_receipt_counter",
                entity="receipt_counter",
                identifier=str(self.tenant_id),
                detail="last_receipt_number is negative",
            )
        if not self.receipt_prefix.strip():
            raise EntityInvariantError(
                operation="build_receipt_counter",
                entity="receipt_counter",
                identifier=str(self.tenant_id),
                detail="receipt_prefix is empty",
            )
        if len(self.receipt_prefix) > MAXIMUM_PREFIX_LENGTH:
            raise EntityInvariantError(
                operation="build_receipt_counter",
                entity="receipt_counter",
                identifier=str(self.tenant_id),
                detail=f"receipt_prefix exceeds {MAXIMUM_PREFIX_LENGTH} characters",
            )
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise EntityInvariantError(
                operation="build_receipt_counter",
                entity="receipt_counter",
                identifier=str(self.tenant_id),
                detail="updated_at is a naive datetime; timestamps must carry a timezone",
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def for_new_business(
        cls,
        *,
        tenant_id: UUID,
        prefix: str,
        now: datetime,
    ) -> ReceiptCounterModel:
        """Return the counter a business starts with, before it has issued anything."""
        return cls(
            tenant_id=tenant_id,
            last_receipt_number=0,
            receipt_prefix=clean_receipt_prefix(prefix),
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    def next_number(self) -> int:
        """Return the number the next sale will take, without claiming it."""
        return self.last_receipt_number + 1

    def render(self) -> str:
        """Return the last number issued, as a person reads it."""
        return render_receipt_number(prefix=self.receipt_prefix, number=self.last_receipt_number)

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def with_next_number(self, *, at: datetime) -> ReceiptCounterModel:
        """Return the counter advanced by one.

        Refuses to move backwards: a counter that went back would issue a number that is
        already printed on a receipt, and the unique constraint would then reject a
        legitimate sale rather than a bug.
        """
        return replace(
            self,
            last_receipt_number=self.last_receipt_number + 1,
            updated_at=at,
        )
