"""The transport shapes of a customer's list.

Two audiences, deliberately different. A customer sends a list and needs nothing but an
acknowledgement -
no session, no account, and no view of anything the shop keeps to itself. The trader reads the same
list
with everything he needs to act on it: what was asked for, what it is priced at, and what it cost
him.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

from ahia.models.entities.request_line_model import RequestLineState, RequestLineUnit
from ahia.models.entities.request_model import RequestStatus


#: A price as text or a number, so a client that sends 350 is not argued with about JSON types.
def _parse_decimal(value: object) -> object:
    """Accept a decimal string or a number, and let the entity decide whether it is a price at
    all."""
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            return value
    return value


Money = Annotated[Decimal, BeforeValidator(_parse_decimal)]
Quantity = Annotated[Decimal, BeforeValidator(_parse_decimal)]

CustomerPhone = Annotated[
    str, StringConstraints(min_length=7, max_length=32, strip_whitespace=True)
]
CustomerName = Annotated[str, StringConstraints(max_length=120, strip_whitespace=True)]
LineText = Annotated[str, StringConstraints(min_length=2, max_length=400, strip_whitespace=True)]


class PublicRequestLineSchema(BaseModel):
    """One thing a customer is asking for.

    Either something from the catalogue - which carries a price they could see - or free text with
    their
    own words, because in real life nothing stops a customer asking for what the shop has not
    listed.
    An unpriced line is normal: the customer does not price what the trader has to go and find.
    """

    model_config = ConfigDict(extra="forbid")

    #: The catalogue is addressed by slug in public, because a slug is what appears in a link and an
    #: internal identifier must never be handed to a stranger. The service resolves it inside the
    #: shop's own catalogue.
    product_slug: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = None
    free_text: LineText | None = None
    quantity: Quantity = Decimal("1")
    unit: RequestLineUnit = RequestLineUnit.PIECE
    pieces_per_pack: int | None = Field(default=None, ge=1, le=1000)
    note: LineText | None = None
    #: What they were shown when they built the list. A record of a conversation, not a promise.
    customer_price: Money | None = None
    #: A photograph of the thing they mean, which needs no words from either side.
    image_key: Annotated[str, StringConstraints(max_length=512)] | None = None


class PublicRequestSchema(BaseModel):
    """A list as it arrives from somebody with no account."""

    model_config = ConfigDict(extra="forbid")

    #: The only thing asked of a customer, and the reason is said out loud in the interface: so the
    #: trader knows whose list this is, and so they do not start from nothing next time.
    customer_phone: CustomerPhone
    customer_name: CustomerName | None = None
    note: LineText | None = None
    lines: list[PublicRequestLineSchema] = Field(min_length=1, max_length=200)


class PublicRequestAcceptedSchema(BaseModel):
    """What a customer is told: that it arrived, and nothing about the shop's own affairs."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    line_count: int
    message: str


class RequestLineResponseSchema(BaseModel):
    """One line of a list, as the trader sees it."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    position: int
    product_id: UUID | None
    free_text: str | None
    note: str | None
    quantity: str
    unit: RequestLineUnit
    pieces_per_pack: int | None
    pieces: str
    customer_price: str | None
    shop_price: str | None
    line_total: str | None
    state: RequestLineState
    image_key: str | None


class RequestResponseSchema(BaseModel):
    """A list, as the business sees it - with its lines and what they come to."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    customer_phone: str
    customer_name: str | None
    status: RequestStatus
    note: str | None
    created_at: datetime
    lines: list[RequestLineResponseSchema]
    # : What is known so far. None while nothing is priced, because a total missing money is worse
    # than
    #: no total at all - the screen says "to be priced" instead of adding up what it does not know.
    priced_total: str | None
    unpriced_line_count: int
