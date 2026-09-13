"""Tests for the shared slug rules.

Two entities address records by a slug, so this module is the one definition of what
a slug is. Its tests are unit tests: no database, no configuration, no fixture
beyond the values themselves - which is the condition that lets the entity layer
import it.
"""

from __future__ import annotations

import pytest

from ahia.core.slug import (
    MAXIMUM_SLUG_LENGTH,
    SLUG_PATTERN,
    normalize_slug,
    require_slug_shape,
)

# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Obi Electronics", "obi-electronics"),
        ("OBI  ELECTRONICS", "obi-electronics"),
        ("  Obi Electronics  ", "obi-electronics"),
        ("Obi's Electronics", "obi-s-electronics"),
        ("Drinks & Beverages", "drinks-beverages"),
        ("--Drinks--", "drinks"),
        ("a", "a"),
        ("TV", "tv"),
        ("Gluten Free / Dairy Free", "gluten-free-dairy-free"),
        ("", ""),
    ],
)
def test_normalisation_is_deterministic(raw: str, expected: str) -> None:
    """The same words must always produce the same slug, whoever wrote them."""
    assert normalize_slug(raw) == expected


@pytest.mark.unit
def test_names_that_look_alike_normalise_alike() -> None:
    """A person typing the same name twice must not create two records."""
    assert normalize_slug("Obi Electronics") == normalize_slug("obi  electronics")
    assert normalize_slug("Obi Electronics") == normalize_slug("OBI-ELECTRONICS")


@pytest.mark.unit
def test_normalisation_never_produces_a_leading_or_trailing_hyphen() -> None:
    for raw in ("--x--", "!value!", "  spaced  ", "a - b"):
        slug = normalize_slug(raw)
        assert slug == slug.strip("-")
        assert "--" not in slug


# ---------------------------------------------------------------------------
# Shape and bounds
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_shared_pattern_matches_what_normalisation_produces() -> None:
    for raw in ("Obi Electronics", "TV", "Drinks & Beverages", "a-b-c"):
        assert SLUG_PATTERN.match(normalize_slug(raw))


@pytest.mark.unit
@pytest.mark.parametrize("slug", ["obi-electronics", "a", "tv", "a1", "a" * 63])
def test_acceptable_shapes_are_accepted(slug: str) -> None:
    require_slug_shape(slug)


@pytest.mark.unit
@pytest.mark.parametrize(
    "slug",
    [
        "",
        "Obi-Electronics",
        "_leading",
        "trailing-",
        "double--hyphen",
        "with space",
        "with_underscore",
        "with.dot",
        "with/slash",
        "a" * (MAXIMUM_SLUG_LENGTH + 1),
    ],
)
def test_unacceptable_shapes_are_rejected(slug: str) -> None:
    with pytest.raises(ValueError):
        require_slug_shape(slug)


@pytest.mark.unit
def test_the_bounds_are_the_callers_contract_not_the_modules() -> None:
    """A published business slug is at least three characters; a category slug may be two.

    The shape is shared, the length is not, which is why the bounds are parameters
    rather than constants here.
    """
    require_slug_shape("tv")
    with pytest.raises(ValueError, match="between 3 and"):
        require_slug_shape("tv", minimum_length=3)
    with pytest.raises(ValueError, match="between 1 and 8"):
        require_slug_shape("a" * 9, maximum_length=8)


@pytest.mark.unit
def test_the_default_maximum_is_the_widest_bound_in_the_product() -> None:
    require_slug_shape("a" * MAXIMUM_SLUG_LENGTH)
    with pytest.raises(ValueError):
        require_slug_shape("a" * (MAXIMUM_SLUG_LENGTH + 1))
