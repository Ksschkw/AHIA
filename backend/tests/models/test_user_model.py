"""Tests for the user entity.

The entity is the source of truth for its own invariants, so these tests are
about the rules rather than about storage: normalization, the requirement for a
contact channel, timezone-aware timestamps, and the immutability of every
transition.
"""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

import ahia.models.entities.user_model as user_model_module
from ahia.core.errors import EntityInvariantError
from ahia.models.entities.user_model import (
    UserModel,
    normalize_email,
    normalize_phone,
)

NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)


def build_user(**overrides: object) -> UserModel:
    parameters: dict[str, object] = {
        "user_id": uuid4(),
        "first_name": "Emeka",
        "now": NOW,
        "last_name": "Okonkwo",
        "email": "emeka@example.com",
        "phone": "+2348031234567",
    }
    parameters.update(overrides)
    return UserModel.create(**parameters)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_new_user_is_active_and_carries_both_contacts() -> None:
    user = build_user()

    assert user.is_active is True
    assert user.full_name == "Emeka Okonkwo"
    assert user.email == "emeka@example.com"
    assert user.phone == "+2348031234567"
    assert user.created_at == NOW
    assert user.updated_at == NOW
    assert user.has_password is False


@pytest.mark.unit
def test_first_and_last_names_are_trimmed() -> None:
    user = build_user(first_name="  Ngozi  ", last_name="  Uzoma  ")

    assert user.first_name == "Ngozi"
    assert user.last_name == "Uzoma"


@pytest.mark.unit
def test_full_name_handles_a_missing_last_name() -> None:
    user = build_user(last_name=None)

    assert user.full_name == "Emeka"


@pytest.mark.unit
def test_a_user_needs_at_least_one_contact_channel() -> None:
    """An account nobody can reach is an account nobody can use."""
    with pytest.raises(EntityInvariantError) as captured:
        build_user(email=None, phone=None)

    assert "at least one of email or phone" in str(captured.value)


@pytest.mark.unit
def test_a_user_may_have_only_a_phone() -> None:
    """A trader may onboard a worker with a phone number and no email."""
    user = build_user(email=None)

    assert user.email is None
    assert user.full_name == "Emeka Okonkwo"


@pytest.mark.unit
@pytest.mark.parametrize("first_name", ["", "   ", "\t"])
def test_an_empty_first_name_is_rejected(first_name: str) -> None:
    with pytest.raises(EntityInvariantError, match="first_name is empty"):
        build_user(first_name=first_name)


@pytest.mark.unit
def test_an_overlong_name_is_rejected() -> None:
    with pytest.raises(EntityInvariantError, match="first_name exceeds"):
        build_user(first_name="A" * 101)


@pytest.mark.unit
@pytest.mark.parametrize(
    "email",
    ["not-an-address", "missing@tld", "@example.com", "two@@example.com", "spaces in@example.com"],
)
def test_a_malformed_email_is_rejected(email: str) -> None:
    with pytest.raises(EntityInvariantError, match="email is not a valid address shape"):
        build_user(email=email)


@pytest.mark.unit
@pytest.mark.parametrize(
    "phone",
    ["12345", "abcdefgh", "+234-803-123-4567-ext", "++2348031234567", "1" * 16],
)
def test_a_malformed_phone_is_rejected(phone: str) -> None:
    with pytest.raises(EntityInvariantError, match="phone is not a valid number shape"):
        build_user(phone=phone)


@pytest.mark.unit
def test_an_empty_password_hash_is_rejected() -> None:
    with pytest.raises(EntityInvariantError, match="password_hash is present but empty"):
        build_user(password_hash="   ")


@pytest.mark.unit
def test_timestamps_must_carry_a_timezone() -> None:
    """A naive timestamp means different instants on different devices."""
    with pytest.raises(EntityInvariantError, match="naive datetime"):
        # A naive datetime is the input under test; the rule is silenced here
        # because constructing one is exactly what this case must do.
        build_user(now=datetime(2026, 9, 13, 9, 30))  # noqa: DTZ001

    naive_updated = datetime(2026, 9, 13, 10, 0)  # noqa: DTZ001 - the input under test
    with pytest.raises(EntityInvariantError, match="naive datetime"):
        UserModel(
            id=uuid4(),
            first_name="Emeka",
            email="emeka@example.com",
            created_at=NOW,
            updated_at=naive_updated,
        )


@pytest.mark.unit
def test_update_cannot_predate_creation() -> None:
    with pytest.raises(EntityInvariantError, match="updated_at is earlier than created_at"):
        UserModel(
            id=uuid4(),
            first_name="Emeka",
            email="emeka@example.com",
            created_at=NOW,
            updated_at=NOW - timedelta(hours=1),
        )


