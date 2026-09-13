"""Tests for the product entity.

This entity is where money lives, so most of these tests are about numbers: a float
price refused rather than rounded, a price with three decimal places refused, a price
of exactly zero allowed. The rest are about the two states a product has and the rules
between them, because a product that is not sold must not stay on a storefront.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.product_model import (
    MAXIMUM_DESCRIPTION_LENGTH,
    MAXIMUM_NAME_LENGTH,
    MAXIMUM_PRICE,
    MAXIMUM_QUANTITY,
    ProductModel,
)

NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)


def build_product(**overrides: object) -> ProductModel:
    parameters: dict[str, object] = {
        "product_id": uuid4(),
        "tenant_id": uuid4(),
        "name": "Coca Cola 50cl",
        "selling_price": Decimal("250.00"),
        "now": NOW,
        "description": "Chilled bottle",
        "sku": "CC-50",
        "barcode": "5449000000996",
        "cost_price": Decimal("180.00"),
        "low_stock_threshold": Decimal("12.000"),
    }
    parameters.update(overrides)
    return ProductModel.create(**parameters)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_new_product_is_active_and_unpublished() -> None:
    """A business prepares a product before anybody sees it."""
    product = build_product()

    assert product.is_active is True
    assert product.is_published is False
    assert product.public_token is None
    assert product.is_visible_to_customers() is False


@pytest.mark.unit
def test_the_slug_is_derived_from_the_name() -> None:
    assert build_product(name="Coca Cola 50cl").slug == "coca-cola-50cl"


@pytest.mark.unit
@pytest.mark.parametrize("name", ["", "   ", "\t"])
def test_an_empty_name_is_rejected(name: str) -> None:
    with pytest.raises(EntityInvariantError, match="name is empty"):
        build_product(name=name)


@pytest.mark.unit
def test_a_name_of_only_punctuation_is_rejected() -> None:
    with pytest.raises(EntityInvariantError, match="invalid slug"):
        build_product(name="!!!")


@pytest.mark.unit
def test_an_overlong_name_is_rejected() -> None:
    with pytest.raises(EntityInvariantError, match="exceeds"):
        build_product(name="x" * (MAXIMUM_NAME_LENGTH + 1))


@pytest.mark.unit
def test_an_overlong_description_is_rejected() -> None:
    with pytest.raises(EntityInvariantError, match="description exceeds"):
        build_product(description="x" * (MAXIMUM_DESCRIPTION_LENGTH + 1))


@pytest.mark.unit
def test_an_empty_description_becomes_none() -> None:
    assert build_product(description="   ").description is None


@pytest.mark.unit
def test_an_uncategorised_product_is_legitimate() -> None:
    assert build_product(category_id=None).category_id is None


@pytest.mark.unit
def test_a_category_identifier_is_kept_as_given() -> None:
    category_id = uuid4()
    assert build_product(category_id=category_id).category_id == category_id


# ---------------------------------------------------------------------------
# Money: the reason this entity is strict
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_float_price_is_refused_rather_than_rounded() -> None:
    """0.1 + 0.2 != 0.3, and a shop that loses a kobo per sale cannot balance its books."""
    with pytest.raises(EntityInvariantError, match="float"):
        build_product(selling_price=250.1)  # type: ignore[arg-type]


@pytest.mark.unit
def test_a_float_cost_is_refused_too() -> None:
    with pytest.raises(EntityInvariantError, match="float"):
        build_product(cost_price=180.5)  # type: ignore[arg-type]


@pytest.mark.unit
def test_a_float_threshold_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="float"):
        build_product(low_stock_threshold=12.5)  # type: ignore[arg-type]


@pytest.mark.unit
def test_a_non_numeric_price_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="must be a Decimal"):
        build_product(selling_price="250.00")  # type: ignore[arg-type]


@pytest.mark.unit
def test_a_price_with_three_decimal_places_is_refused() -> None:
    """The column cannot hold it, and rounding would change what somebody typed."""
    with pytest.raises(EntityInvariantError, match="more than two decimal places"):
        build_product(selling_price=Decimal("250.005"))


@pytest.mark.unit
def test_a_quantity_with_four_decimal_places_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="more than three decimal places"):
        build_product(low_stock_threshold=Decimal("12.0005"))


@pytest.mark.unit
@pytest.mark.parametrize(
    "price",
    [Decimal("0.00"), Decimal("0.01"), Decimal("250.00"), Decimal("250.5"), Decimal("250")],
)
def test_acceptable_prices_are_accepted(price: Decimal) -> None:
    assert build_product(selling_price=price).selling_price == price


@pytest.mark.unit
def test_a_price_of_zero_is_allowed_because_shops_give_things_away() -> None:
    product = build_product(selling_price=Decimal("0.00"))

    assert product.selling_price == Decimal("0.00")


@pytest.mark.unit
def test_a_negative_price_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="below"):
        build_product(selling_price=Decimal("-1.00"))


@pytest.mark.unit
def test_a_negative_cost_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="below"):
        build_product(cost_price=Decimal("-1.00"))


@pytest.mark.unit
def test_an_absurd_price_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="exceeds"):
        build_product(selling_price=MAXIMUM_PRICE + Decimal("1.00"))


@pytest.mark.unit
def test_a_negative_threshold_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="negative"):
        build_product(low_stock_threshold=Decimal("-0.001"))


@pytest.mark.unit
def test_an_absurd_threshold_is_refused() -> None:
    with pytest.raises(EntityInvariantError, match="exceeds"):
        build_product(low_stock_threshold=MAXIMUM_QUANTITY + Decimal("1"))


@pytest.mark.unit
def test_a_cost_above_the_selling_price_is_allowed_and_reported() -> None:
    """Clearing stock at a loss is a decision, not a defect."""
    product = build_product(selling_price=Decimal("100.00"), cost_price=Decimal("150.00"))

    assert product.sells_at_a_loss is True
    assert build_product().sells_at_a_loss is False
    assert build_product(cost_price=None).sells_at_a_loss is False


@pytest.mark.unit
def test_the_stored_price_keeps_its_two_places() -> None:
    """A price read back from the database must compare equal to the one stored."""
    product = build_product(selling_price=Decimal("250.00"))

    assert str(product.selling_price) == "250.00"
    assert product.selling_price == Decimal("250.0")


# ---------------------------------------------------------------------------
# Stock identifiers
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_sku_is_stored_uppercase() -> None:
    """`abc-1` one day and `ABC-1` the next must be one product, not two."""
    assert build_product(sku="abc-1").sku == "ABC-1"


@pytest.mark.unit
def test_a_barcode_keeps_its_case_and_loses_its_spaces() -> None:
    assert build_product(barcode="123 456 789").barcode == "123456789"
    assert build_product(barcode="AbC-9").barcode == "AbC-9"


@pytest.mark.unit
def test_an_identifier_of_only_whitespace_becomes_none() -> None:
    product = build_product(sku="   ", barcode="  ")

    assert product.sku is None
    assert product.barcode is None


@pytest.mark.unit
def test_an_overlong_identifier_is_rejected() -> None:
    with pytest.raises(EntityInvariantError, match="sku exceeds"):
        build_product(sku="X" * 65)


@pytest.mark.unit
def test_a_lowercase_sku_built_directly_is_refused() -> None:
    """The mapper builds the dataclass field by field, so the rule cannot live in the factory."""
    product = build_product()
    with pytest.raises(EntityInvariantError, match="uppercase"):
        ProductModel(
            id=product.id,
            tenant_id=product.tenant_id,
            name=product.name,
            slug=product.slug,
            selling_price=product.selling_price,
            sku="lower-case",
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.unit
def test_an_identifier_containing_a_space_built_directly_is_refused() -> None:
    product = build_product()
    with pytest.raises(EntityInvariantError, match="contains a space"):
        ProductModel(
            id=product.id,
            tenant_id=product.tenant_id,
            name=product.name,
            slug=product.slug,
            selling_price=product.selling_price,
            barcode="123 456",
            created_at=NOW,
            updated_at=NOW,
        )


# ---------------------------------------------------------------------------
# Timestamps and immutability
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("field_name", ["created_at", "updated_at"])
def test_naive_timestamps_are_rejected(field_name: str) -> None:
    product = build_product()
    timestamps: dict[str, datetime] = {"created_at": NOW, "updated_at": NOW}
    timestamps[field_name] = datetime(2026, 9, 13, 9, 30)  # noqa: DTZ001 - under test

    with pytest.raises(EntityInvariantError, match="naive datetime"):
        ProductModel(
            id=product.id,
            tenant_id=product.tenant_id,
            name=product.name,
            slug=product.slug,
            selling_price=product.selling_price,
            created_at=timestamps["created_at"],
            updated_at=timestamps["updated_at"],
        )


@pytest.mark.unit
def test_updated_at_cannot_precede_created_at() -> None:
    product = build_product()

    with pytest.raises(EntityInvariantError, match="earlier than created_at"):
        ProductModel(
            id=product.id,
            tenant_id=product.tenant_id,
            name=product.name,
            slug=product.slug,
            selling_price=product.selling_price,
            created_at=NOW,
            updated_at=NOW - timedelta(seconds=1),
        )


@pytest.mark.unit
def test_the_entity_is_immutable() -> None:
    product = build_product()
    with pytest.raises(FrozenInstanceError):
        product.selling_price = Decimal("1.00")  # type: ignore[misc]


@pytest.mark.unit
def test_the_audit_description_carries_identifiers_and_states_but_no_prices() -> None:
    product = build_product(description="Bought from Musa on credit")

    description = product.describe_for_audit()

    assert set(description) == {
        "product_id",
        "tenant_id",
        "product_slug",
        "is_active",
        "is_published",
    }
    assert "250" not in repr(description)
    assert "Musa" not in repr(description)


# ---------------------------------------------------------------------------
# Editing transitions
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_renaming_leaves_the_public_slug_alone() -> None:
    product = build_product(name="Coca Cola 50cl")
    renamed = product.renamed(name="Coke 50cl", at=LATER)

    assert renamed.name == "Coke 50cl"
    assert renamed.slug == "coca-cola-50cl"
    assert renamed.updated_at == LATER


@pytest.mark.unit
def test_describing_can_set_and_clear() -> None:
    product = build_product(description="Chilled bottle")
    described = product.described(description="Served cold", at=LATER)
    cleared = described.described(description=None, at=LATER)

    assert described.description == "Served cold"
    assert cleared.description is None
    assert product.description == "Chilled bottle"


@pytest.mark.unit
def test_categorising_can_assign_and_remove() -> None:
    product = build_product(category_id=None)
    category_id = uuid4()

    assigned = product.categorised(category_id=category_id, at=LATER)
    removed = assigned.categorised(category_id=None, at=LATER)

    assert assigned.category_id == category_id
    assert removed.category_id is None


@pytest.mark.unit
def test_identifiers_are_set_together_so_clearing_one_is_explicit() -> None:
    product = build_product(sku="CC-50", barcode="5449000000996")

    changed = product.identified(sku=None, barcode="5449000000996", at=LATER)

    assert changed.sku is None
    assert changed.barcode == "5449000000996"


@pytest.mark.unit
def test_repricing_sets_both_prices() -> None:
    product = build_product()
    repriced = product.repriced(selling_price=Decimal("275.00"), cost_price=None, at=LATER)

    assert repriced.selling_price == Decimal("275.00")
    assert repriced.cost_price is None
    assert repriced.updated_at == LATER


@pytest.mark.unit
def test_rethresholding_changes_only_the_threshold() -> None:
    product = build_product(low_stock_threshold=Decimal("12.000"))
    rethresholded = product.rethresholded(low_stock_threshold=Decimal("6.000"), at=LATER)

    assert rethresholded.low_stock_threshold == Decimal("6.000")
    assert rethresholded.selling_price == product.selling_price


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_publishing_makes_the_product_visible_and_records_its_token() -> None:
    published = build_product().publish(public_token="tok_abc", at=LATER)

    assert published.is_published is True
    assert published.public_token == "tok_abc"
    assert published.is_visible_to_customers() is True


@pytest.mark.unit
def test_publishing_twice_keeps_the_link_that_was_already_shared() -> None:
    published = build_product().publish(public_token="tok_abc", at=LATER)
    again = published.publish(public_token="tok_different", at=LATER)

    assert again.public_token == "tok_abc"
    assert again.updated_at == published.updated_at


@pytest.mark.unit
def test_republishing_a_withdrawn_product_keeps_its_address() -> None:
    """A link already printed on a QR code must not stop working because of a pause."""
    published = build_product().publish(public_token="tok_abc", at=LATER)
    hidden = published.unpublish(at=LATER)

    republished = hidden.publish(public_token="tok_brand_new", at=LATER)

    assert republished.public_token == "tok_abc"
    assert republished.is_published is True


@pytest.mark.unit
def test_an_inactive_product_cannot_be_published() -> None:
    inactive = build_product().deactivate(at=LATER)

    with pytest.raises(EntityInvariantError, match="not active"):
        inactive.publish(public_token="tok_abc", at=LATER)


@pytest.mark.unit
def test_unpublishing_keeps_the_token_for_a_later_republish() -> None:
    published = build_product().publish(public_token="tok_abc", at=LATER)
    hidden = published.unpublish(at=LATER)

    assert hidden.is_published is False
    assert hidden.public_token == "tok_abc"
    assert hidden.unpublish(at=LATER) == hidden, "unpublishing twice changes nothing"


@pytest.mark.unit
def test_deactivating_also_unpublishes() -> None:
    """A product that is no longer sold must not stay on the storefront."""
    published = build_product().publish(public_token="tok_abc", at=LATER)
    retired = published.deactivate(at=LATER)

    assert retired.is_active is False
    assert retired.is_published is False
    assert retired.is_visible_to_customers() is False


@pytest.mark.unit
def test_deactivating_twice_changes_nothing() -> None:
    retired = build_product().deactivate(at=LATER)

    assert retired.deactivate(at=LATER) == retired


@pytest.mark.unit
def test_reactivating_returns_the_product_without_publishing_it() -> None:
    """Coming back is a decision; being visible again is a separate one."""
    retired = build_product().deactivate(at=LATER)
    revived = retired.activate(at=LATER)

    assert revived.is_active is True
    assert revived.is_published is False


@pytest.mark.unit
def test_a_published_product_built_directly_must_carry_a_token() -> None:
    product = build_product()

    with pytest.raises(EntityInvariantError, match="must carry a public token"):
        ProductModel(
            id=product.id,
            tenant_id=product.tenant_id,
            name=product.name,
            slug=product.slug,
            selling_price=product.selling_price,
            is_published=True,
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.unit
def test_a_published_product_built_directly_must_be_active() -> None:
    product = build_product()

    with pytest.raises(EntityInvariantError, match="cannot be published"):
        ProductModel(
            id=product.id,
            tenant_id=product.tenant_id,
            name=product.name,
            slug=product.slug,
            selling_price=product.selling_price,
            is_active=False,
            is_published=True,
            public_token="tok_abc",
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.unit
def test_a_blank_public_token_built_directly_is_refused() -> None:
    product = build_product()

    with pytest.raises(EntityInvariantError, match="public_token is empty"):
        ProductModel(
            id=product.id,
            tenant_id=product.tenant_id,
            name=product.name,
            slug=product.slug,
            selling_price=product.selling_price,
            public_token="   ",
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.unit
def test_transitions_never_lose_the_tenant() -> None:
    """Every transition returns the same product; none of them can change its owner."""
    product = build_product()
    tenant_id: UUID = product.tenant_id

    for changed in (
        product.renamed(name="Coke", at=LATER),
        product.described(description=None, at=LATER),
        product.categorised(category_id=uuid4(), at=LATER),
        product.identified(sku=None, barcode=None, at=LATER),
        product.repriced(selling_price=Decimal("1.00"), cost_price=None, at=LATER),
        product.rethresholded(low_stock_threshold=Decimal("1.000"), at=LATER),
        product.publish(public_token="tok", at=LATER),
        product.deactivate(at=LATER),
    ):
        assert changed.tenant_id == tenant_id
        assert changed.id == product.id
