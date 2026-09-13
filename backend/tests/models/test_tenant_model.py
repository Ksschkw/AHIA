"""Tests for the tenant entity.

The slug is the part that reaches the public internet, so most of these tests are
about it: its shape, the names it may not take, and the fact that it cannot
change.
"""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

import ahia.models.entities.tenant_model as tenant_model_module
from ahia.core.errors import EntityInvariantError
from ahia.models.entities.tenant_model import (
    DEFAULT_COUNTRY,
    DEFAULT_CURRENCY,
    DEFAULT_TIMEZONE,
    MAXIMUM_SLUG_LENGTH,
    RESERVED_SLUGS,
    TenantModel,
    normalize_slug,
    validate_slug,
)

NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)


def build_tenant(**overrides: object) -> TenantModel:
    parameters: dict[str, object] = {
        "tenant_id": uuid4(),
        "name": "Obi Electronics",
        "slug": "obi-electronics",
        "now": NOW,
    }
    parameters.update(overrides)
    return TenantModel.create(**parameters)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_new_business_carries_the_market_defaults() -> None:
    tenant = build_tenant()

    assert tenant.is_active is True
    assert tenant.country == DEFAULT_COUNTRY
    assert tenant.currency == DEFAULT_CURRENCY
    assert tenant.timezone == DEFAULT_TIMEZONE
    assert tenant.created_at == NOW
    assert tenant.public_path == "/shop/obi-electronics"


@pytest.mark.unit
def test_the_name_and_contacts_are_trimmed_and_lowercased() -> None:
    tenant = build_tenant(
        name="  Obi Electronics  ",
        email="  SALES@Obi.example  ",
        phone="  +2348031234567  ",
        city="  Lagos  ",
    )

    assert tenant.name == "Obi Electronics"
    assert tenant.email == "sales@obi.example"
    assert tenant.phone == "+2348031234567"
    assert tenant.city == "Lagos"


@pytest.mark.unit
def test_an_empty_name_is_rejected() -> None:
    with pytest.raises(EntityInvariantError, match="name is empty"):
        build_tenant(name="   ")


@pytest.mark.unit
def test_an_overlong_name_is_rejected() -> None:
    with pytest.raises(EntityInvariantError, match="name exceeds"):
        build_tenant(name="A" * 121)


@pytest.mark.unit
def test_timestamps_must_carry_a_timezone() -> None:
    with pytest.raises(EntityInvariantError, match="naive datetime"):
        build_tenant(now=datetime(2026, 9, 13, 9, 30))  # noqa: DTZ001 - the input under test


@pytest.mark.unit
def test_update_cannot_predate_creation() -> None:
    with pytest.raises(EntityInvariantError, match="updated_at is earlier"):
        TenantModel(
            id=uuid4(),
            name="Obi Electronics",
            slug="obi-electronics",
            created_at=NOW,
            updated_at=NOW - timedelta(hours=1),
        )


@pytest.mark.unit
@pytest.mark.parametrize("country", ["N", "NGA", "12"])
def test_an_invalid_country_code_is_rejected(country: str) -> None:
    with pytest.raises(EntityInvariantError, match="country must be a two-letter code"):
        build_tenant(country=country)


@pytest.mark.unit
@pytest.mark.parametrize("currency", ["NG", "NAIRA", "12"])
def test_an_invalid_currency_code_is_rejected(currency: str) -> None:
    with pytest.raises(EntityInvariantError, match="currency must be a three-letter code"):
        build_tenant(currency=currency)


@pytest.mark.unit
def test_an_empty_timezone_is_rejected() -> None:
    with pytest.raises(EntityInvariantError, match="timezone is required"):
        build_tenant(timezone="   ")


# ---------------------------------------------------------------------------
# Slug shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Obi Electronics", "obi-electronics"),
        ("  Obi  Electronics  ", "obi-electronics"),
        ("OBI-ELECTRONICS", "obi-electronics"),
        ("Obi's Electronics", "obi-s-electronics"),
        ("Obi & Sons Ltd.", "obi-sons-ltd"),
        ("shop123", "shop123"),
        ("--obi--", "obi"),
        ("Obi___Electronics", "obi-electronics"),
    ],
)
def test_slug_normalization_is_stable(raw: str, expected: str) -> None:
    assert normalize_slug(raw) == expected


