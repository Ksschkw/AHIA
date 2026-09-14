"""Rendering money and quantities for the wire, in one place.

A price, a line total, a sale total, a payment and a ledger amount all leave this API as
decimal strings, and a stock quantity leaves with three decimal places. That rule was stated
in the product contract when products were the only thing with a price; sales have amounts
now too, and a second implementation of "how many places" would eventually disagree with the
first - which a client would discover as a total that does not equal the sum of the lines it
was shown.

The values are quantised to the places the columns store, so a price sent as `250` and
returned as `"250.00"` matches what the next read returns rather than echoing the shorter
form the caller happened to type.
"""

from __future__ import annotations

from decimal import Decimal

from ahia.models.entities.money import MONEY_PLACES, QUANTITY_PLACES


def money_text(value: Decimal) -> str:
    """Render an amount exactly as it is stored, for the wire."""
    return format(value.quantize(MONEY_PLACES), "f")


def quantity_text(value: Decimal) -> str:
    """Render a stock quantity exactly as it is stored, for the wire."""
    return format(value.quantize(QUANTITY_PLACES), "f")
