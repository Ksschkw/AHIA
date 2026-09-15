"""Tests for the storefront entity.

The subject is the publication lifecycle, and one property that matters more than the rest: what
a business writes on its public page is not the same as what it knows about its business, so the
entity's audit description carries identifiers and states and none of the text a person typed.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.storefront_model import (
    MAXIMUM_DESCRIPTION_LENGTH,
    MAXIMUM_HEADLINE_LENGTH,
    StorefrontModel,
)

NOW = datetime(2026, 9, 15, 8, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=1)


def build_storefront(**overrides: object) -> StorefrontModel:
    parameters: dict[str, object] = {
        "storefront_id": uuid4(),
        "tenant_id": uuid4(),
        "now": NOW,
        "headline": "Rice, beans and cooking gas",
        "description": "We deliver in Ikeja on Saturdays.",
        "contact_phone": "08031234567",
    }
    parameters.update(overrides)
    return StorefrontModel.open_shop(**parameters)  # type: ignore[arg-type]


@pytest.mark.unit
def test_a_new_shop_is_closed() -> None:
    """A shop that appears the moment a business registers is one nobody decided to open."""
    storefront = build_storefront()

    assert storefront.is_open() is False
    assert storefront.published_at is None
    assert storefront.unpublished_at is None


@pytest.mark.unit
def test_publishing_records_when_it_opened() -> None:
    storefront = build_storefront()

    published = storefront.published(at=NOW)

    assert published.is_open() is True
    assert published.published_at == NOW
    assert published.updated_at == NOW
    assert storefront.is_open() is False, "the original is unchanged"


@pytest.mark.unit
def test_publishing_again_keeps_the_moment_it_first_opened() -> None:
    """A later edit is not the event that brought the first customer."""
    opened = build_storefront().published(at=NOW)

    again = opened.published(at=LATER)

    assert again.published_at == NOW
    assert again.updated_at == LATER


@pytest.mark.unit
def test_unpublishing_keeps_the_address_and_the_history() -> None:
    opened = build_storefront().published(at=NOW)

    closed = opened.unpublished(at=LATER)

    assert closed.is_open() is False
    assert closed.published_at == NOW, "it was open, and that stays true"
    assert closed.unpublished_at == LATER


@pytest.mark.unit
def test_unpublishing_a_closed_shop_changes_nothing() -> None:
    storefront = build_storefront()

    assert storefront.unpublished(at=LATER) is storefront


@pytest.mark.unit
def test_reopening_clears_the_withdrawal() -> None:
    closed = build_storefront().published(at=NOW).unpublished(at=LATER)

    reopened = closed.published(at=LATER)

    assert reopened.is_open() is True
    assert reopened.published_at == NOW
    assert reopened.unpublished_at is None


@pytest.mark.unit
def test_publishing_keeps_what_it_was_not_given() -> None:
    """A caller that says nothing about the headline is not asking for it to be cleared."""
    opened = build_storefront().published(at=NOW)

    again = opened.published(at=LATER, description="Now open on Sundays too.")

    assert again.headline == "Rice, beans and cooking gas"
    assert again.description == "Now open on Sundays too."


@pytest.mark.unit
def test_a_headline_longer_than_the_bound_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="headline exceeds"):
        build_storefront(headline="x" * (MAXIMUM_HEADLINE_LENGTH + 1))


@pytest.mark.unit
def test_an_empty_description_is_stored_as_absent() -> None:
    assert build_storefront(description="   ").description is None
    assert build_storefront(headline="").headline is None


@pytest.mark.unit
def test_a_description_longer_than_the_bound_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="description exceeds"):
        build_storefront(description="x" * (MAXIMUM_DESCRIPTION_LENGTH + 1))


@pytest.mark.unit
def test_a_contact_number_that_could_not_be_dialled_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="not a plausible phone number"):
        build_storefront(contact_phone="call the shop")


@pytest.mark.unit
def test_a_state_that_contradicts_itself_is_refused() -> None:
    storefront = build_storefront()

    with pytest.raises(EntityInvariantError, match="must record when it was published"):
        StorefrontModel(
            id=storefront.id,
            tenant_id=storefront.tenant_id,
            is_published=True,
            created_at=NOW,
            updated_at=NOW,
        )

    with pytest.raises(EntityInvariantError, match="must record when it was withdrawn"):
        StorefrontModel(
            id=storefront.id,
            tenant_id=storefront.tenant_id,
            is_published=False,
            created_at=NOW,
            updated_at=NOW,
            published_at=NOW,
        )


@pytest.mark.unit
def test_a_naive_timestamp_is_refused() -> None:
    naive = datetime(2026, 9, 15, 8, 0)  # noqa: DTZ001 - the value under test

    with pytest.raises(EntityInvariantError, match="naive datetime"):
        build_storefront(now=naive)


@pytest.mark.unit
def test_the_audit_description_carries_no_text_a_person_typed() -> None:
    storefront = build_storefront(
        headline="Call Musa on 08031234567",
        contact_phone="08031234567",
        description="Ask for Alhaji",
    ).published(at=NOW)

    described = storefront.describe_for_audit()

    assert described["is_published"] == "true"
    assert described["has_contact_phone"] == "true"
    assert "Musa" not in str(described)
    assert "Alhaji" not in str(described)
    assert "08031234567" not in str(described)


@pytest.mark.unit
def test_a_storefront_is_immutable() -> None:
    storefront = build_storefront()

    with pytest.raises(FrozenInstanceError):
        storefront.is_published = True  # type: ignore[misc]
