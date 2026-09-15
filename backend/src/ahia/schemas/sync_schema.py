"""Transport contracts for offline synchronization.

**The wire validates shape; the use cases validate permission and meaning.** Every payload model
forbids extras, so a client cannot smuggle a field the server would half-ignore, and each one
carries exactly the keys its operation needs. What the sync service then does with the validated
mapping is translation, not validation: it reads keys the contract promised and hands them to the
use case that owns the operation.

**Operations are a discriminated union on `operation_type`.** A client sends a queue, and each
entry is parsed as the operation it claims to be. An unknown operation type is a 422 at the edge
rather than a recorded rejection, because a client that speaks a protocol this server does not
have should learn that from the contract rather than from a queue of rejections it cannot act on.
An operation the server knows but refuses at run time - a permission it no longer holds - is a
recorded `REJECTED`, which is a different thing entirely.

**Money crosses as a decimal string on the way out and accepts a decimal on the way in.**
`money_text` renders responses, and request amounts are `Decimal` so pydantic parses `"3500.00"`
without a float ever existing. The client's own arithmetic is its business; the server's is not
allowed to round.

**A conflict is a 200 with a conflict in it, not a 409 for the whole queue.** One operation's
stale version must not hide the answers to the twenty behind it. Each result carries its own
status, and a client that wants to know what needs its attention reads `needs_attention`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ahia.models.entities.expense_category import ExpenseCategory
from ahia.models.entities.money import MAXIMUM_MONEY, ZERO_MONEY
from ahia.models.entities.payment_model import PaymentMethod
from ahia.models.entities.sync_change_model import ChangeType
from ahia.models.entities.sync_operation_model import SyncOperationStatus

PositiveAmount = Annotated[Decimal, Field(gt=ZERO_MONEY, le=MAXIMUM_MONEY)]
SignedAmount = Annotated[Decimal, Field(ge=-MAXIMUM_MONEY, le=MAXIMUM_MONEY)]
PositiveQuantity = Annotated[Decimal, Field(gt=ZERO_MONEY, le=Decimal("1000000"))]
Sequence = Annotated[int, Field(ge=0)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
ShortOptionalText = (
    Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] | None
)
OptionalPhone = (
    Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=32)] | None
)
OptionalEmail = Annotated[str, StringConstraints(strip_whitespace=True, max_length=254)] | None
ShortOptional = ShortText | None


class SaleLinePushSchema(BaseModel):
    """One line of a sale recorded offline."""

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    quantity: PositiveQuantity
    unit_price: PositiveAmount | None = None
    discount_amount: PositiveAmount | None = None


class SalePaymentPushSchema(BaseModel):
    """Money taken for a sale recorded offline."""

    model_config = ConfigDict(extra="forbid")

    amount: PositiveAmount
    method: PaymentMethod = PaymentMethod.CASH
    reference: Annotated[str, StringConstraints(max_length=64)] | None = None


class SalePushPayload(BaseModel):
    """What a sale needs to be completed."""

    model_config = ConfigDict(extra="forbid")

    lines: Annotated[list[SaleLinePushSchema], Field(min_length=1)]
    payments: list[SalePaymentPushSchema] = Field(default_factory=list)
    customer_id: UUID | None = None


class ExpensePushPayload(BaseModel):
    """What an expense needs to be recorded."""

    model_config = ConfigDict(extra="forbid")

    category: ExpenseCategory
    amount: PositiveAmount
    payment_method: PaymentMethod = PaymentMethod.CASH
    description: ShortText | None = None


class CustomerPushPayload(BaseModel):
    """What a new customer needs."""

    model_config = ConfigDict(extra="forbid")

    name: ShortText
    phone: OptionalPhone
    email: OptionalEmail = None
    address: ShortOptional = None
    notes: ShortOptional = None


class CustomerEditPushPayload(BaseModel):
    """A versioned edit of a customer, with the version the client was working from."""

    model_config = ConfigDict(extra="forbid")

    customer_id: UUID
    # Required, not optional: this is the versioned case of the conflict matrix, and an edit
    # without a version would be a last-writer-wins write pretending to be a checked one.
    expected_version: Annotated[int, Field(ge=1)]
    name: ShortOptional = None
    phone: OptionalPhone = None
    email: OptionalEmail = None
    address: ShortOptional = None
    notes: ShortOptional = None


class StockReceiptPushPayload(BaseModel):
    """Stock that arrived while the device was offline."""

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    quantity: PositiveQuantity
    note: ShortText | None = None


class StockAdjustmentPushPayload(BaseModel):
    """A counted correction, as a delta rather than an absolute quantity.

    A delta is what makes this operation-based: two devices counting the same shelf each record
    what they found as a change from what the server held, and neither can silently overwrite the
    other's count the way an absolute quantity would.
    """

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    delta: SignedAmount
    reason: ShortText


class SalePushOperationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    operation_type: Literal["complete_sale"]
    payload: SalePushPayload


class ExpensePushOperationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    operation_type: Literal["record_expense"]
    payload: ExpensePushPayload


class CustomerPushOperationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    operation_type: Literal["create_customer"]
    payload: CustomerPushPayload


class CustomerEditPushOperationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    operation_type: Literal["update_customer"]
    payload: CustomerEditPushPayload


class StockReceiptPushOperationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    operation_type: Literal["receive_stock"]
    payload: StockReceiptPushPayload


class StockAdjustmentPushOperationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    operation_type: Literal["adjust_stock"]
    payload: StockAdjustmentPushPayload


PushOperationSchema = Annotated[
    SalePushOperationSchema
    | ExpensePushOperationSchema
    | CustomerPushOperationSchema
    | CustomerEditPushOperationSchema
    | StockReceiptPushOperationSchema
    | StockAdjustmentPushOperationSchema,
    Field(discriminator="operation_type"),
]


class SyncPushRequestSchema(BaseModel):
    """A queue of operations, in the order the device recorded them."""

    model_config = ConfigDict(extra="forbid")

    operations: Annotated[list[PushOperationSchema], Field(min_length=1, max_length=200)]


class SyncOperationResultSchema(BaseModel):
    """What became of one operation."""

    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    operation_type: str
    status: SyncOperationStatus
    needs_attention: bool
    entity_type: str | None
    entity_id: UUID | None
    detail: dict[str, str]

    @classmethod
    def from_result(cls, result: Any) -> SyncOperationResultSchema:
        """Render a service result. Plain values rather than a service type.

        The schema reads attributes rather than importing the service, because a contract that
        depended on a use case would change every time the use case did.
        """
        return cls(
            operation_id=result.operation_id,
            operation_type=result.operation_type,
            status=result.status,
            needs_attention=result.needs_the_clients_attention,
            entity_type=result.entity_type,
            entity_id=result.entity_id,
            detail=dict(result.detail),
        )


class SyncPushResponseSchema(BaseModel):
    """Every operation's answer, in the order they were pushed."""

    model_config = ConfigDict(extra="forbid")

    results: list[SyncOperationResultSchema]