@pytest.mark.unit
def test_two_spellings_of_a_name_become_one_slug() -> None:
    first = build_tenant(name="Obi Electronics", slug="Obi Electronics")
    second = build_tenant(name="Obi Electronics", slug="obi-electronics")

    assert first.slug == second.slug == "obi-electronics"


@pytest.mark.unit
@pytest.mark.parametrize("slug", ["ab", "a" * (MAXIMUM_SLUG_LENGTH + 1)])
def test_a_slug_outside_the_length_bounds_is_rejected(slug: str) -> None:
    with pytest.raises(EntityInvariantError, match="invalid slug"):
        build_tenant(slug=slug)


@pytest.mark.unit
@pytest.mark.parametrize("slug", ["www", "api", "admin", "shop", "app", "health", "static"])
def test_infrastructure_names_are_rejected(slug: str) -> None:
    """A tenant that claimed `www` would shadow infrastructure and break its own link."""
    with pytest.raises(EntityInvariantError, match="invalid slug"):
        build_tenant(slug=slug)


@pytest.mark.unit
def test_every_reserved_slug_is_valid_in_shape_but_refused() -> None:
    """The reserved list must not rely on the shape rules to reject these."""
    for reserved in RESERVED_SLUGS:
        assert validate_reserved_shape(reserved)
        with pytest.raises(ValueError, match="reserved"):
            validate_slug(reserved)


def validate_reserved_shape(slug: str) -> bool:
    """Return True when a slug matches the pattern, ignoring the reserved list."""
    return bool(tenant_model_module.SLUG_PATTERN.match(slug))


@pytest.mark.unit
def test_a_slug_cannot_be_confused_by_removing_punctuation() -> None:
    """`obi-electronics` and `obielectronics` are different businesses, deliberately."""
    first = build_tenant(slug="obi-electronics")
    second = build_tenant(slug="obielectronics")

    assert first.slug != second.slug


# ---------------------------------------------------------------------------
# Immutability and transitions
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_entity_is_immutable() -> None:
    tenant = build_tenant()

    with pytest.raises(FrozenInstanceError):
        tenant.slug = "other-slug"  # type: ignore[misc]


@pytest.mark.unit
def test_there_is_no_slug_transition() -> None:
    """A published slug is published; a rename must not break an existing link."""
    assert not hasattr(build_tenant(), "with_slug")
    assert not hasattr(build_tenant(), "change_slug")


@pytest.mark.unit
def test_profile_update_changes_the_name_and_never_the_slug() -> None:
    tenant = build_tenant()
    later = NOW + timedelta(days=1)

    renamed = tenant.with_profile(name="Obi Home Appliances", at=later)

    assert renamed.name == "Obi Home Appliances"
    assert renamed.slug == tenant.slug
    assert renamed.updated_at == later
    assert tenant.name == "Obi Electronics"


@pytest.mark.unit
def test_profile_update_treats_none_as_unchanged() -> None:
    tenant = build_tenant(business_type="Electronics", city="Lagos")

    updated = tenant.with_profile(name="Obi Home Appliances", at=NOW + timedelta(minutes=1))

    assert updated.business_type == "Electronics"
    assert updated.city == "Lagos"


@pytest.mark.unit
def test_deactivation_and_activation() -> None:
    tenant = build_tenant()
    later = NOW + timedelta(days=30)

    deactivated = tenant.deactivate(at=later)

    assert deactivated.is_active is False
    assert deactivated.updated_at == later
    assert tenant.is_active is True

    assert deactivated.activate(at=later + timedelta(hours=1)).is_active is True


# ---------------------------------------------------------------------------
# Privacy and purity
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_audit_description_carries_no_contact_details() -> None:
    tenant = build_tenant(email="sales@obi.example", phone="+2348031234567")

    description = tenant.describe_for_audit()
    rendered = repr(description)

    assert set(description) == {"tenant_id", "tenant_slug", "is_active"}
    assert "sales@obi.example" not in rendered
    assert "+2348031234567" not in rendered


@pytest.mark.unit
def test_entity_imports_no_framework() -> None:
    """Domain purity, checked locally as well as by the architecture contract."""
    source = Path(tenant_model_module.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    forbidden = {
        "sqlalchemy",
        "pydantic",
        "fastapi",
        "httpx",
        "alembic",
        "asyncpg",
        "jwt",
        "argon2",
    }
    assert imported & forbidden == set()
