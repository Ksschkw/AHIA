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
    #: The line this one sits under, named by its position in this submission: the
    #: customer's own heading, with their things beneath it. **A parent must come
    #: before its child**, so a loop cannot be expressed at all.
    parent_position: Annotated[int, Field(ge=0)] | None = None


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
    """What a customer is told: that it arrived, and nothing about the shop's own affairs.

    It carries the list's own address, because the customer needs it: they will close the page, and
    the
    link is how they come back to their list - and how the trader opens the same one.
    """

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    line_count: int
    message: str
    # : The path of this list, absolute from the site root. The token is the customer's own; it is
    # not a
    #: secret from them, and without it they cannot return to what they built.
    list_path: str


class RequestLineWorkSchema(BaseModel):
    """What the trader says about one line: where he got it, what it cost, what he charges.

    Every field is optional and the difference between "not sent" and "sent as null" is preserved: a
    price sent as null is not a price, a cost sent as null clears what he had recorded, and a state
    sent
    as null leaves it where it is.
    """

    model_config = ConfigDict(extra="forbid")

    state: RequestLineState | None = None
    #: What it cost him, when he had to go and buy it. Null clears it.
    cost_price: Money | None = None
    #: What the customer pays, per piece. On the list, not on the catalogue: this is the agreement.
    shop_price: Money | None = None


class PublicListLineSchema(BaseModel):
    """One line of a list, as the customer who sent it sees it.

    The shop's price and nothing else: what it cost the trader, and what he makes, are his business
    and
    never travel to a customer - the same rule the shop page follows about stock.
    """

    model_config = ConfigDict(extra="forbid")

    position: int
    #: The position of the line this one sits under, or None when it stands at the top of the list.
    parent_position: int | None
    text: str
    group: str | None
    quantity: str
    pieces: str
    shop_price: str | None
    line_total: str | None
    state: RequestLineState


class PublicListSchema(BaseModel):
    """A customer's own list, at its own address."""

    model_config = ConfigDict(extra="forbid")

    business_name: str
    tenant_slug: str
    status: RequestStatus
    created_at: datetime
    lines: list[PublicListLineSchema]
    priced_total: str | None
    unpriced_line_count: int


class RequestLineResponseSchema(BaseModel):
    """One line of a list, as the trader sees it."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    position: int
    product_id: UUID | None
    product_name: str | None = None
    group_name: str | None = None
    parent_position: int | None = None
    free_text: str | None
    note: str | None
    quantity: str
    unit: RequestLineUnit
    pieces_per_pack: int | None
    pieces: str
    customer_price: str | None
    shop_price: str | None
    # : What it cost him when he had to go and buy it. The one number paper can never give him: at
    # the
    #: end of a mixed list, this is what tells him what he actually made on it.
    cost_price: str | None
    line_total: str | None
    #: What he made on this line, when both numbers are known. None while one of them is missing,
    #: because a margin computed from half the facts is a number somebody would act on.
    margin: str | None
    state: RequestLineState
    image_key: str | None


class CustomerListLineItemSchema(BaseModel):
    """One line on a customer's past list, ready to be reused."""

    model_config = ConfigDict(extra="forbid")

    position: int
    product_id: UUID | None = None
    text: str
    group: str | None = None
    quantity: str
    unit: str
    pieces_per_pack: int | None = None
    shop_price: str | None = None


class CustomerListSummarySchema(BaseModel):
    """A previous list for a returning customer."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    created_at: datetime
    status: RequestStatus
    line_count: int
    priced_total: str | None
    lines_preview: list[str]
    lines: list[CustomerListLineItemSchema] = []


class DispatchSchema(BaseModel):
    """How a list was sent.

    Every field is optional, and none of them means "clear the rest": this is what the trader wrote
    down on the way to the park, and what he did not write down is simply not there.
    """

    model_config = ConfigDict(extra="forbid")

    transporter_name: str | None = None
    transporter_phone: str | None = None
    waybill_number: str | None = None
    dispatch_cost: Money | None = None
    tracking_url: str | None = None


class RequestResponseSchema(BaseModel):
    """A list, as the business sees it - with its lines and what they come to."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    customer_phone: str
    customer_name: str | None
    status: RequestStatus
    note: str | None
    created_at: datetime
    #: How it was sent, once it has been. None for a list nobody has dispatched yet, which is not
    #: the same as one collected by hand.
    transporter_name: str | None = None
    transporter_phone: str | None = None
    waybill_number: str | None = None
    dispatch_cost: str | None = None
    tracking_url: str | None = None
    dispatched_at: datetime | None = None
    lines: list[RequestLineResponseSchema]
    # : What is known so far. None while nothing is priced, because a total missing money is worse
    # than
    #: no total at all - the screen says "to be priced" instead of adding up what it does not know.
    priced_total: str | None
    unpriced_line_count: int
