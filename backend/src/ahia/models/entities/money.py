"""What money is, in one place.

A price, a discount, a line total, a sale total, a payment and a ledger amount are all the
same kind of number, and they must agree about three things: how many decimal places they
carry, how a multiplication is rounded, and how one arrives from the wire. A sale whose
line total is computed by one rule and whose price was stored by another is a receipt that
does not add up, and the shopkeeper finds out in front of the customer.

Two decimal places, and rounding is half-up
    Money is `NUMERIC(18,2)` everywhere. A quantity carries three places, so
    `unit_price * quantity` can produce five, and something has to decide what happens to
    the extra. `ROUND_HALF_UP` is how people round money - 0.005 becomes 0.01 - and
    Python's default `ROUND_HALF_EVEN` would make 0.005 become 0.00, which is a kobo the
    shopkeeper cannot explain. The rule is stated once here so a line total, a sale total
    and a ledger entry cannot disagree.

A float is parsed through its own decimal text, never its binary value
    `Decimal(0.1)` is not one tenth. A number that arrived as JSON is converted through
    `str()`, which is what the client actually typed.

Why this is not in `core`
    It is domain vocabulary: nothing here reads configuration, and the entities that
    compute with money are in this layer. It is a separate module rather than a field on
    one of them because prices, totals and payments all need it, and a rule declared twice
    is a rule that drifts.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Final

#: Money is stored and compared with two decimal places.
MONEY_PLACES: Final[Decimal] = Decimal("0.01")

#: Quantities carry three, because stock is counted in kilos and litres as well as units.
QUANTITY_PLACES: Final[Decimal] = Decimal("0.001")

#: The largest amount a NUMERIC(18,2) column can hold, as this product uses it. A value
#: beyond it is a typo rather than an amount, and it is caught where it is parsed.
MAXIMUM_MONEY: Final[Decimal] = Decimal("999999999999.99")

#: The largest quantity, in the same unit as a product's stock threshold.
MAXIMUM_QUANTITY: Final[Decimal] = Decimal("999999999999.999")

ZERO_MONEY: Final[Decimal] = Decimal("0.00")
ZERO_QUANTITY: Final[Decimal] = Decimal("0.000")

#: The rounding every monetary calculation uses. Named so a reader can see the decision
#: rather than infer it from a call site.
MONEY_ROUNDING: Final[str] = ROUND_HALF_UP


def quantise_money(value: Decimal) -> Decimal:
    """Return the value rounded to two decimal places, half-up.

    Used for every derived amount: a line total, a sale subtotal, a payment sum. Calling it
    on a value that already carries two places changes nothing, which is what makes it safe
    to apply at each step of a calculation.
    """
    return value.quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def line_total_for(*, unit_price: Decimal, quantity: Decimal, discount: Decimal) -> Decimal:
    """Return the amount a sale line contributes: price times quantity, less its discount.

    The multiplication is rounded once, to the places money is stored in, rather than
    carried at full precision into a total: a receipt shows two decimals per line, and the
    total must equal the sum of what is printed.
    """
    return quantise_money(unit_price * quantity) - quantise_money(discount)


def quantise_quantity(value: Decimal) -> Decimal:
    """Return the value rounded to three decimal places, half-up."""
    return value.quantize(QUANTITY_PLACES, rounding=ROUND_HALF_UP)


def parse_decimal_like(value: object, *, field_name: str) -> Decimal:
    """Turn a wire value into a Decimal without ever going through a binary float.

    Accepts a Decimal, an int, a float or a string. A float is converted through its own
    decimal text: `Decimal(str(v))`, never `Decimal(v)`, because the latter exposes the
    binary approximation nobody typed.
    """
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field_name} must be a number")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{field_name} is empty")
        try:
            return Decimal(text)
        except InvalidOperation as invalid:
            raise ValueError(f"{field_name} is not a number") from invalid
    raise ValueError(f"{field_name} must be a number, not {type(value).__name__}")


def check_money_rules(
    value: Decimal,
    *,
    field_name: str,
    minimum: Decimal = ZERO_MONEY,
    maximum: Decimal = MAXIMUM_MONEY,
) -> None:
    """Raise ValueError unless the Decimal is an amount these columns can hold."""
    if not value.is_finite():
        raise ValueError(f"{field_name} is not a finite number")
    try:
        quantised = value.quantize(MONEY_PLACES)
    except InvalidOperation as unrepresentable:
        raise ValueError(
            f"{field_name} cannot be represented with two decimal places"
        ) from unrepresentable
    if quantised != value:
        raise ValueError(f"{field_name} has more than two decimal places")
    if value < minimum:
        raise ValueError(f"{field_name} is below {minimum}")
    if value > maximum:
        raise ValueError(f"{field_name} exceeds {maximum}")


def check_quantity_rules(
    value: Decimal,
    *,
    field_name: str,
    minimum: Decimal = ZERO_QUANTITY,
    maximum: Decimal = MAXIMUM_QUANTITY,
) -> None:
    """Raise ValueError unless the Decimal is a quantity these columns can hold."""
    if not value.is_finite():
        raise ValueError(f"{field_name} is not a finite number")
    if value.quantize(QUANTITY_PLACES) != value:
        raise ValueError(f"{field_name} has more than three decimal places")
    if value < minimum:
        raise ValueError(f"{field_name} is negative")
    if value > maximum:
        raise ValueError(f"{field_name} exceeds {maximum}")


def coerce_money(
    value: object,
    *,
    field_name: str,
    minimum: Decimal = ZERO_MONEY,
    maximum: Decimal = MAXIMUM_MONEY,
) -> Decimal:
    """Parse an amount from the wire and check it against the caller's bounds."""
    parsed = parse_decimal_like(value, field_name=field_name)
    check_money_rules(parsed, field_name=field_name, minimum=minimum, maximum=maximum)
    return parsed


def coerce_quantity(
    value: object,
    *,
    field_name: str = "quantity",
    minimum: Decimal = ZERO_QUANTITY,
    maximum: Decimal = MAXIMUM_QUANTITY,
) -> Decimal:
    """Parse a quantity from the wire and check it against the caller's bounds."""
    parsed = parse_decimal_like(value, field_name=field_name)
    check_quantity_rules(parsed, field_name=field_name, minimum=minimum, maximum=maximum)
    return parsed
