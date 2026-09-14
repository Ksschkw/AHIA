"""HTTP transport for sales.

Four routes on `/tenants/{tenant_id}/sales`: record a sale, list them, read one, and cancel
one. A sale is recorded in a single request, because its lines and its payments are one
transaction - a client that sent the sale and then its lines could leave a sale with no
lines, which is exactly the state the service exists to make impossible.

A replay is not an error. An offline client that sends the same basket twice receives the
sale it already created, with `was_replayed` set, and a 201 - the request was understood and
the resource it names exists, which is what the status means. Answering 409 would tell a
client to reconcile something that is already correct.

Every handler parses, calls one service method and shapes the response. Authorization, the
receipt counter, the stock movements, the ledger and the rollback all live in the service.
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from ahia.core.tenant_context import TenantContext
from ahia.routers.tenant_router import require_tenant_context
from ahia.schemas.sale_schema import (
    SaleCancellationSchema,
    SaleCreateSchema,
    SaleCreationResponseSchema,
    SaleResponseSchema,
    SaleSummaryResponseSchema,
)
from ahia.services.sale_service import PaymentRequest, SaleLineRequest, SalesService

_TENANT_SCOPE_PREFIX: Final[str] = "/tenants/{tenant_id}"

#: The largest number of sales a single listing returns.
MAXIMUM_SALE_LIST_LIMIT: Final[int] = 200

router = APIRouter(prefix=_TENANT_SCOPE_PREFIX, tags=["sales"])


def get_sales_service(request: Request) -> SalesService:
    """Return the sales service for this request."""
    service: SalesService = request.app.state.container.sales_service
    return service


SalesServiceDependency = Annotated[SalesService, Depends(get_sales_service)]
TenantContextDependency = Annotated[TenantContext, Depends(require_tenant_context)]


@router.post(
    "/sales",
    response_model=SaleCreationResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Record a sale",
)
async def complete_sale(
    payload: SaleCreateSchema,
    tenant_context: TenantContextDependency,
    service: SalesServiceDependency,
) -> SaleCreationResponseSchema:
    """Record a sale: its lines, its payments, the stock it moved and its ledger entry.

    Sending an `operation_id` that has already been seen returns the sale that was created
    the first time, with `was_replayed` set.
    """
    result = await service.complete_sale(
        tenant_context,
        lines=[
            SaleLineRequest(
                product_id=line.product_id,
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount_amount=line.discount_amount,
            )
            for line in payload.lines
        ],
        payments=[
            PaymentRequest(
                amount=payment.amount,
                method=payment.method,
                reference=payment.reference,
            )
            for payment in payload.payments
        ],
        customer_id=payload.customer_id,
        discount_amount=payload.discount_amount,
        operation_id=payload.operation_id,
        occurred_at=payload.occurred_at,
    )
    return SaleCreationResponseSchema(
        sale=SaleResponseSchema.from_entities(
            result.sale, items=result.items, payments=result.payments
        ),
        was_replayed=result.was_replayed,
    )


@router.get(
    "/sales",
    response_model=list[SaleSummaryResponseSchema],
    summary="List this business's sales",
)
async def list_sales(
    tenant_context: TenantContextDependency,
    service: SalesServiceDependency,
    limit: Annotated[
        int,
        Query(ge=1, le=MAXIMUM_SALE_LIST_LIMIT, description="How many sales to return."),
    ] = 100,
) -> list[SaleSummaryResponseSchema]:
    """Return the most recent sales, without their lines."""
    sales = await service.list_sales(tenant_context, limit=limit)
    return [SaleSummaryResponseSchema.from_entity(sale) for sale in sales]


@router.get(
    "/sales/{sale_id}",
    response_model=SaleResponseSchema,
    summary="Read one sale with its lines and payments",
)
async def get_sale(
    sale_id: UUID,
    tenant_context: TenantContextDependency,
    service: SalesServiceDependency,
) -> SaleResponseSchema:
    """Return one sale. A sale of another business is a 404, not a 403."""
    result = await service.get_sale(tenant_context, sale_id=sale_id)
    return SaleResponseSchema.from_entities(
        result.sale, items=result.items, payments=result.payments
    )


@router.post(
    "/sales/{sale_id}/cancel",
    response_model=SaleResponseSchema,
    summary="Cancel a sale, returning the stock and the money",
)
async def cancel_sale(
    sale_id: UUID,
    payload: SaleCancellationSchema,
    tenant_context: TenantContextDependency,
    service: SalesServiceDependency,
) -> SaleResponseSchema:
    """Cancel a sale.

    The stock comes back, the payments are marked refunded and the ledger records a refund.
    The sale is not deleted: the money and the goods both moved, and cancelling records that
    they moved back.
    """
    result = await service.cancel_sale(tenant_context, sale_id=sale_id, reason=payload.reason)
    return SaleResponseSchema.from_entities(
        result.sale, items=result.items, payments=result.payments
    )
