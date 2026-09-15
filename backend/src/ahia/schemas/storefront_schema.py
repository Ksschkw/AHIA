"""Transport contracts for the storefront.

**The public contracts carry an allowlist, and the schema is where it is visible.** What a stranger
receives is written down here field by field: the shop's name and what it says about itself, and
for each product its address, its name, its selling price, a description, one picture and whether
it is available at all. There is no field for a cost price, a stock count, an internal identifier
or a publication token, so a future change that wants to expose one has to add it here, in a
contract a reviewer reads, rather than discovering that a business object happened to be returned.

**Money crosses as a decimal string.** `money_text` is the single wire format for money in this
product, and a public page is the last place a client's float arithmetic should be able to
disagree with the ledger.

**The management contract is the business's own view, and it is a different shape on purpose.**
It carries identifiers and the publication timestamps because a worker managing the shop needs
them; the public one carries neither. Two contracts rather than one with fields hidden, because a
single shape that is public in one context and private in another is a shape that leaks the first
time somebody reuses it.

**Neither contract carries a public path.** The address is the tenant's, spelled from the tenant's
slug, and the tenant contract already publishes that slug. A computed path here would be a second
place the address is spelled, and the two would eventually differ.

**Contact details are the business's own choice to publish.** The contact number in the public
contract is the one the business typed for customers. Nothing else about the business - its
address, its contact email, its owner - is in this contract, because a shop needs a way to be
reached and not a profile.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

from ahia.models.entities.storefront_model import (
    MAXIMUM_DESCRIPTION_LENGTH,
    MAXIMUM_HEADLINE_LENGTH,
)
from ahia.schemas.money_format import money_text

StorefrontHeadline = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAXIMUM_HEADLINE_LENGTH)
]
StorefrontDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAXIMUM_DESCRIPTION_LENGTH),
]
StorefrontContactPhone = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=4, max_length=32)
]
#: A public slug, shaped like every other public address in this product.
PublicSlug = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80, pattern=r"^[a-z0-9-]+$"),
]


class StorefrontPublishSchema(BaseModel):
    """What a business says about its shop when it opens it."""

    model_config = ConfigDict(extra="forbid")

    headline: StorefrontHeadline | None = None
    description: StorefrontDescription | None = None
    contact_phone: StorefrontContactPhone | None = None


class StorefrontUpdateSchema(BaseModel):
    """A partial edit of what the shop says. It never changes whether the shop is open."""

    model_config = ConfigDict(extra="forbid")

    headline: StorefrontHeadline | None = None
    description: StorefrontDescription | None = None
    contact_phone: StorefrontContactPhone | None = None

    def to_changes(self) -> dict[str, Any]:
        """Return only the fields the caller actually sent.

        `exclude_unset` preserves the difference between "not sent" and "sent as null": clearing a
        headline is a real operation, and leaving one alone is a different request.
        """
        return self.model_dump(exclude_unset=True)


class StorefrontResponseSchema(BaseModel):
    """The business's own view of its shop."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    is_published: bool
    headline: str | None
    description: str | None
    contact_phone: str | None
    published_at: datetime | None
    unpublished_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, storefront: Any) -> StorefrontResponseSchema:
        return cls(
            id=storefront.id,
            tenant_id=storefront.tenant_id,
            is_published=storefront.is_published,
            headline=storefront.headline,
            description=storefront.description,
            contact_phone=storefront.contact_phone,
            published_at=storefront.published_at,
            unpublished_at=storefront.unpublished_at,
            created_at=storefront.created_at,
            updated_at=storefront.updated_at,
        )


class PublicProductSchema(BaseModel):
    """One product, as a stranger sees it."""

    model_config = ConfigDict(extra="forbid")

    product_slug: str
    name: str
    selling_price: str
    is_available: bool
    description: str | None
    primary_image_url: str | None

    @classmethod
    def from_projection(cls, product: Any) -> PublicProductSchema:
        return cls(
            product_slug=product.product_slug,
            name=product.name,
            selling_price=money_text(Decimal(product.selling_price)),
            is_available=product.is_available,
            description=product.description,
            primary_image_url=product.primary_image_url,
        )


class PublicStorefrontSchema(BaseModel):
    """A shop, as a stranger sees it."""

    model_config = ConfigDict(extra="forbid")

    tenant_slug: str
    business_name: str
    headline: str | None
    description: str | None
    contact_phone: str | None
    products: list[PublicProductSchema]

    @classmethod
    def from_projection(cls, storefront: Any) -> PublicStorefrontSchema:
        return cls(
            tenant_slug=storefront.tenant_slug,
            business_name=storefront.business_name,
            headline=storefront.headline,
            description=storefront.description,
            contact_phone=storefront.contact_phone,
            products=[
                PublicProductSchema.from_projection(product) for product in storefront.products
            ],
        )


class PublicProductPageSchema(BaseModel):
    """One product of a shop, with the shop it belongs to named.

    The shop's name travels with the product because a shared link to a product is how most people
    arrive: a page that says "Rice 50kg" and nothing about who is selling it is a page a customer
    cannot act on.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_slug: str
    business_name: str
    contact_phone: str | None
    product: PublicProductSchema

    @classmethod
    def from_projection(cls, *, storefront: Any, product: Any) -> PublicProductPageSchema:
        return cls(
            tenant_slug=storefront.tenant_slug,
            business_name=storefront.business_name,
            contact_phone=storefront.contact_phone,
            product=PublicProductSchema.from_projection(product),
        )


__all__ = [
    "PublicProductPageSchema",
    "PublicProductSchema",
    "PublicStorefrontSchema",
    "StorefrontPublishSchema",
    "StorefrontResponseSchema",
    "StorefrontUpdateSchema",
]


class ProductShareSheetSchema(BaseModel):
    """Everything a share button needs, in one response.

    The public URL, the string a QR code should encode, and the WhatsApp link with the message
    already written. One response rather than three: the three describe one intention, and a client
    that fetched them separately would render a share sheet with a stale address in it.

    `whatsapp_url` is null when the business has no number a customer can message, and
    `whatsapp_unavailable_reason` says why. A typed absence rather than a silent null: a button that
    does nothing is worse than one that explains itself.
    """

    model_config = ConfigDict(extra="forbid")

    product_name: str
    public_url: str
    qr_payload: str
    whatsapp_url: str | None
    whatsapp_unavailable_reason: str | None
