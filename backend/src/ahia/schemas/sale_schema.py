"""Transport contracts for sales.

**A sale is one request.** Its lines and its payments travel together, because they are one
transaction: a client that sent a sale and then its lines would be able to leave a sale with
no lines if the second request failed, and the API would have created the exact state the
service is built to prevent.

**Money follows the same rule as everywhere else.** Amounts arrive as a number or a decimal
string and always leave as a decimal string; quantities carry three places. The renderers are
shared with the product and inventory contracts, so a total cannot be printed with different
precision from the line it came from.

**An operation identifier makes a request idempotent.** An offline client sends the same
basket again with the same identifier, and receives the sale it already created - marked as a
replay - rather than a second sale. Omitting it means every request creates a sale, which is
what an online client wants.

**Cancellation carries a reason and nothing else.** A client may not send a stock quantity, a
refund amount or a status: those are consequences the service derives from the sale, and
accepting them would let a caller decide what the books say.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

from ahia.models.entities.money import (
    MAXIMUM_MONEY,
    MAXIMUM_QUANTITY,
    ZERO_MONEY,
    coerce_money,
    coerce_quantity,
)
from ahia.models.entities.payment_model import (
    MAXIMUM_REFERENCE_LENGTH,
    PaymentMethod,
    PaymentModel,
)
from ahia.models.entities.sale_item_model import SaleItemModel
from ahia.models.entities.sale_model import (
    MAXIMUM_CANCELLATION_REASON_LENGTH,
    SaleModel,
)
from ahia.schemas.money_format import money_text, quantity_text

CancellationReason = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=MAXIMUM_CANCELLATION_REASON_LENGTH
    ),
]
PaymentReference = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAXIMUM_REFERENCE_LENGTH)
]


def _parse_money(value: Any) -> Decimal:
    """Parse an amount from the wire, keeping the failure a 422."""
    return coerce_money(value, field_name="amount", minimum=ZERO_MONEY, maximum=MAXIMUM_MONEY)


def _parse_quantity(value: Any) -> Decimal:
    """Parse a sold quantity; not bounded below here, because a line must be positive."""
    return coerce_quantity(value, field_name="quantity", maximum=MAXIMUM_QUANTITY)


#: An amount: two decimal places, never negative. A line's discount and a sale's discount are
#: both amounts, and a negative one would be a refund recorded through the wrong door.
Amount = Annotated[Decimal, BeforeValidator(_parse_money)]

#: A sold quantity: three decimal places, because a shop sells kilos as well as units.
SoldQuantity = Annotated[Decimal, BeforeValidator(_parse_quantity)]


class SaleLineRequestSchema(BaseModel):
    """One thing being sold.

    `unit_price` is optional because the usual case is the product's current price. When a
    price is sent it is what is charged and what is snapshotted - a negotiated price is a
    real thing at a counter - and the product's own price is not consulted.
    """

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    quantity: SoldQuantity
    unit_price: Amount | None = None
    discount_amount: Amount = ZERO_MONEY


class SalePaymentRequestSchema(BaseModel):
    """Money taken for the sale."""

    model_config = ConfigDict(extra="forbid")

    amount: Amount
    method: PaymentMethod = PaymentMethod.CASH
    reference: PaymentReference | None = None


class SaleCreateSchema(BaseModel):
    """A whole sale in one request."""

    model_config = ConfigDict(extra="forbid")

    lines: Annotated[list[SaleLineRequestSchema], Field(min_length=1, max_length=100)]
    payments: Annotated[list[SalePaymentRequestSchema], Field(max_length=20)] = []
    customer_id: UUID | None = None
    discount_amount: Amount = ZERO_MONEY
    # Set by an offline client so a replay is recognised. Absent means every request sells.
    operation_id: UUID | None = None
    # When the sale happened, for a client that was offline. Absent means now.
    occurred_at: datetime | None = None


class SaleCancellationSchema(BaseModel):
    """Why a sale was cancelled, and nothing else.

    A client may not send a status, a refund amount or a restock quantity: those are
    consequences the service derives from the sale, and accepting one would let a caller
    decide what the books say.
    """

    model_config = ConfigDict(extra="forbid")

    reason: CancellationReason


class SaleItemResponseSchema(BaseModel):
    """One line of a receipt, with the name and the price as they were at the time."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    product_id: UUID
    product_name_snapshot: str
    unit_price: str
    quantity: str
    discount_amount: str
    line_total: str

    @classmethod
    def from_entity(cls, item: SaleItemModel) -> SaleItemResponseSchema:
        return cls(
            id=item.id,
            product_id=item.product_id,
            product_name_snapshot=item.product_name_snapshot,
            unit_price=money_text(item.unit_price),
            quantity=quantity_text(item.quantity),
            discount_amount=money_text(item.discount_amount),
            line_total=money_text(item.line_total),
        )


