"""Tests for the customer entity and the shared phone rule.

The privacy rules are the subject. A customer record is personal data about somebody who
never signed up for anything, so the entity's job is to keep consent explicit, to keep the
person out of audit descriptions, and to make sure a customer is never removed - only
deactivated, because sales reference them.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.customer_model import (
    MAXIMUM_ADDRESS_LENGTH,
    MAXIMUM_NAME_LENGTH,
    MAXIMUM_NOTES_LENGTH,
    CustomerModel,
)
from ahia.models.entities.phone_number import (
    canonical_phone_number,
    is_plausible_phone_number,
    normalize_phone_number,
)

NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)


def build_customer(**overrides: object) -> CustomerModel:
    parameters: dict[str, object] = {
        "customer_id": uuid4(),
        "tenant_id": uuid4(),
        "name": "Ada Obi",
        "now": NOW,
        "phone": "+2348031234567",
        "email": "ada@example.com",
        "address": "12 Awolowo Road, Ikeja",
        "notes": "Prefers delivery on Saturdays",
    }
    parameters.update(overrides)
    return CustomerModel.create(**parameters)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The shared phone rule
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0803 123 4567", "+2348031234567"),
        ("08031234567", "+2348031234567"),
        ("8031234567", "+2348031234567"),
        ("(0803) 123-4567", "+2348031234567"),
        ("+2348031234567", "+2348031234567"),
        ("+44 8081 2345", "+4480812345"),
        ("  +234 803 123 4567  ", "+2348031234567"),
    ],
)
def test_a_local_number_becomes_one_canonical_international_number(raw: str, expected: str) -> None:
    """A trader types one form and a client sends another; both must be one person."""
    assert canonical_phone_number(raw, default_country_code="+234") == expected


@pytest.mark.unit
def test_a_number_that_states_its_country_is_never_overridden() -> None:
    """Guessing a country for a number that names one would corrupt it, invisibly."""
    assert canonical_phone_number("+14155552671", default_country_code="+234") == "+14155552671"


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        "+2348031234567",  # the way the rest of the world writes it
        "2348031234567",  # the country code typed without a plus
        "002348031234567",  # the international prefix dialled from a landline
        "08031234567",  # the local form, with the trunk zero
        "8031234567",  # the local form without it
        "+234 803 123 4567",  # separated the way a person writes it
        "0803 123 4567",
    ],
)
def test_every_way_a_person_writes_a_number_is_one_number(raw: str) -> None:
    """One trader, one account, however the number is typed.

    The case that matters is the country code without a plus: reading it as a local number gives
    `+2342348031234567`, which is a different account for the same person and is exactly the kind of
    duplication nobody notices until a customer cannot sign in.
    """
    assert canonical_phone_number(raw, default_country_code="+234") == "+2348031234567"


@pytest.mark.unit
def test_a_local_number_beginning_with_the_country_digits_is_not_read_as_international() -> None:
    """The guard on the country-code rule: a local number lacks the length a national one has."""
    assert canonical_phone_number("0234567890", default_country_code="+234") == "+234234567890"


@pytest.mark.unit
def test_an_absent_number_stays_absent() -> None:
    assert canonical_phone_number(None, default_country_code="+234") is None
    assert canonical_phone_number("   ", default_country_code="+234") is None


@pytest.mark.unit
@pytest.mark.parametrize("raw", ["12345", "+1234567890123456", "0803-ABC-4567", "not a number"])
def test_an_implausible_number_is_not_a_phone_number(raw: str) -> None:
    """Short codes and typos are not customer numbers, and storing one matches nobody."""
    assert is_plausible_phone_number(normalize_phone_number(raw) or "") is False


@pytest.mark.unit
def test_normalisation_removes_separators_but_keeps_the_plus() -> None:
    assert normalize_phone_number(" +234 (803) 123-4567 ") == "+2348031234567"


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_new_customer_has_not_consented_to_marketing() -> None:
    """Consent is given, not assumed: typing a name is not agreeing to be messaged."""
    customer = build_customer()

    assert customer.marketing_opt_in is False
    assert customer.is_active is True
    assert customer.version == 1
    assert customer.is_reachable_for_marketing() is False


@pytest.mark.unit
def test_a_name_is_trimmed_and_required() -> None:
    assert build_customer(name="  Ada Obi  ").name == "Ada Obi"
    with pytest.raises(EntityInvariantError, match="name is empty"):
        build_customer(name="   ")


@pytest.mark.unit
def test_an_overlong_name_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="exceeds"):
        build_customer(name="x" * (MAXIMUM_NAME_LENGTH + 1))


@pytest.mark.unit
def test_an_email_is_normalised_to_lowercase() -> None:
    assert build_customer(email="Ada.Obi@Example.COM").email == "ada.obi@example.com"


@pytest.mark.unit
def test_a_malformed_email_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="email is not a valid address"):
        build_customer(email="ada at example")


@pytest.mark.unit
def test_a_malformed_phone_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="phone is not a plausible number"):
        build_customer(phone="12345")


@pytest.mark.unit
def test_a_customer_may_have_no_contact_details_at_all() -> None:
    """A shopkeeper recording someone who buys on credit should not have to invent one."""
    customer = build_customer(phone=None, email=None)

    assert customer.has_a_contact_detail() is False
    assert customer.phone is None
    assert customer.email is None


@pytest.mark.unit
def test_empty_text_becomes_absent() -> None:
    customer = build_customer(address="   ", notes="", phone="  ", email="   ")

    assert customer.address is None
    assert customer.notes is None
    assert customer.phone is None
    assert customer.email is None


@pytest.mark.unit
def test_an_overlong_address_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="address exceeds"):
        build_customer(address="x" * (MAXIMUM_ADDRESS_LENGTH + 1))


@pytest.mark.unit
def test_overlong_notes_are_refused() -> None:
    with pytest.raises(EntityInvariantError, match="notes exceeds"):
        build_customer(notes="x" * (MAXIMUM_NOTES_LENGTH + 1))


@pytest.mark.unit
@pytest.mark.parametrize("field_name", ["created_at", "updated_at"])
def test_naive_timestamps_are_rejected(field_name: str) -> None:
    customer = build_customer()
    timestamps: dict[str, datetime] = {"created_at": NOW, "updated_at": NOW}
    timestamps[field_name] = datetime(2026, 9, 13, 9, 30)  # noqa: DTZ001 - under test

    with pytest.raises(EntityInvariantError, match="naive datetime"):
        CustomerModel(
            id=customer.id,
            tenant_id=customer.tenant_id,
            name=customer.name,
            created_at=timestamps["created_at"],
            updated_at=timestamps["updated_at"],
        )


@pytest.mark.unit
def test_the_entity_is_immutable() -> None:
    customer = build_customer()
    with pytest.raises(FrozenInstanceError):
        customer.name = "Someone Else"  # type: ignore[misc]


@pytest.mark.unit
def test_the_version_only_moves_forward() -> None:
    customer = build_customer()
    with pytest.raises(EntityInvariantError, match="version starts at 1"):
        CustomerModel(
            id=customer.id,
            tenant_id=customer.tenant_id,
            name=customer.name,
            version=0,
            created_at=NOW,
            updated_at=NOW,
        )


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_audit_description_carries_no_personal_data() -> None:
    """The rule that keeps a log line from becoming a place a phone number leaks."""
    customer = build_customer(name="Ada Obi", phone="+2348031234567", email="ada@example.com")

    description = customer.describe_for_audit()
    rendered = repr(description)

    assert set(description) == {
        "customer_id",
        "tenant_id",
        "is_active",
        "has_phone",
        "has_email",
        "marketing_opt_in",
        "version",
    }
    assert "Ada" not in rendered
    assert "+2348031234567" not in rendered
    assert "ada@example.com" not in rendered
    assert "Ikeja" not in rendered


@pytest.mark.unit
def test_a_customer_is_reachable_for_marketing_only_with_consent_and_a_channel() -> None:
    consenting = build_customer(marketing_opt_in=True)
    unknown_contact = build_customer(marketing_opt_in=True, phone=None, email=None)
    deactivated = consenting.deactivated(at=LATER)

    assert consenting.is_reachable_for_marketing() is True
    assert unknown_contact.is_reachable_for_marketing() is False
    assert deactivated.is_reachable_for_marketing() is False


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_every_change_moves_the_version() -> None:
    """A version that did not move would make two offline edits look identical."""
    customer = build_customer()

    for changed in (
        customer.renamed(name="Ada N. Obi", at=LATER),
        customer.contacted(phone="+2348039998888", email=None, at=LATER),
        customer.addressed(address=None, at=LATER),
        customer.noted(notes="Pays on delivery", at=LATER),
        customer.gave_marketing_consent(opt_in=True, at=LATER),
        customer.deactivated(at=LATER),
    ):
        assert changed.version == customer.version + 1
        assert changed.updated_at == LATER


@pytest.mark.unit
def test_contact_details_are_set_together_so_clearing_one_is_explicit() -> None:
    customer = build_customer(phone="+2348031234567", email="ada@example.com")

    changed = customer.contacted(phone=None, email="ada@example.com", at=LATER)

    assert changed.phone is None
    assert changed.email == "ada@example.com"


@pytest.mark.unit
def test_notes_can_be_set_and_cleared() -> None:
    customer = build_customer(notes="Prefers Saturdays")

    noted = customer.noted(notes="Pays on delivery", at=LATER)
    cleared = noted.noted(notes=None, at=LATER)

    assert noted.notes == "Pays on delivery"
    assert cleared.notes is None
    assert customer.notes == "Prefers Saturdays"


@pytest.mark.unit
def test_consent_can_be_withdrawn() -> None:
    consenting = build_customer(marketing_opt_in=True)

    withdrawn = consenting.gave_marketing_consent(opt_in=False, at=LATER)

    assert withdrawn.marketing_opt_in is False
    assert withdrawn.version == consenting.version + 1


@pytest.mark.unit
def test_deactivation_keeps_everything_else() -> None:
    """Sales reference customers, so a customer is withdrawn rather than removed."""
    customer = build_customer()

    deactivated = customer.deactivated(at=LATER)

    assert deactivated.is_active is False
    assert deactivated.name == customer.name
    assert deactivated.phone == customer.phone
    assert deactivated.notes == customer.notes
    assert deactivated.created_at == customer.created_at


@pytest.mark.unit
def test_deactivating_twice_changes_nothing() -> None:
    retired = build_customer().deactivated(at=LATER)

    assert retired.deactivated(at=LATER) == retired


@pytest.mark.unit
def test_reactivating_returns_the_customer_and_moves_the_version() -> None:
    retired = build_customer().deactivated(at=LATER)

    revived = retired.reactivated(at=LATER)

    assert revived.is_active is True
    assert revived.version == retired.version + 1
    assert revived.reactivated(at=LATER) == revived, "activating an active customer changes nothing"


@pytest.mark.unit
def test_transitions_never_lose_the_tenant() -> None:
    customer = build_customer()
    tenant_id: UUID = customer.tenant_id

    for changed in (
        customer.renamed(name="Ada N. Obi", at=LATER),
        customer.contacted(phone=None, email=None, at=LATER),
        customer.addressed(address="New address", at=LATER),
        customer.noted(notes="Anything", at=LATER),
        customer.gave_marketing_consent(opt_in=True, at=LATER),
        customer.deactivated(at=LATER),
    ):
        assert changed.tenant_id == tenant_id
        assert changed.id == customer.id