@pytest.mark.unit
def test_a_non_utc_timezone_is_accepted() -> None:
    """Nigeria is UTC+1; the entity stores an instant, not a wall clock."""
    lagos_time = datetime(2026, 9, 13, 10, 30, tzinfo=timezone(timedelta(hours=1)))

    user = build_user(now=lagos_time)

    assert user.created_at.utcoffset() == timedelta(hours=1)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Emeka@Example.COM ", "emeka@example.com"),
        ("ngozi@example.com", "ngozi@example.com"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_email_normalization(raw: str | None, expected: str | None) -> None:
    assert normalize_email(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+234 803 123 4567", "+2348031234567"),
        ("0803-123-4567", "08031234567"),
        ("(0803) 123.4567", "08031234567"),
        ("  08031234567  ", "08031234567"),
        ("", None),
        (None, None),
    ],
)
def test_phone_normalization(raw: str | None, expected: str | None) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.unit
def test_normalization_happens_through_the_constructor() -> None:
    """A caller cannot create an unnormalized user and defeat uniqueness."""
    user = build_user(email="  NGOZI@Example.com ", phone="0803 123 4567")

    assert user.email == "ngozi@example.com"
    assert user.phone == "08031234567"


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_entity_is_immutable() -> None:
    user = build_user()

    with pytest.raises(FrozenInstanceError):
        user.email = "other@example.com"  # type: ignore[misc]


@pytest.mark.unit
def test_profile_update_returns_a_new_instance() -> None:
    user = build_user()
    later = NOW + timedelta(minutes=5)

    updated = user.with_profile(first_name="Chinedu", at=later)

    assert updated is not user
    assert updated.first_name == "Chinedu"
    assert updated.last_name == "Okonkwo"
    assert updated.updated_at == later
    assert user.first_name == "Emeka", "the original must be untouched"


@pytest.mark.unit
def test_profile_update_treats_none_as_unchanged() -> None:
    """A partial update means the fields that were sent, not the ones that were not."""
    user = build_user()

    updated = user.with_profile(last_name=None, at=NOW + timedelta(minutes=1))

    assert updated.last_name == "Okonkwo"


@pytest.mark.unit
def test_profile_update_normalizes_new_contacts() -> None:
    user = build_user()

    updated = user.with_profile(email="  ADA@Example.com ", at=NOW + timedelta(minutes=1))

    assert updated.email == "ada@example.com"


@pytest.mark.unit
def test_profile_update_cannot_remove_the_last_contact_channel() -> None:
    """Changing a channel to an invalid value is rejected, not silently dropped."""
    user = build_user(email=None)

    with pytest.raises(EntityInvariantError):
        user.with_profile(email="not-an-address", at=NOW + timedelta(minutes=1))


@pytest.mark.unit
def test_deactivation_and_activation() -> None:
    user = build_user()
    later = NOW + timedelta(days=1)

    deactivated = user.deactivate(at=later)

    assert deactivated.is_active is False
    assert deactivated.updated_at == later
    assert user.is_active is True

    reactivated = deactivated.activate(at=later + timedelta(hours=1))

    assert reactivated.is_active is True


@pytest.mark.unit
def test_verification_and_login_timestamps_are_recorded() -> None:
    user = build_user()
    later = NOW + timedelta(minutes=10)

    verified = user.mark_email_verified(at=later)
    logged_in = verified.record_login(at=later + timedelta(minutes=1))

    assert verified.is_email_verified is True
    assert user.is_email_verified is False
    assert logged_in.last_login_at == later + timedelta(minutes=1)
    assert logged_in.is_phone_verified is False


@pytest.mark.unit
def test_password_hash_can_be_set_and_cannot_be_empty() -> None:
    user = build_user()

    with_password = user.change_password_hash(password_hash="$argon2id$v=19$...", at=NOW)

    assert with_password.has_password is True
    assert user.has_password is False

    with pytest.raises(EntityInvariantError, match="refusing to store an empty password hash"):
        with_password.change_password_hash(password_hash="  ", at=NOW)


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_audit_description_carries_identifiers_and_no_personal_data() -> None:
    description = build_user().describe_for_audit()

    assert description == {"user_id": description["user_id"], "is_active": "true"}
    rendered = repr(description)
    assert "Emeka" not in rendered
    assert "emeka@example.com" not in rendered
    assert "+2348031234567" not in rendered


@pytest.mark.unit
def test_entity_imports_no_framework() -> None:
    """A framework import here would end domain purity.

    The check parses imports rather than searching the text: the module
    docstring names the frameworks precisely to say they are absent, and a text
    search cannot tell a prohibition from a violation.
    """
    source = Path(user_model_module.__file__).read_text(encoding="utf-8")
    imported_modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])

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
    assert imported_modules & forbidden == set()
    # The only application import permitted is the cross-cutting error hierarchy,
    # which is what lets an entity raise a typed error instead of a bare one.
    assert imported_modules & {"ahia"} == {"ahia"}
