"""What a slug is, in one place.

A slug is the readable handle a record is addressed by: a business publishes one at
`/shop/{slug}`, a category is filtered by one, a product is linked by one. Two
records in this product need the same rule about what a slug may contain, and a rule
stated twice is a rule that drifts - one of them starts accepting an underscore and
the two disagree about whether "Obi Electronics" and "obi_electronics" are the same
identity.

Why this module is in `core` rather than in one entity
    It is consulted by entities, and the entity layer may import a core module only
    if that module is pure: standard library only, no configuration, no I/O. This file
    imports `re` and nothing else, and a test asserts that it stays that way (see
    ADR-0010 and tests/architecture/test_domain_vocabulary_purity.py).

What it deliberately does not decide
    Length. A business slug is published in a URL and is required to be at least
    three characters; a category slug is internal and may be two ("TV"). The shape is
    shared, the bounds are the caller's contract, so the bounds are parameters here
    rather than constants.
"""

from __future__ import annotations

import re
from typing import Final

#: Lowercase letters, digits and single hyphens between them. This shape is safe in
#: a URL path, safe in a subdomain, and cannot be confused with another slug by
#: removing punctuation.
SLUG_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: The widest bound any slug in this product uses. Callers pass their own narrower
#: limits; this exists so `normalize_slug` has a default that cannot be exceeded.
MAXIMUM_SLUG_LENGTH: Final[int] = 63


def normalize_slug(value: str) -> str:
    """Return the canonical slug for a name or a typed slug.

    Lowercases, replaces anything that is not a letter or a digit with a single
    hyphen, and trims the hyphens from the ends. Doing this here rather than trusting
    a client means "Obi Electronics" and "OBI  electronics" are the same name rather
    than two records that look identical to a person.
    """
    lowered = value.strip().lower()
    hyphenated = re.sub(r"[^a-z0-9]+", "-", lowered)
    return hyphenated.strip("-")


def require_slug_shape(
    slug: str,
    *,
    minimum_length: int = 1,
    maximum_length: int = MAXIMUM_SLUG_LENGTH,
) -> None:
    """Raise ValueError unless the slug has the shared shape and the caller's bounds.

    Raises ValueError rather than a domain error so that both callers can be honest
    about where the value came from: the schema layer converts it into a 422 for a
    client, and the entity layer converts it into an invariant violation, which is the
    difference between a bad request and a bug.
    """
    if len(slug) < minimum_length or len(slug) > maximum_length:
        raise ValueError(f"a slug must be between {minimum_length} and {maximum_length} characters")
    if not SLUG_PATTERN.match(slug):
        raise ValueError("a slug may contain lowercase letters, digits and single hyphens")
