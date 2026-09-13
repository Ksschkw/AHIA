"""What a business has decided about stock going negative.

A shop that sells offline can promise stock it has not physically counted yet. Two
workers sell the same last item before either phone syncs, and the arithmetic arrives at
a negative quantity. That is not a bug in the arithmetic - it is a real thing that
happened in a real shop - so what to do about it is a business decision, and this module
is where that decision is named.

Three policies, and the default is to refuse.

    BLOCK_NEGATIVE_STOCK       the movement is refused and the caller is told
    ALLOW_WITH_WARNING         the movement is recorded, and flagged as an overdraw
    ALLOW_NEGATIVE_STOCK       the movement is recorded silently

Why the default refuses
    A shop that has sold stock it does not have has a real problem - a miscount, a
    theft, or a double-sale - and the moment it appears is the cheapest moment to notice.
    Recording negative stock silently by default would hide the first symptom of the
    problem until a stock-take weeks later, when the cause is unrecoverable. A business
    that genuinely sells ahead of delivery can say so, once, and the choice is then
    visible in the tenant's own configuration rather than buried in a service.

Why this lives in the entity layer and not in `core`
    It is domain vocabulary, not infrastructure: the tenant stores it, the inventory
    service applies it, and nobody reads it from the environment. It is a separate module
    rather than a field on one of those entities because both need it, and an enum
    declared twice is two definitions of one concept.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class NegativeStockPolicy(StrEnum):
    """What happens when a movement would take a product below zero."""

    BLOCK_NEGATIVE_STOCK = "BLOCK_NEGATIVE_STOCK"
    ALLOW_WITH_WARNING = "ALLOW_WITH_WARNING"
    ALLOW_NEGATIVE_STOCK = "ALLOW_NEGATIVE_STOCK"

    @property
    def refuses_the_movement(self) -> bool:
        """Return True when a movement that would overdraw must be refused."""
        return self is NegativeStockPolicy.BLOCK_NEGATIVE_STOCK

    @property
    def flags_the_movement(self) -> bool:
        """Return True when an overdraw is recorded but marked for somebody to look at."""
        return self is NegativeStockPolicy.ALLOW_WITH_WARNING

    def describe(self) -> str:
        """Return a sentence an operator can act on."""
        if self.refuses_the_movement:
            return "stock cannot go negative; the movement is refused"
        if self.flags_the_movement:
            return "stock may go negative, and the movement is flagged as an overdraw"
        return "stock may go negative without a flag"


#: The policy a business gets until it chooses otherwise. A module-level singleton rather
#: than a call in a dataclass default: an enum member is immutable, so sharing one instance
#: is safe, and a default evaluated per instance is a default that could be mutated per
#: instance.
DEFAULT_NEGATIVE_STOCK_POLICY: Final[NegativeStockPolicy] = NegativeStockPolicy.BLOCK_NEGATIVE_STOCK

#: The same default as the name that is stored in the database.
DEFAULT_NEGATIVE_STOCK_POLICY_NAME: Final[str] = DEFAULT_NEGATIVE_STOCK_POLICY.value


def parse_negative_stock_policy(value: str) -> NegativeStockPolicy:
    """Return the policy a stored or configured string names.

    Raises ValueError rather than guessing: an unrecognised value is a configuration
    defect, and defaulting it silently would apply a policy the business did not choose.
    """
    try:
        return NegativeStockPolicy(value)
    except ValueError as invalid:
        allowed = ", ".join(policy.value for policy in NegativeStockPolicy)
        raise ValueError(
            f"{value!r} is not a negative stock policy; expected one of {allowed}"
        ) from invalid