class SyncPullRequestSchema(BaseModel):
    """How far the device has read, and how much it wants."""

    model_config = ConfigDict(extra="forbid")

    # Zero means "everything": a device that has never synchronized asks from the beginning, and
    # the feed's first sequence is one.
    after_sequence: Sequence = 0
    limit: Annotated[int, Field(ge=1, le=500)] = 500


class SyncChangeSchema(BaseModel):
    """One change a device must fetch.

    The feed names records rather than carrying them: a client fetches the current record through
    the endpoint that owns it, which already checks the permission and already knows the wire
    format. A payload here would be a second representation of the domain that can disagree with
    the first.
    """

    model_config = ConfigDict(extra="forbid")

    change_sequence: int
    entity_type: str
    entity_id: UUID
    change_type: ChangeType
    occurred_at: datetime

    @classmethod
    def from_entity(cls, change: Any) -> SyncChangeSchema:
        return cls(
            change_sequence=change.change_sequence,
            entity_type=change.entity_type,
            entity_id=change.entity_id,
            change_type=change.change_type,
            occurred_at=change.occurred_at,
        )


class SyncPullResponseSchema(BaseModel):
    """A page of changes, and where the business's feed has reached."""

    model_config = ConfigDict(extra="forbid")

    changes: list[SyncChangeSchema]
    latest_sequence: int
    has_more: bool


class SyncCursorRequestSchema(BaseModel):
    """How far the device has applied."""

    model_config = ConfigDict(extra="forbid")

    sequence: Sequence


class SyncCursorResponseSchema(BaseModel):
    """The position the device now holds."""

    model_config = ConfigDict(extra="forbid")

    last_server_sequence: int


def payload_as_mapping(payload: BaseModel) -> dict[str, Any]:
    """Return a validated payload as JSON primitives for the service to translate.

    `mode="json"` renders amounts and identifiers as strings, which is what the sync service reads
    and what it hands to the use cases. `exclude_unset=True` preserves the difference between a
    field the client did not send and one it sent as null - the same distinction the online edit
    contract makes, and the reason a first version of this function failed a test: every optional
    customer field arrived as an explicit `null`, and the use case read "name is null" as an
    attempt to rename the customer to nothing.
    """
    return payload.model_dump(mode="json", exclude_unset=True)
