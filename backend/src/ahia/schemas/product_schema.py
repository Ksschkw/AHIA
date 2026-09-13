"""Transport contracts for products.

**Money on the wire.** A price is accepted as a JSON number or as a decimal string, and
it is always returned as a decimal string. The reason is that no client should have to
pass money through a binary float to talk to this API: JavaScript parses every JSON
number into a double, so a client computing with prices it received could produce a
value this server refuses, or worse, one it rounds. A string is exact on both sides.
Accepting a number is a concession to how most clients are written, and it is parsed
through the value's own decimal text rather than its binary value.

**What a client may not send.** The slug (derived from the name), the tenant (from the
authorized context), the public token (issued when a product is published), and the two
lifecycle booleans: publishing and deactivating are explicit operations, because a
product that vanishes from a storefront should not be a side effect of a profile edit.
`extra="forbid"` turns each of those into a 422 rather than a field that is quietly
ignored.

**Cost price is in the response.** It is the business's own record of what it paid, and
an edit form that cannot show it would ask an owner to change a number they cannot see.
A business that wants margin hidden from a salesperson should not give that person
`products.read` on management routes; that is a permission decision rather than a field
that silently disappears from a contract.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, StringConstraints, field_validator

from ahia.models.entities.product_model import (
    MAXIMUM_DESCRIPTION_LENGTH,
    MAXIMUM_IDENTIFIER_LENGTH,
    MAXIMUM_NAME_LENGTH,
    ProductModel,
    coerce_money,
    coerce_quantity,
)

ProductName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAXIMUM_NAME_LENGTH),
]
ProductDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=MAXIMUM_DESCRIPTION_LENGTH),
]
StockIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAXIMUM_IDENTIFIER_LENGTH),
]


def _parse_money(value: Any) -> Decimal:
    """Parse a price from the wire, keeping the failure a 422 rather than a 500."""
    return coerce_money(value, field_name="price")


def _parse_quantity(value: Any) -> Decimal:
    """Parse a quantity from the wire."""
    return coerce_quantity(value, field_name="quantity")


#: A price: at most two decimal places, never negative. Declared as a Decimal so the
#: response carries an exact value, and parsed by the entity's own rules so the edge
#: and the domain cannot disagree about what a price is.
Money = Annotated[Decimal, BeforeValidator(_parse_money)]

#: A stock quantity: at most three decimal places, because stock is counted in kilos
#: and litres as well as in units.
Quantity = Annotated[Decimal, BeforeValidator(_parse_quantity)]


class ProductCreateSchema(BaseModel):
    """A product a business is adding to its catalogue."""

    model_config = ConfigDict(extra="forbid")

    name: ProductName
    selling_price: Money
    category_id: UUID | None = None
    description: ProductDescription | None = None
    sku: StockIdentifier | None = None
    barcode: StockIdentifier | None = None
    cost_price: Money | None = None
    low_stock_threshold: Quantity | None = None

    @field_validator("sku", "barcode")
    @classmethod
    def _reject_internal_whitespace(cls, value: str | None) -> str | None:
        """A space inside a stock code is a typo, and it would defeat the uniqueness index."""
        if value is not None and " " in value:
            raise ValueError("a stock identifier may not contain a space")
        return value


class ProductUpdateSchema(BaseModel):
    """A partial edit of a product.

    Every field is optional, and `exclude_unset` preserves the difference between "not
    sent" and "sent as null": clearing a description, a category, a SKU or a cost is a
    real operation, and leaving one alone is a different request. The two lifecycle
    booleans are absent - publication and deactivation have their own operations.
    """

    model_config = ConfigDict(extra="forbid")

    name: ProductName | None = None
    category_id: UUID | None = None
    description: ProductDescription | None = None
    sku: StockIdentifier | None = None
    barcode: StockIdentifier | None = None
    selling_price: Money | None = None
    cost_price: Money | None = None
    low_stock_threshold: Quantity | None = None

    @field_validator("sku", "barcode")
    @classmethod
    def _reject_internal_whitespace(cls, value: str | None) -> str | None:
        if value is not None and " " in value:
            raise ValueError("a stock identifier may not contain a space")
        return value

    def to_entity_changes(self) -> dict[str, Any]:
        """Return only the fields the caller actually sent."""
        return self.model_dump(exclude_unset=True)


class ProductResponseSchema(BaseModel):
    """One product, as the business sees it.

    Prices are Decimal, which this API serialises as a JSON string: a client receives
    `"250.00"` and never a binary approximation of it.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    name: str
    slug: str
    category_id: UUID | None
    description: str | None
    sku: str | None
    barcode: str | None
    selling_price: Decimal
    cost_price: Decimal | None
    low_stock_threshold: Decimal
    is_active: bool
    is_published: bool
    is_visible_to_customers: bool
    public_token: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, product: ProductModel) -> ProductResponseSchema:
        return cls(
            id=product.id,
            tenant_id=product.tenant_id,
            name=product.name,
            slug=product.slug,
            category_id=product.category_id,
            description=product.description,
            sku=product.sku,
            barcode=product.barcode,
            selling_price=product.selling_price,
            cost_price=product.cost_price,
            low_stock_threshold=product.low_stock_threshold,
            is_active=product.is_active,
            is_published=product.is_published,
            is_visible_to_customers=product.is_visible_to_customers(),
            public_token=product.public_token,
            created_at=product.created_at,
            updated_at=product.updated_at,
        )
