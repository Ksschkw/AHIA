"""What a business spends money on, as a closed set.

An expense category is what a spending report groups by, so it cannot be free text. A
business that types `transport`, `Transport` and `transport ` has three categories, and its
transport total is wrong in a way nobody can see - the report looks complete and is not.

**One word per concept, and the words a Nigerian shopkeeper uses.** These are the headings a
trader already keeps in a notebook, not an accountant's chart of accounts: buying goods to
resell, moving them, keeping the lights on, paying staff.

**`OTHER` is the escape hatch, and the description carries the detail.** A closed set with no
exit forces a person to file reality under the nearest wrong heading; a closed set with an
exit keeps the headings that reports depend on while accepting that a business will always
have one expense nobody anticipated. The description is where that detail goes.

**Why this is not configuration a business edits.** A tenant-editable category list would
make every report a different shape per business, and the first question anybody asks about a
spending report is what is in it. When a business needs a heading this product does not have,
the honest change is to add it here, once, where every business gets it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

#: How long a stored category value may be. A test asserts every member fits, so adding a
#: longer category fails the build instead of failing on the first expense somebody records.
MAXIMUM_VALUE_LENGTH: Final[int] = 40


class ExpenseCategory(StrEnum):
    """The headings a spending report groups by."""

    STOCK_PURCHASE = "STOCK_PURCHASE"
    TRANSPORT = "TRANSPORT"
    RENT = "RENT"
    UTILITIES = "UTILITIES"
    SALARIES = "SALARIES"
    PACKAGING = "PACKAGING"
    MARKETING = "MARKETING"
    MAINTENANCE = "MAINTENANCE"
    FEES_AND_LEVIES = "FEES_AND_LEVIES"
    OTHER = "OTHER"

    @property
    def is_known_spending(self) -> bool:
        """Return True when the category says what the money was for.

        `OTHER` does not: it says the business spent something and classified it nowhere,
        which a report should be able to spot rather than hide inside a total.
        """
        return self is not ExpenseCategory.OTHER

    def label(self) -> str:
        """Return the heading as a person reads it.

        Derived from the value rather than kept in a second table, so a category cannot be
        added without a label or renamed in one place and not the other.
        """
        return self.value.replace("_", " ").title()


def parse_expense_category(value: str) -> ExpenseCategory:
    """Return the category a stored or configured string names.

    Raises ValueError rather than guessing: an unrecognised value is either a category this
    version does not know or a free-text value that got in, and defaulting either to `OTHER`
    would silently move money into a heading nobody chose.
    """
    try:
        return ExpenseCategory(value)
    except ValueError as invalid:
        allowed = ", ".join(category.value for category in ExpenseCategory)
        raise ValueError(
            f"{value!r} is not an expense category; expected one of {allowed}"
        ) from invalid
