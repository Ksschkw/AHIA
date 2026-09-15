"""Transport contracts for share links.

**The token appears in exactly one response.** `ShareLinkResponseSchema` - what a business sees when
it lists the links a sale has been shared through - has no field for it, because the server does not
have it: only a digest is stored, and the plaintext exists in the moment the link is minted.
`IssuedShareLinkResponseSchema` is the one shape that carries it, and it is returned once, by the
request that created the link.

**What a link opens is an allowlist, and the customer is not in it.** The shared invoice carries the
business's name and contact number, the receipt number, the moment of the sale, its lines and its
totals. It carries no customer name, no customer phone number and no internal identifier: the person
holding an invoice link already knows who they are, and a bearer token is not a reason to move
somebody's personal data.

**Money crosses as decimal strings.** `money_text` for amounts and `quantity_text` for quantities,
the same single wire format the rest of the product uses.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ahia.models.entities.share_link_model import ShareableResource
from ahia.schemas.money_format import money_text, quantity_text

#: How long a link should live, in days. Bounded on both sides: the entity refuses anything outside
#: the same range, and a request that asks for a century is asking for a permanent public address
#: for a customer's purchases.
ShareLinkLifetimeDays = Annotated[int, Field(ge=1, le=365, description="How long the link lasts.")]


class ShareLinkCreateSchema(BaseModel):
    """A request to share one invoice."""

    model_config = ConfigDict(extra="forbid")

    lifetime_days: ShareLinkLifetimeDays = 30


class ShareLinkResponseSchema(BaseModel):
    """A link a business has created, without the token that opens it."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    resource_type: ShareableResource
    resource_id: UUID
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    created_by_user_id: UUID | None
    is_open: bool

    @classmethod
    def from_entity(cls, link: Any, *, is_open: bool) -> ShareLinkResponseSchema:
        return cls(
            id=link.id,
            resource_type=link.resource_type,
            resource_id=link.resource_id,
            expires_at=link.expires_at,
            revoked_at=link.revoked_at,
            created_at=link.created_at,
            created_by_user_id=link.created_by_user_id,
            is_open=is_open,
        )


class IssuedShareLinkResponseSchema(BaseModel):
    """A freshly minted link, and the token that opens it.

    The only response in this product that carries a token, and it carries it once. A caller that
    loses it asks for a new link: the server cannot re-show it, because the server did not keep it.
    """

    model_config = ConfigDict(extra="forbid")

    link: ShareLinkResponseSchema
    token: str
    public_path: str


class SharedInvoiceLineSchema(BaseModel):
    """One line of a shared invoice."""

    model_config = ConfigDict(extra="forbid")

    product_name: str
    quantity: str
    unit_price: str
    line_total: str

    @classmethod
    def from_projection(cls, line: Any) -> SharedInvoiceLineSchema:
        return cls(
            product_name=line.product_name,
            quantity=quantity_text(Decimal(line.quantity)),
            unit_price=money_text(Decimal(line.unit_price)),
            line_total=money_text(Decimal(line.line_total)),
        )


class SharedInvoiceSchema(BaseModel):
    """An invoice opened through a link, for a caller with no account."""

    model_config = ConfigDict(extra="forbid")

    business_name: str
    business_contact_phone: str | None
    receipt_number: str
    occurred_at: datetime
    subtotal: str
    discount_amount: str
    total_amount: str
    lines: list[SharedInvoiceLineSchema]

    @classmethod
    def from_projection(cls, invoice: Any) -> SharedInvoiceSchema:
        return cls(
            business_name=invoice.business_name,
            business_contact_phone=invoice.business_contact_phone,
            receipt_number=invoice.receipt_number,
            occurred_at=invoice.occurred_at,
            subtotal=money_text(Decimal(invoice.subtotal)),
            discount_amount=money_text(Decimal(invoice.discount_amount)),
            total_amount=money_text(Decimal(invoice.total_amount)),
            lines=[SharedInvoiceLineSchema.from_projection(line) for line in invoice.lines],
        )
