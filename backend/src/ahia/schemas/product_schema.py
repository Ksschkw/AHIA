"""Transport contracts for products.

**Money on the wire.** A price is accepted as a JSON number or as a decimal string, and
it is always returned as a decimal string. The reason is that no client should have to
pass money through a binary float to talk to this API: JavaScript parses every JSON
number into a double, so a client computing with prices it received could produce a
value this server refuses, or worse, one it rounds. A string is exact on both sides.
Accepting a number is a concession to how most clients are written, and it is parsed
through the value's own decimal text rather than its binary value.

The response fields are declared `str`, not `Decimal`, and that is deliberate. Annotating
them `Decimal` reads better and is wrong: FastAPI's encoder turns a Decimal into a JSON
*number*, which is precisely what this contract forbids, and the OpenAPI schema would
advertise a number as well. A declared string cannot be encoded into a float by
accident, and the conversion is explicit and tested.

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
from typing import Annotated, Any, Protocol
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, StringConstraints, field_validator

from ahia.models.entities.price_book import resolve_price
from ahia.models.entities.product_model import (
    MAXIMUM_DESCRIPTION_LENGTH,
    MAXIMUM_IDENTIFIER_LENGTH,
    MAXIMUM_NAME_LENGTH,
    coerce_money,
    coerce_quantity,
)
from ahia.schemas.money_format import money_text, quantity_text

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
    # Optional: an item under a group that carries a price inherits it, which is how a grade is
    # priced once. An item with no price from anywhere is refused by the service, because that is a
    # business rule rather than a shape.
    selling_price: Money | None = None
    wholesale_price: Money | None = None
    pieces_per_pack: int | None = None
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
    wholesale_price: Money | None = None
    pieces_per_pack: int | None = None
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


class ProductForResponse(Protocol):
    """What a product has to look like to be rendered as a response.

    A structural type rather than the entity itself, because the transport layer may not name a
    domain entity - the architecture contract draws that line, and this stays on the right side of
    it without giving up the checking. A `ProductModel` satisfies it by having these members, and
    the type checker proves that at each call site instead of trusting an annotation.

    **Properties, not plain attributes**, and that is not decoration: the entity is a frozen
    dataclass, whose members are read-only, and a protocol that asked for mutable attributes would
    reject it. Asking for what a reader needs - the values - is both more accurate and the only
    version that type-checks."""

    @property
    def id(self) -> UUID: ...

    @property
    def tenant_id(self) -> UUID: ...

    @property
    def name(self) -> str: ...

    @property
    def slug(self) -> str: ...

    @property
    def category_id(self) -> UUID | None: ...

    @property
    def description(self) -> str | None: ...

    @property
    def sku(self) -> str | None: ...

    @property
    def barcode(self) -> str | None: ...

    @property
    def selling_price(self) -> Decimal | None: ...

    @property
    def wholesale_price(self) -> Decimal | None: ...

    @property
    def pieces_per_pack(self) -> int | None: ...

    @property
    def cost_price(self) -> Decimal | None: ...

    @property
    def low_stock_threshold(self) -> Decimal: ...

    @property
    def is_active(self) -> bool: ...

    @property
    def is_published(self) -> bool: ...

    @property
    def public_token(self) -> str | None: ...

    @property
    def created_at(self) -> datetime: ...

    @property
    def updated_at(self) -> datetime: ...

    def is_visible_to_customers(self) -> bool:
        """Whether a customer may see this item."""
        ...


class PriceForResponse(Protocol):
    """What a resolved price has to look like to be rendered.

    Structural for the same reason as `ProductForResponse`: the rule that decides these values lives
    in the entity layer, the service hands the result over, and the transport layer should be able
    to render it without importing the module it came from."""

    @property
    def normal_price(self) -> Decimal | None: ...

    @property
    def wholesale_price(self) -> Decimal | None: ...

    @property
    def pieces_per_pack(self) -> int | None: ...

    @property
    def normal_price_from_group(self) -> bool: ...

    @property
    def wholesale_price_from_group(self) -> bool: ...

    @property
    def wholesale_price_used_the_normal_price(self) -> bool: ...


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
    selling_price: str | None
    effective_normal_price: str | None
    effective_wholesale_price: str | None
    effective_pieces_per_pack: int | None
    normal_price_from_group: bool
    wholesale_price_from_group: bool
    wholesale_price_uses_normal_price: bool
    cost_price: str | None
    low_stock_threshold: str
    is_active: bool
    is_published: bool
    is_visible_to_customers: bool
    public_token: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(
        cls,
        product: ProductForResponse,
        price: PriceForResponse | None = None,
    ) -> ProductResponseSchema:
        """Build the response from the item, and the price that applies to it.

        The resolved price is passed in rather than computed here because resolving it properly
        needs
        the item's **group**, and a schema that reached for the database would be doing the service
        layer's job. When a caller has no group to hand - a unit test, a job - the item speaks for
        itself instead: its own prices, and nothing claimed as inherited, which is true.
        """
        effective = (
            price
            if price is not None
            else resolve_price(
                own_normal_price=product.selling_price,
                own_wholesale_price=product.wholesale_price,
                own_pieces_per_pack=product.pieces_per_pack,
            )
        )
        return cls(
            id=product.id,
            tenant_id=product.tenant_id,
            name=product.name,
            slug=product.slug,
            category_id=product.category_id,
            description=product.description,
            sku=product.sku,
            barcode=product.barcode,
            selling_price=(
                None if product.selling_price is None else money_text(product.selling_price)
            ),
            effective_normal_price=(
                None if effective.normal_price is None else money_text(effective.normal_price)
            ),
            effective_wholesale_price=(
                None if effective.wholesale_price is None else money_text(effective.wholesale_price)
            ),
            effective_pieces_per_pack=effective.pieces_per_pack,
            normal_price_from_group=effective.normal_price_from_group,
            wholesale_price_from_group=effective.wholesale_price_from_group,
            wholesale_price_uses_normal_price=effective.wholesale_price_used_the_normal_price,
            cost_price=(None if product.cost_price is None else money_text(product.cost_price)),
            low_stock_threshold=quantity_text(product.low_stock_threshold),
            is_active=product.is_active,
            is_published=product.is_published,
            is_visible_to_customers=product.is_visible_to_customers(),
            public_token=product.public_token,
            created_at=product.created_at,
            updated_at=product.updated_at,
        )


class ProductCopySchema(BaseModel):
    """Payload to copy multiple products into a destination category."""

    model_config = ConfigDict(extra="forbid")

    product_ids: list[UUID]
    target_category_id: UUID | None = None


class ProductMoveBatchSchema(BaseModel):
    """Payload to move multiple products into a destination category."""

    model_config = ConfigDict(extra="forbid")

    product_ids: list[UUID]
    target_category_id: UUID | None = None
