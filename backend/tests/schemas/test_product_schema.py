"""Tests for the product transport contracts.

Money is the part that matters: what the edge accepts, what it refuses, and what a
client is guaranteed to receive back. The rest is the allowlist - a slug, a tenant, a
public token and the two lifecycle booleans are all things a client may not send, and
each of them is a 422 rather than a field that is quietly ignored.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ahia.models.entities.product_model import (
    MAXIMUM_NAME_LENGTH,
    ProductModel,
)
from ahia.schemas.product_schema import (
    ProductCreateSchema,
    ProductResponseSchema,
    ProductUpdateSchema,
)

NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)


def build_product(**overrides: object) -> ProductModel:
    parameters: dict[str, object] = {
        "product_id": uuid4(),
        "tenant_id": uuid4(),
        "name": "Coca Cola 50cl",
        "selling_price": Decimal("250.00"),
        "now": NOW,
        "sku": "CC-50",
        "cost_price": Decimal("180.00"),
    }
    parameters.update(overrides)
    return ProductModel.create(**parameters)  # type: ignore[arg-type]


def validation_errors(payload: dict[str, object]) -> list[str]:
    with pytest.raises(ValidationError) as captured:
        ProductCreateSchema.model_validate(payload)
    return [str(error["msg"]) for error in captured.value.errors()]


# ---------------------------------------------------------------------------
# Money on the way in
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_price_may_be_left_to_the_group() -> None:
    """An item under a priced group needs no price of its own - "all of the 21D are 350".

    The schema accepts the absence; the **service** refuses an item that ends up with no price from
    anywhere, because "no price at all" is a business rule about an item and its group together and
    a shape check cannot see the group. That refusal is tested where it lives, against the real API.
    """
    assert ProductCreateSchema(name="Coca Cola 50cl").selling_price is None


@pytest.mark.unit
def test_a_price_may_arrive_as_a_decimal_string() -> None:
    """The form this API publishes, because a string is exact on both sides."""
    assert ProductCreateSchema(name="Coke", selling_price="250.00").selling_price == Decimal(
        "250.00"
    )


@pytest.mark.unit
def test_a_price_may_arrive_as_a_number() -> None:
    """Most clients send one, and it is parsed through its own decimal text."""
    assert ProductCreateSchema(name="Coke", selling_price=250.1).selling_price == Decimal("250.1")
    assert ProductCreateSchema(name="Coke", selling_price=250).selling_price == Decimal("250")


@pytest.mark.unit
def test_a_float_that_is_not_exactly_a_price_is_refused() -> None:
    """The classic binary artefact: 0.1 + 0.2 reaches the API as 0.30000000000000004."""
    messages = validation_errors({"name": "Coke", "selling_price": 0.1 + 0.2})

    assert any("more than two decimal places" in message for message in messages)


@pytest.mark.unit
def test_a_price_with_three_decimal_places_is_refused() -> None:
    messages = validation_errors({"name": "Coke", "selling_price": "250.005"})

    assert any("more than two decimal places" in message for message in messages)


@pytest.mark.unit
def test_a_negative_price_is_refused() -> None:
    messages = validation_errors({"name": "Coke", "selling_price": "-1.00"})

    assert any("below" in message for message in messages)


@pytest.mark.unit
def test_a_price_that_is_not_a_number_is_refused() -> None:
    messages = validation_errors({"name": "Coke", "selling_price": "two hundred"})

    assert any("is not a number" in message for message in messages)


@pytest.mark.unit
def test_a_boolean_is_not_a_price() -> None:
    """`True` is an int in Python, and silently becoming 1.00 would be a surprise."""
    messages = validation_errors({"name": "Coke", "selling_price": True})

    assert any("must be a number" in message for message in messages)


@pytest.mark.unit
def test_a_negative_infinity_is_not_a_price() -> None:
    messages = validation_errors({"name": "Coke", "selling_price": float("-inf")})

    assert any("finite" in message for message in messages)


@pytest.mark.unit
def test_a_price_of_zero_is_allowed() -> None:
    assert ProductCreateSchema(name="Coke", selling_price="0.00").selling_price == Decimal("0.00")


# ---------------------------------------------------------------------------
# The rest of the create contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_name_is_trimmed_and_required() -> None:
    assert ProductCreateSchema(name="  Coke  ", selling_price="1.00").name == "Coke"
    with pytest.raises(ValidationError):
        ProductCreateSchema(name="   ", selling_price="1.00")


@pytest.mark.unit
def test_an_overlong_name_is_refused() -> None:
    with pytest.raises(ValidationError):
        ProductCreateSchema(name="x" * (MAXIMUM_NAME_LENGTH + 1), selling_price="1.00")


@pytest.mark.unit
def test_a_cost_is_optional() -> None:
    assert ProductCreateSchema(name="Coke", selling_price="1.00").cost_price is None


@pytest.mark.unit
def test_a_quantity_may_carry_three_decimal_places() -> None:
    """Stock is counted in kilos as well as in units."""
    payload = ProductCreateSchema(name="Rice", selling_price="1.00", low_stock_threshold="2.500")

    assert payload.low_stock_threshold == Decimal("2.500")


@pytest.mark.unit
def test_a_quantity_with_four_decimal_places_is_refused() -> None:
    messages = validation_errors(
        {"name": "Rice", "selling_price": "1.00", "low_stock_threshold": "2.5001"}
    )

    assert any("more than three decimal places" in message for message in messages)


@pytest.mark.unit
def test_a_negative_quantity_is_refused() -> None:
    messages = validation_errors(
        {"name": "Rice", "selling_price": "1.00", "low_stock_threshold": "-1"}
    )

    assert any("negative" in message for message in messages)


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload",
    [
        {"name": "Coke", "selling_price": "1.00", "slug": "coke"},
        {"name": "Coke", "selling_price": "1.00", "tenant_id": str(uuid4())},
        {"name": "Coke", "selling_price": "1.00", "public_token": "tok"},
        {"name": "Coke", "selling_price": "1.00", "is_published": True},
        {"name": "Coke", "selling_price": "1.00", "is_active": True},
    ],
)
def test_a_field_a_client_may_not_set_is_refused(payload: dict[str, object]) -> None:
    """The slug is derived, the tenant comes from the context, and the lifecycle is
    an explicit operation rather than a field on a profile edit."""
    with pytest.raises(ValidationError):
        ProductCreateSchema.model_validate(payload)


@pytest.mark.unit
@pytest.mark.parametrize("field_name", ["sku", "barcode"])
def test_a_stock_identifier_containing_a_space_is_refused(field_name: str) -> None:
    """A space inside a stock code is a typo, and it would defeat the uniqueness index."""
    with pytest.raises(ValidationError):
        ProductCreateSchema.model_validate(
            {"name": "Coke", "selling_price": "1.00", field_name: "CC 50"}
        )


@pytest.mark.unit
def test_an_overlong_identifier_is_refused() -> None:
    with pytest.raises(ValidationError):
        ProductCreateSchema(name="Coke", selling_price="1.00", sku="X" * 65)


@pytest.mark.unit
def test_a_blank_identifier_is_refused() -> None:
    with pytest.raises(ValidationError):
        ProductCreateSchema(name="Coke", selling_price="1.00", barcode="   ")


# ---------------------------------------------------------------------------
# The update contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_an_update_sends_only_what_changed() -> None:
    assert ProductUpdateSchema(name="Coke 50cl").to_entity_changes() == {"name": "Coke 50cl"}


@pytest.mark.unit
def test_clearing_a_cost_is_distinguishable_from_leaving_it_alone() -> None:
    assert ProductUpdateSchema(cost_price=None).to_entity_changes() == {"cost_price": None}
    assert ProductUpdateSchema().to_entity_changes() == {}


@pytest.mark.unit
@pytest.mark.parametrize("field_name", ["category_id", "description", "sku", "barcode"])
def test_every_clearable_field_can_be_cleared(field_name: str) -> None:
    assert ProductUpdateSchema.model_validate({field_name: None}).to_entity_changes() == {
        field_name: None
    }


@pytest.mark.unit
def test_an_update_cannot_change_the_lifecycle() -> None:
    with pytest.raises(ValidationError):
        ProductUpdateSchema.model_validate({"is_published": True})
    with pytest.raises(ValidationError):
        ProductUpdateSchema.model_validate({"is_active": False})


@pytest.mark.unit
def test_an_update_cannot_change_the_slug_or_the_tenant() -> None:
    with pytest.raises(ValidationError):
        ProductUpdateSchema.model_validate({"slug": "coke"})
    with pytest.raises(ValidationError):
        ProductUpdateSchema.model_validate({"tenant_id": str(uuid4())})


@pytest.mark.unit
def test_an_update_price_is_validated_the_same_way() -> None:
    with pytest.raises(ValidationError):
        ProductUpdateSchema.model_validate({"selling_price": "1.005"})


# ---------------------------------------------------------------------------
# The response contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_money_leaves_as_a_decimal_string() -> None:
    """No client ever receives a binary float for a price."""
    rendered = ProductResponseSchema.from_entity(build_product()).model_dump_json()

    assert '"selling_price":"250.00"' in rendered
    assert '"cost_price":"180.00"' in rendered
    assert "250.0," not in rendered


@pytest.mark.unit
def test_the_response_reports_visibility_as_the_product_computes_it() -> None:
    product = build_product()
    published = product.publish(public_token="tok", at=NOW)

    assert ProductResponseSchema.from_entity(product).is_visible_to_customers is False
    assert ProductResponseSchema.from_entity(published).is_visible_to_customers is True
    assert ProductResponseSchema.from_entity(published).public_token == "tok"


@pytest.mark.unit
def test_the_response_carries_no_field_the_entity_does_not_have() -> None:
    fields = set(ProductResponseSchema.model_fields)

    assert fields == {
        "id",
        "tenant_id",
        "name",
        "slug",
        "category_id",
        "description",
        "sku",
        "barcode",
        "selling_price",
        "cost_price",
        "low_stock_threshold",
        "is_active",
        "is_published",
        "is_visible_to_customers",
        "public_token",
        # What applies once the item's group has had its say, and which parts came from the group.
        # The entity does not hold these - they are derived from it and its group - so a screen can
        # mark an exception without doing the arithmetic itself, which is the one place the rule may
        # live.
        "effective_normal_price",
        "effective_wholesale_price",
        "effective_pieces_per_pack",
        "normal_price_from_group",
        "wholesale_price_from_group",
        "wholesale_price_uses_normal_price",
        "created_at",
        "updated_at",
    }


@pytest.mark.unit
def test_a_deactivated_product_reports_itself_as_invisible() -> None:
    retired = build_product().publish(public_token="tok", at=NOW).deactivate(at=NOW)

    response = ProductResponseSchema.from_entity(retired)

    assert response.is_active is False
    assert response.is_published is False
    assert response.is_visible_to_customers is False
