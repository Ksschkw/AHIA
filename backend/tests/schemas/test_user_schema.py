"""Tests for the user transport contracts.

The schema is the allowlist that stands between the network and the domain, so
these tests are about what it accepts, what it refuses, and what it can never
publish.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ahia.models.entities.user_model import UserModel
from ahia.schemas.user_schema import (
    UserProfileUpdateSchema,
    UserResponseSchema,
    UserSummarySchema,
    is_credential_shaped_field_name,
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
# Update contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_full_update_parses() -> None:
    schema = UserProfileUpdateSchema(
        first_name="Ngozi",
        last_name="Uzoma",
        email="Ngozi@Example.com",
        phone="+234 803 123 4567",
    )

    assert schema.first_name == "Ngozi"
    assert schema.email == "ngozi@example.com", "the wire normalizes case for comparison"
    assert schema.phone == "+234 803 123 4567", "separators survive to the domain"


@pytest.mark.unit
def test_an_empty_update_is_valid() -> None:
    """No fields means no changes, which is a legitimate request."""
    schema = UserProfileUpdateSchema()

    assert schema.to_entity_changes() == {}


@pytest.mark.unit
def test_only_the_supplied_fields_are_reported_as_changes() -> None:
    schema = UserProfileUpdateSchema(first_name="Ngozi")

    assert schema.to_entity_changes() == {"first_name": "Ngozi"}


@pytest.mark.unit
def test_an_explicit_null_is_reported_as_a_change() -> None:
    """Omitted and explicitly null are different requests, and the service needs both."""
    schema = UserProfileUpdateSchema(last_name=None)

    assert schema.to_entity_changes() == {"last_name": None}


@pytest.mark.unit
def test_an_unknown_field_is_rejected_rather_than_ignored() -> None:
    """A misspelled field must fail loudly, not silently save nothing."""
    with pytest.raises(ValidationError) as captured:
        UserProfileUpdateSchema(firstname="Ngozi")

    assert "firstname" in str(captured.value)


@pytest.mark.unit
def test_a_credential_field_cannot_be_submitted() -> None:
    """The profile endpoint is not a password endpoint, and must never become one."""
    for forbidden_field in ("password", "password_hash", "is_active", "id", "created_at"):
        with pytest.raises(ValidationError):
            UserProfileUpdateSchema(**{forbidden_field: "anything"})


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload",
    [
        {"first_name": ""},
        {"first_name": "   "},
        {"first_name": "A" * 101},
        {"last_name": "B" * 101},
        {"email": "not-an-address"},
        {"email": "missing@tld"},
        {"email": "@example.com"},
        {"email": "a@b.c" * 100},
        {"phone": "12345"},
        {"phone": "abcdefgh"},
        {"phone": "+234-803-123-4567-extension"},
    ],
)
def test_malformed_input_is_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        UserProfileUpdateSchema(**payload)


@pytest.mark.unit
def test_whitespace_is_trimmed_at_the_edge() -> None:
    schema = UserProfileUpdateSchema(first_name="  Ngozi  ")

    assert schema.first_name == "Ngozi"


@pytest.mark.unit
def test_the_wire_accepts_the_same_shapes_the_domain_accepts() -> None:
    """Two validators that disagree produce a 422 for input the domain would take."""
    samples = [
        {"first_name": "Chinedu", "last_name": "Nwachukwu"},
        {"email": "ada@example.com"},
        {"phone": "08031234567"},
        {"phone": "+234 803 123 4567"},
        {"email": "ngozi.uzoma+shop@example.co.uk"},
    ]

    for sample in samples:
        schema = UserProfileUpdateSchema(**sample)
        changes = schema.to_entity_changes()
        # Feeding the parsed values to the entity must not raise.
        build_user(
            first_name=changes.get("first_name") or "Emeka",
            last_name=changes.get("last_name", "Okonkwo"),
            email=changes.get("email", "emeka@example.com"),
            phone=changes.get("phone", "+2348031234567"),
        )


# ---------------------------------------------------------------------------
# Response contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_response_maps_every_exposed_field() -> None:
    user = build_user()

    response = UserResponseSchema.from_entity(user)

    assert response.id == user.id
    assert response.first_name == "Emeka"
    assert response.last_name == "Okonkwo"
    assert response.email == "emeka@example.com"
    assert response.phone == "+2348031234567"
    assert response.is_active is True
    assert response.is_email_verified is False
    assert response.is_phone_verified is False
    assert response.last_login_at is None


@pytest.mark.unit
def test_response_carries_no_credential_shaped_field() -> None:
    """The rule is checked, not remembered."""
    for field_name in UserResponseSchema.model_fields:
        assert not is_credential_shaped_field_name(field_name), (
            f"{field_name} looks like credential material and must not be published"
        )


@pytest.mark.unit
def test_response_serialisation_contains_no_credentials() -> None:
    user = build_user(password_hash="$argon2id$v=19$m=65536,t=3,p=2$c2FsdA$aGFzaA")

    payload = UserResponseSchema.from_entity(user).model_dump(mode="json")
    rendered = str(payload)

    assert "argon2" not in rendered
    assert "password" not in rendered
    assert set(payload) == {
        "id",
        "first_name",
        "last_name",
        "email",
        "phone",
        "is_active",
        "is_email_verified",
        "is_phone_verified",
        "created_at",
        "updated_at",
        "last_login_at",
    }


@pytest.mark.unit
def test_response_rejects_an_unknown_field_being_added_at_the_edge() -> None:
    with pytest.raises(ValidationError):
        UserResponseSchema(
            id=uuid4(),
            first_name="Emeka",
            last_name=None,
            email=None,
            phone="+2348031234567",
            is_active=True,
            is_email_verified=False,
            is_phone_verified=False,
            created_at=NOW,
            updated_at=NOW,
            last_login_at=None,
            internal_note="should not exist",
        )


@pytest.mark.unit
def test_summary_view_exposes_far_less_than_the_self_view() -> None:
    """A colleague needs a name, not a private phone number."""
    user = build_user()

    summary = UserSummarySchema.from_entity(user).model_dump()

    assert set(summary) == {"id", "full_name", "is_active"}
    assert "emeka@example.com" not in str(summary)
    assert "+2348031234567" not in str(summary)


@pytest.mark.unit
def test_response_reflects_verification_and_login_state() -> None:
    user = build_user()
    later = NOW + timedelta(minutes=5)
    verified = user.mark_email_verified(at=later).record_login(at=later)

    response = UserResponseSchema.from_entity(verified)

    assert response.is_email_verified is True
    assert response.last_login_at == later


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "field_name",
    ["password", "password_hash", "refresh_token", "api_key", "secret", "checksum_hash"],
)
def test_credential_shaped_names_are_detected(field_name: str) -> None:
    assert is_credential_shaped_field_name(field_name) is True


@pytest.mark.unit
@pytest.mark.parametrize("field_name", ["email", "phone", "first_name", "created_at", "is_active"])
def test_ordinary_names_are_not_credential_shaped(field_name: str) -> None:
    assert is_credential_shaped_field_name(field_name) is False
