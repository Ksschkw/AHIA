"""HTTP transport for expenses.

Five routes on `/tenants/{tenant_id}/expenses`.

**There is no delete route, and there is no update route.** A mistaken expense is corrected by
`POST /expenses/{expense_id}/reverse`, which records when, why and who and appends the ledger
entry that credits the money back. Offering `DELETE` would let a client erase money the
business spent, and offering `PATCH` would let it change an amount the ledger has already
recorded as a debit - neither of which the service layer can undo, because the ledger is
append-only.

**The category vocabulary has its own route.** `GET /expenses/categories` publishes the
declared set, which is what lets a client render the picker without hard-coding headings this
product can change. It is declared before the parameterised `/expenses/{expense_id}` route,
because FastAPI matches in registration order and the literal word `categories` would
otherwise be parsed as an expense identifier and answered with a misleading 422.

**The report route takes a period and returns the total.** Both boundaries are required, so
"how much did we spend" always has a start and an end: a report with no period is a number
that grows every day and cannot be compared with anything. `since` is inclusive and `until` is
exclusive, so consecutive periods tile without counting one expense twice.

Every handler parses, calls one service method and shapes the response. Authorization,
idempotency, reversal and the exclusion of reversed expenses from a report all live in the
service, where a CLI or a scheduled job gets the same answers as an HTTP request.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from ahia.core.tenant_context import TenantContext
from ahia.routers.tenant_router import require_tenant_context
from ahia.schemas.expense_schema import (
    ExpenseCategoryListSchema,
    ExpenseCategoryName,
    ExpenseCategorySchema,
    ExpenseCreateSchema,
    ExpenseResponseSchema,
    ExpenseReversalSchema,
    SpendingByCategorySchema,
)
from ahia.services.expense_service import ExpenseService

_TENANT_SCOPE_PREFIX: Final[str] = "/tenants/{tenant_id}"

router = APIRouter(prefix=_TENANT_SCOPE_PREFIX, tags=["expenses"])


def get_expense_service(request: Request) -> ExpenseService:
    """Return the expense service for this request."""
    service: ExpenseService = request.app.state.container.expense_service
    return service


ExpenseServiceDependency = Annotated[ExpenseService, Depends(get_expense_service)]
TenantContextDependency = Annotated[TenantContext, Depends(require_tenant_context)]


@dataclass(frozen=True, slots=True)
class ExpensePeriod:
    """The period a listing is narrowed to, as the caller sent it.

    Both bounds are optional here, because a list without a period is "recent expenses". The
    report route declares them required instead: "how much did we spend" is a question with a
    start and an end, and a report with no period is a number that grows every day and can be
    compared with nothing.

    `since` is inclusive and `until` is exclusive, so consecutive periods tile without
    counting one expense twice.
    """

    since: Annotated[
        datetime | None,
        Query(description="Only expenses incurred at or after this moment."),
    ] = None
    until: Annotated[
        datetime | None,
        Query(description="Only expenses incurred before this moment."),
    ] = None


ExpensePeriodDependency = Annotated[ExpensePeriod, Depends()]


@router.post(
    "/expenses",
    response_model=ExpenseResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Record an expense",
)
async def record_expense(
    payload: ExpenseCreateSchema,
    tenant_context: TenantContextDependency,
    service: ExpenseServiceDependency,
) -> ExpenseResponseSchema:
    """Record what the business spent, and debit the ledger for it.

    Sending an `operation_id` that has already been recorded returns the original expense
    instead of a second one, which is what makes a queued expense safe to resend.
    """
    recorded = await service.record_expense(
        tenant_context,
        category=payload.category,
        amount=payload.amount,
        payment_method=payload.payment_method,
        description=payload.description,
        incurred_at=payload.incurred_at,
        operation_id=payload.operation_id,
    )
    return ExpenseResponseSchema.from_entity(recorded.expense)


@router.get(
    "/expenses/categories",
    response_model=ExpenseCategoryListSchema,
    summary="List the expense categories",
)
async def list_expense_categories(
    tenant_context: TenantContextDependency,
    service: ExpenseServiceDependency,
) -> ExpenseCategoryListSchema:
    """Return the declared vocabulary, so a client chooses instead of guessing.

    The permission check happens in the service, so this route is not a way to read a
    business's data without authority even though the answer is the same for every business.
    """
    categories = await service.list_categories(tenant_context)
    return ExpenseCategoryListSchema(
        categories=[ExpenseCategorySchema.from_category(category) for category in categories]
    )


@router.get(
    "/expenses/report",
    response_model=SpendingByCategorySchema,
    summary="What the business spent in a period",
)
async def report_spending(
    tenant_context: TenantContextDependency,
    service: ExpenseServiceDependency,
    since: Annotated[
        datetime,
        Query(description="Start of the period, inclusive. Must carry a timezone."),
    ],
    until: Annotated[
        datetime,
        Query(description="End of the period, exclusive. Must carry a timezone."),
    ],
) -> SpendingByCategorySchema:
    """Return spending per category and in total, excluding reversed expenses."""
    report = await service.spending_by_category(tenant_context, since=since, until=until)
    return SpendingByCategorySchema.from_amounts(
        since=report.since,
        until=report.until,
        total_spent=report.total_spent,
        amounts_by_category=report.by_category,
    )


@router.get(
    "/expenses",
    response_model=list[ExpenseResponseSchema],
    summary="List this business's expenses",
)
async def list_expenses(
    tenant_context: TenantContextDependency,
    service: ExpenseServiceDependency,
    period: ExpensePeriodDependency,
    category: Annotated[
        ExpenseCategoryName | None,
        Query(description="Only expenses filed under this heading."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="How many to return.")] = 100,
) -> list[ExpenseResponseSchema]:
    """Return the expenses, most recently incurred first.

    Reversed expenses are included: this is the record of what was entered, and a person
    looking for the entry they reversed has to be able to find it.
    """
    expenses = await service.list_expenses(
        tenant_context,
        category=category,
        since=period.since,
        until=period.until,
        limit=limit,
    )
    return [ExpenseResponseSchema.from_entity(expense) for expense in expenses]


@router.get(
    "/expenses/{expense_id}",
    response_model=ExpenseResponseSchema,
    summary="Read one expense",
)
async def get_expense(
    expense_id: UUID,
    tenant_context: TenantContextDependency,
    service: ExpenseServiceDependency,
) -> ExpenseResponseSchema:
    """Return one expense. An expense of another business is a 404, not a 403."""
    expense = await service.get_expense(tenant_context, expense_id=expense_id)
    return ExpenseResponseSchema.from_entity(expense)


@router.post(
    "/expenses/{expense_id}/reverse",
    response_model=ExpenseResponseSchema,
    summary="Undo an expense that was not really spent",
)
async def reverse_expense(
    expense_id: UUID,
    payload: ExpenseReversalSchema,
    tenant_context: TenantContextDependency,
    service: ExpenseServiceDependency,
) -> ExpenseResponseSchema:
    """Credit the money back, keeping the original expense and its ledger entry.

    A reversal, not a deletion: the money moved, so the record of it stays, and a second
    reversal of the same expense changes nothing.
    """
    reversed_expense = await service.reverse_expense(
        tenant_context, expense_id=expense_id, reason=payload.reason
    )
    return ExpenseResponseSchema.from_entity(reversed_expense.expense)
