"""Transport contracts for expenses.

**The category arrives as an enum, so a client can only send one the product knows.** FastAPI
publishes the members in the OpenAPI document and refuses anything else with a 422 that names
the permitted values, which is what makes "expense categories are configuration" true at the
edge as well as in the entity: a client picks from the server's list instead of hard-coding
one, and a category added to the vocabulary appears in the contract without a client change.

**Money crosses the wire as a decimal string, both directions.** `money_text` is the single
format, the same one every other slice uses, so a client cannot receive a JSON number whose
binary float rounds a kobo away on the way back.

**The client is not allowed to say who recorded an expense, or on what device.** The actor and
the device come from the authenticated context, so the create contract has no such fields and
forbids extras: a request carrying `actor_id` is refused rather than half-ignored.

**The wire carries no currency.** Money in this product is the tenant's currency, stated once
on the business, and repeating it on every expense would invite a client to compare two naira
amounts as if the unit were in question.

**Reversal is a request with a reason, and there is no delete route at all.** A mistaken
expense is corrected by `POST /expenses/{expense_id}/reverse`, which is a written, attributed
action. This module deliberately defines no update contract: the amount that was spent is what
was spent.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ahia.models.entities.expense_category import ExpenseCategory
from ahia.models.entities.expense_model import ExpenseModel
from ahia.models.entities.money import MAXIMUM_MONEY, ZERO_MONEY
from ahia.models.entities.payment_model import PaymentMethod
from ahia.schemas.money_format import money_text

ExpenseDescription = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
#: The reason a reversal is being made. Required, because a correction without one is a
#: number somebody has to explain from memory.
ExpenseReversalReason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
#: A positive amount. The bound is the entity's, so a value that would be refused by the
#: domain is refused at the edge with a field-level message rather than a 500.
ExpenseAmount = Annotated[Decimal, Field(gt=ZERO_MONEY, le=MAXIMUM_MONEY)]

#: The category as it crosses the wire, including as a filter on the list route. Re-exported
#: from the entity so the request body, the response and the filter cannot drift apart, and
#: because the transport layer speaks in contract types: a router importing the entity
#: directly would be the transport layer reaching into the domain.
ExpenseCategoryName = ExpenseCategory


class ExpenseCreateSchema(BaseModel):
    """An expense a business is recording.

    `incurred_at` is optional and means "now" when absent: most expenses are recorded as they
    are paid, and a back-dated one is the case that has to say so. It must carry a timezone,
    because a bare local time means a different instant to every client that sends one.
    """

    model_config = ConfigDict(extra="forbid")

    category: ExpenseCategory
    amount: ExpenseAmount
    payment_method: PaymentMethod = PaymentMethod.CASH
    description: ExpenseDescription | None = None
    incurred_at: datetime | None = None
    # A client-generated identifier that makes a queued expense safe to resend. Optional: an
    # online request does not need one, and requiring it would invent an identifier for the
    # client to manage.
    operation_id: UUID | None = None


class ExpenseReversalSchema(BaseModel):
    """A request to undo an expense the business did not really spend."""

    model_config = ConfigDict(extra="forbid")

    reason: ExpenseReversalReason


class ExpenseResponseSchema(BaseModel):
    """One expense, as the business recorded it.

    The amount is a decimal string: `money_text` is the one wire format for money in this
    product, and a JSON number would let a client's float arithmetic disagree with the
    ledger. `counted_amount` is included because a reversed expense is still in the list and
    a client that shows spending should not have to know that reversal means zero.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    category: ExpenseCategory
    category_label: str
    amount: str
    counted_amount: str
    payment_method: PaymentMethod
    description: str | None
    incurred_at: datetime
    actor_id: UUID
    device_id: UUID | None
    operation_id: UUID | None
    is_reversed: bool
    reversed_at: datetime | None
    reversal_reason: str | None
    created_at: datetime

    @classmethod
    def from_entity(cls, expense: ExpenseModel) -> ExpenseResponseSchema:
        return cls(
            id=expense.id,
            tenant_id=expense.tenant_id,
            category=expense.category,
            # The heading as a person reads it. Sent because a client that renders the raw
            # value would turn "FEES_AND_LEVIES" into a label of its own, differently in
            # every client.
            category_label=expense.category.label(),
            amount=money_text(expense.amount),
            counted_amount=money_text(expense.counted_amount()),
            payment_method=expense.payment_method,
            description=expense.description,
            incurred_at=expense.incurred_at,
            actor_id=expense.actor_id,
            device_id=expense.device_id,
            operation_id=expense.operation_id,
            is_reversed=expense.has_been_reversed(),
            reversed_at=expense.reversed_at,
            reversal_reason=expense.reversal_reason,
            created_at=expense.created_at,
        )


class ExpenseCategorySchema(BaseModel):
    """One heading a spending report groups by, as a client should render it."""

    model_config = ConfigDict(extra="forbid")

    value: ExpenseCategory
    label: str
    is_known_spending: bool

    @classmethod
    def from_category(cls, category: ExpenseCategory) -> ExpenseCategorySchema:
        return cls(
            value=category,
            label=category.label(),
            is_known_spending=category.is_known_spending,
        )


class ExpenseCategoryListSchema(BaseModel):
    """The declared vocabulary, so a client chooses instead of guessing."""

    model_config = ConfigDict(extra="forbid")

    categories: list[ExpenseCategorySchema]


class SpendingByCategorySchema(BaseModel):
    """What the business spent per category in a period.

    Values are decimal strings, and a category with no spending is absent rather than zero:
    the vocabulary endpoint tells a client what the headings are, and inventing zero rows
    here would be this layer deciding what a report displays.

    The total comes from the service. Summing the mapping here would be arithmetic in a
    transport handler, and a handler that rounds is a handler whose total disagrees with the
    ledger.
    """

    model_config = ConfigDict(extra="forbid")

    since: datetime
    until: datetime
    total_spent: str
    by_category: dict[ExpenseCategory, str]

    @classmethod
    def from_amounts(
        cls,
        *,
        since: datetime,
        until: datetime,
        total_spent: Decimal,
        amounts_by_category: Mapping[ExpenseCategory, Decimal],
    ) -> SpendingByCategorySchema:
        """Render a report the service produced. Plain values, not a service type: a schema
        that imported the service would depend outward, and the wire contract would then
        change every time a use case did."""
        return cls(
            since=since,
            until=until,
            total_spent=money_text(total_spent),
            by_category={
                category: money_text(amount) for category, amount in amounts_by_category.items()
            },
        )