class PaymentResponseSchema(BaseModel):
    """One payment, with its amount and what has happened to it since."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    amount: str
    method: str
    reference: str | None
    status: str
    received_at: datetime
    refunded_at: datetime | None

    @classmethod
    def from_entity(cls, payment: PaymentModel) -> PaymentResponseSchema:
        return cls(
            id=payment.id,
            amount=money_text(payment.amount),
            method=payment.method.value,
            reference=payment.reference,
            status=payment.status.value,
            received_at=payment.received_at,
            refunded_at=payment.refunded_at,
        )


class SaleResponseSchema(BaseModel):
    """One sale as a business sees it, with its lines and its payments.

    The lines and the payments belong in the response rather than behind a second request:
    this is a receipt, and a receipt a client has to assemble from three calls is a receipt
    that can be shown half-finished.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    receipt_number: str
    customer_id: UUID | None
    seller_id: UUID
    device_id: UUID | None
    operation_id: UUID | None
    subtotal: str
    discount_amount: str
    total_amount: str
    status: str
    payment_status: str
    is_settled: bool
    occurred_at: datetime
    cancelled_at: datetime | None
    cancellation_reason: str | None
    created_at: datetime
    updated_at: datetime
    items: list[SaleItemResponseSchema]
    payments: list[PaymentResponseSchema]

    @classmethod
    def from_entities(
        cls,
        sale: SaleModel,
        *,
        items: list[SaleItemModel],
        payments: list[PaymentModel],
    ) -> SaleResponseSchema:
        """Shape a sale with its lines and payments.

        Entities rather than the service's combined result: a schema that imported the
        service would depend on the layer above it, which the architecture contract forbids -
        and the contract test caught exactly that the first time this was written.
        """
        return cls(
            id=sale.id,
            tenant_id=sale.tenant_id,
            receipt_number=sale.receipt_number,
            customer_id=sale.customer_id,
            seller_id=sale.seller_id,
            device_id=sale.device_id,
            operation_id=sale.operation_id,
            subtotal=money_text(sale.subtotal),
            discount_amount=money_text(sale.discount_amount),
            total_amount=money_text(sale.total_amount),
            status=sale.status.value,
            payment_status=sale.payment_status.value,
            is_settled=sale.is_settled(),
            occurred_at=sale.occurred_at,
            cancelled_at=sale.cancelled_at,
            cancellation_reason=sale.cancellation_reason,
            created_at=sale.created_at,
            updated_at=sale.updated_at,
            items=[SaleItemResponseSchema.from_entity(item) for item in items],
            payments=[PaymentResponseSchema.from_entity(payment) for payment in payments],
        )


class SaleCreationResponseSchema(BaseModel):
    """The receipt, and whether this request produced it or found it.

    `was_replayed` tells a client that its basket had already been recorded: the receipt
    returned is the original one, and a client can show it again rather than ringing the sale
    up twice.
    """

    model_config = ConfigDict(extra="forbid")

    sale: SaleResponseSchema
    was_replayed: bool


class SaleSummaryResponseSchema(BaseModel):
    """One sale in a list, without its lines or payments.

    A day's sales are read as a list of receipts, and loading every line of every sale to
    render that list is the query that makes a sales screen slow.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    receipt_number: str
    customer_id: UUID | None
    seller_id: UUID
    total_amount: str
    status: str
    payment_status: str
    occurred_at: datetime
    cancelled_at: datetime | None

    @classmethod
    def from_entity(cls, sale: SaleModel) -> SaleSummaryResponseSchema:
        return cls(
            id=sale.id,
            receipt_number=sale.receipt_number,
            customer_id=sale.customer_id,
            seller_id=sale.seller_id,
            total_amount=money_text(sale.total_amount),
            status=sale.status.value,
            payment_status=sale.payment_status.value,
            occurred_at=sale.occurred_at,
            cancelled_at=sale.cancelled_at,
        )
