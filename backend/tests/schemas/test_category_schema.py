"""Tests for the category transport contracts.

The schema is the allowlist between the network and the domain. For categories the
interesting part is what it refuses: a slug is not a field a client may send, because
the domain derives it, and "I did not send a description" has to stay distinguishable
from "clear the description".
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.category_model import (
    MAXIMUM_DESCRIPTION_LENGTH,
    MAXIMUM_NAME_LENGTH,
    CategoryModel,
)
from ahia.schemas.category_schema import (
    CategoryCreateSchema,
    CategoryResponseSchema,
    CategoryUpdateSchema,
)

NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)


def build_category(**overrides: object) -> CategoryModel:
    parameters: dict[str, object] = {
        "category_id": uuid4(),
        "tenant_id": uuid4(),
        "name": "Drinks",
        "now": NOW,
        "description": "Everything cold",
    }
    parameters.update(overrides)
    return CategoryModel.create(**parameters)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Create contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_name_is_required() -> None:
    with pytest.raises(ValidationError):
        CategoryCreateSchema()


@pytest.mark.unit
def test_a_name_is_trimmed_at_the_edge() -> None:
    assert CategoryCreateSchema(name="  Drinks  ").name == "Drinks"


@pytest.mark.unit
@pytest.mark.parametrize("name", ["", "   ", "\t"])
def test_an_empty_name_is_refused(name: str) -> None:
    with pytest.raises(ValidationError):
        CategoryCreateSchema(name=name)


@pytest.mark.unit
def test_an_overlong_name_is_refused() -> None:
    with pytest.raises(ValidationError):
        CategoryCreateSchema(name="x" * (MAXIMUM_NAME_LENGTH + 1))


@pytest.mark.unit
def test_an_overlong_description_is_refused() -> None:
    with pytest.raises(ValidationError):
        CategoryCreateSchema(name="Drinks", description="x" * (MAXIMUM_DESCRIPTION_LENGTH + 1))


@pytest.mark.unit
def test_a_description_is_optional() -> None:
    assert CategoryCreateSchema(name="Drinks").description is None


@pytest.mark.unit
def test_a_slug_cannot_be_sent() -> None:
    """The domain derives it, so accepting one would allow two disagreeing values."""
    with pytest.raises(ValidationError) as captured:
        CategoryCreateSchema(name="Drinks", slug="drinks")

    assert "slug" in str(captured.value)


@pytest.mark.unit
def test_an_unknown_field_is_refused_rather_than_ignored() -> None:
    with pytest.raises(ValidationError):
        CategoryCreateSchema(name="Drinks", tenant_id=str(uuid4()))


@pytest.mark.unit
def test_a_name_of_only_punctuation_passes_the_edge_and_is_refused_by_the_domain() -> None:
    """The edge checks shape, the domain checks meaning.

    A name such as "!!!" is a well-formed string and a category with no usable slug.
    Rejecting it here would mean reimplementing slug normalisation at the edge, and
    the two implementations would eventually disagree.
    """
    payload = CategoryCreateSchema(name="!!!")

    assert payload.name == "!!!"
    with pytest.raises(EntityInvariantError, match="invalid slug"):
        build_category(name=payload.name)


# ---------------------------------------------------------------------------
# Update contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_an_omitted_field_is_not_in_the_changes() -> None:
    assert CategoryUpdateSchema().to_entity_changes() == {}


@pytest.mark.unit
def test_only_the_fields_actually_sent_appear_in_the_changes() -> None:
    assert CategoryUpdateSchema(name="Cold Drinks").to_entity_changes() == {"name": "Cold Drinks"}


@pytest.mark.unit
def test_clearing_a_description_is_distinguishable_from_leaving_it_alone() -> None:
    """The difference the whole partial-update contract rests on."""
    clearing = CategoryUpdateSchema(description=None).to_entity_changes()

    assert clearing == {"description": None}
    assert "description" in clearing
    assert CategoryUpdateSchema().to_entity_changes() == {}


@pytest.mark.unit
def test_an_update_cannot_send_a_slug() -> None:
    with pytest.raises(ValidationError):
        CategoryUpdateSchema(slug="cold-drinks")


@pytest.mark.unit
def test_an_update_cannot_send_an_empty_name() -> None:
    with pytest.raises(ValidationError):
        CategoryUpdateSchema(name="")


# ---------------------------------------------------------------------------
# Response contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_response_publishes_the_derived_slug() -> None:
    category = build_category(name="Cold Drinks")

    response = CategoryResponseSchema.from_entity(category)

    assert response.slug == "cold-drinks"
    assert response.name == "Cold Drinks"
    assert response.tenant_id == category.tenant_id


@pytest.mark.unit
def test_the_response_carries_no_field_the_entity_does_not_have() -> None:
    """A response schema may not invent state, or a client will depend on a guess.

    The three prices are the exception that proves the rule: they are not invented, they are the
    entity's own fields - the price everything under this group uses, and how many pieces are in a
    pack. A group that could not report them would be a group a price grid could not draw.
    """
    fields = set(CategoryResponseSchema.model_fields)

    assert fields == {
        "id",
        "tenant_id",
        "name",
        "slug",
        "description",
        "parent_id",
        "default_normal_price",
        "default_wholesale_price",
        "default_pieces_per_pack",
        "created_at",
        "updated_at",
    }
