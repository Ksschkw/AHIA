"""Tests for the customer transport contracts.

The consent field is the part worth its own tests: it is the only boolean in this API
parsed strictly, and `exclude_unset` is what keeps "clear the phone number" different from
"leave it alone".
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ahia.models.entities.customer_model import CustomerModel
from ahia.schemas.customer_schema import (
    CustomerCreateSchema,
    CustomerResponseSchema,
    CustomerUpdateSchema,
)

NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)


def build_customer(**overrides: object) -> CustomerModel:
    parameters: dict[str, object] = {
        "customer_id": uuid4(),
        "tenant_id": uuid4(),
        "name": "Ada Obi",
        "now": NOW,
        "phone": "+2348031234567",
        "email": "ada@example.com",
    }
    parameters.update(overrides)
    return CustomerModel.create(**parameters)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Create contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_name_is_required_and_trimmed() -> None:
    assert CustomerCreateSchema(name="  Ada Obi  ").name == "Ada Obi"
    with pytest.raises(ValidationError):
        CustomerCreateSchema(name="   ")


@pytest.mark.unit
def test_consent_defaults_to_no() -> None:
    """A customer who was not asked has not agreed."""
    assert CustomerCreateSchema(name="Ada Obi").marketing_opt_in is False


@pytest.mark.unit
def test_consent_is_parsed_strictly() -> None:
    """`yes` is not a boolean, and consent is the field where guessing is unwelcome."""
    assert CustomerCreateSchema(name="Ada Obi", marketing_opt_in=True).marketing_opt_in is True
    assert CustomerCreateSchema(name="Ada Obi", marketing_opt_in=False).marketing_opt_in is False

    for not_a_boolean in ("yes", "true", "1", "on"):
        with pytest.raises(ValidationError):
            CustomerCreateSchema(name="Ada Obi", marketing_opt_in=not_a_boolean)


@pytest.mark.unit
def test_a_tenant_cannot_be_sent() -> None:
    with pytest.raises(ValidationError):
        CustomerCreateSchema(name="Ada Obi", tenant_id=str(uuid4()))


@pytest.mark.unit
def test_every_contact_field_is_optional() -> None:
    payload = CustomerCreateSchema(name="Walk-in customer")

    assert payload.phone is None
    assert payload.email is None
    assert payload.address is None
    assert payload.notes is None


@pytest.mark.unit
def test_an_overlong_name_is_refused() -> None:
    with pytest.raises(ValidationError):
        CustomerCreateSchema(name="x" * 201)


# ---------------------------------------------------------------------------
# Update contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_an_update_sends_only_what_changed() -> None:
    assert CustomerUpdateSchema(name="Ada N. Obi").to_entity_changes() == {"name": "Ada N. Obi"}


@pytest.mark.unit
def test_clearing_a_phone_number_is_distinguishable_from_leaving_it_alone() -> None:
    assert CustomerUpdateSchema(phone=None).to_entity_changes() == {"phone": None}
    assert CustomerUpdateSchema().to_entity_changes() == {}


@pytest.mark.unit
def test_the_version_is_not_a_customer_field() -> None:
    """It travels with the request but must never reach the entity as a change."""
    payload = CustomerUpdateSchema(notes="Edited", version=3)

    assert payload.to_entity_changes() == {"notes": "Edited"}
    assert payload.expected_version == 3


@pytest.mark.unit
def test_an_update_without_a_version_says_nothing_about_concurrency() -> None:
    assert CustomerUpdateSchema(notes="Edited").expected_version is None


@pytest.mark.unit
def test_a_version_below_one_is_refused() -> None:
    with pytest.raises(ValidationError):
        CustomerUpdateSchema(version=0)


@pytest.mark.unit
def test_an_update_cannot_send_a_tenant_or_an_identifier() -> None:
    with pytest.raises(ValidationError):
        CustomerUpdateSchema(tenant_id=str(uuid4()))
    with pytest.raises(ValidationError):
        CustomerUpdateSchema(id=str(uuid4()))


@pytest.mark.unit
def test_an_update_consent_flag_is_strict_too() -> None:
    with pytest.raises(ValidationError):
        CustomerUpdateSchema(marketing_opt_in="no")


# ---------------------------------------------------------------------------
# Response contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_response_publishes_the_version_and_the_consent_state() -> None:
    customer = build_customer(marketing_opt_in=True)

    response = CustomerResponseSchema.from_entity(customer)

    assert response.version == 1
    assert response.marketing_opt_in is True
    assert response.is_active is True
    assert response.phone == "+2348031234567"


@pytest.mark.unit
def test_the_response_carries_no_field_the_entity_does_not_have() -> None:
    fields = set(CustomerResponseSchema.model_fields)

    assert fields == {
        "id",
        "tenant_id",
        "name",
        "phone",
        "email",
        "address",
        "notes",
        "marketing_opt_in",
        "is_active",
        "version",
        "created_at",
        "updated_at",
    }
