"""What a phone number is, in one place.

Two entities store a phone number - a person's account and a business's customer - and
both need the same rule about what "the same number" means. A Nigerian trader writes
`0803 123 4567`, another client sends `+2348031234567`, and a customer typed at the
counter may arrive as `08031234567`. All three are one person, and a system that stores
them as three strings has three customers.

The rule has two halves, and they live apart on purpose.

**Syntax** is here: separators removed, a single leading plus preserved. No knowledge of
any country is needed, so an entity can apply it while building a value.

**Country completion** needs configuration, so `canonical_phone_number` takes the country
code as a parameter. An entity does not read configuration (ADR-0010), and inventing a
country for a number that does not state one is a decision only a configured caller can
make. A service that has the default country code passes it in.

Why this is not in `core`
    It is domain vocabulary rather than infrastructure: nothing here reads the
    environment, and the two things that need it are entities. Putting it in the entity
    layer keeps the core allowance at the three modules ADR-0010 names.
"""

from __future__ import annotations

import re
from typing import Final

#: Separators a person types between digit groups. Removed rather than rejected: a space
#: in a phone number is how people write them.
_PHONE_SEPARATORS: Final[re.Pattern[str]] = re.compile(r"[\s()\-.\u2010-\u2015]+")

#: Digits, with at most one leading plus, between seven and fifteen of them. The upper
#: bound is E.164's: no dialable number is longer, so accepting one would store a value
#: that cannot exist. The lower bound excludes short codes and typos - `12345` is a
#: service number or a slipped keystroke, and neither belongs in a customer record.
_PHONE_SHAPE: Final[re.Pattern[str]] = re.compile(r"^\+?[0-9]{7,15}$")

MAXIMUM_PHONE_LENGTH: Final[int] = 20


def normalize_phone_number(value: str | None) -> str | None:
    """Return the canonical *syntax* of a phone number, or None.

    Separators are removed and a single leading plus is preserved. Country-code
    completion needs configuration, so it belongs to the caller that has it; what belongs
    here is the shape, because uniqueness depends on it.
    """
    if value is None:
        return None
    without_separators = _PHONE_SEPARATORS.sub("", value.strip())
    return without_separators or None


def canonical_phone_number(value: str | None, *, default_country_code: str) -> str | None:
    """Return the E.164 form of a phone number, or None.

    `default_country_code` is the calling code including its plus, such as `+234`, and it
    completes a number written locally:

        0803 123 4567   ->  +2348031234567     (trunk prefix replaced by the code)
        8031234567      ->  +2348031234567     (no trunk prefix to replace)
        +2348031234567  ->  +2348031234567     (already international, left alone)
        +4480812345     ->  +4480812345        (a different country is not overridden)

    A number already in international form is never touched. Guessing a country for a
    number that states one would corrupt it, and the corruption would be invisible until
    somebody tried to call it.
    """
    normalized = normalize_phone_number(value)
    if normalized is None:
        return None
    if normalized.startswith("+"):
        return normalized
    if normalized.startswith("0"):
        # A trunk prefix is meaningful only locally, so it is replaced by the country code
        # rather than kept.
        return f"{default_country_code}{normalized[1:]}"
    return f"{default_country_code}{normalized}"


def international_digits_for(value: str | None, *, default_country_code: str) -> str | None:
    """Return the international digits of a phone number, or None.

    The form a dialler wants: `+2348031234567` without its plus, and no punctuation anywhere. It is
    the same normalisation the account and the customer record use, exposed in the one place that
    defines what a phone number is - a second implementation in an integration would eventually
    disagree with this one about a trunk prefix, and the disagreement would show up as a call to the
    wrong number.
    """
    canonical = canonical_phone_number(value, default_country_code=default_country_code)
    if canonical is None or not is_plausible_phone_number(canonical):
        return None
    return canonical.lstrip("+")


def is_plausible_phone_number(value: str) -> bool:
    """Return True when the string looks like a phone number this product can dial.

    Seven to fifteen digits, optionally with a leading plus: E.164's own bounds, which is
    what both the account and the customer record are storing. Strict about characters
    because a value with letters in it is a typo that would otherwise become a customer
    nobody can ever be matched against.
    """
    return bool(_PHONE_SHAPE.match(value)) and len(value) <= MAXIMUM_PHONE_LENGTH
