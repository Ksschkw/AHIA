"""HTTP transport for reports.

Three read routes on `/tenants/{tenant_id}/reports`, and no write route at all: a report is a
question, and nothing in this product lets a client change the answer.

**The period is optional and the bounds are the service's.** A caller that omits `since` and `until`
gets the last seven days, which is long enough to see a trend and short enough to answer instantly;
a caller that asks for more than ninety days is refused, because a report is a screen and a wider
range is an export. Both rules live in `ReportService`, not here: a transport handler that defaulted
a period would be a second opinion about what "this week" means, and a CLI or a scheduled job asking
the same question would get a different answer.

**Authorization is `reports.read`, checked in the service.** A report is the business's own numbers,
and the owner and the manager hold the permission; a salesperson sees what they sold through the
sales endpoints and not what the business made.

Every handler parses, calls one service method and shapes the response.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query, Request

from ahia.core.tenant_context import TenantContext
from ahia.routers.tenant_router import require_tenant_context
from ahia.schemas.report_schema import (
    DailySalesSummarySchema,
    LowStockProductSchema,
    ProductPerformanceSchema,
    ReportExportRequestSchema,
    ReportExportResponseSchema,
    ReportLimit,
)
from ahia.services.report_service import ReportService

_TENANT_SCOPE_PREFIX: Final[str] = "/tenants/{tenant_id}"

router = APIRouter(prefix=_TENANT_SCOPE_PREFIX, tags=["reports"])


def get_report_service(request: Request) -> ReportService:
    """Return the report service for this request."""
    service: ReportService = request.app.state.container.report_service
    return service


ReportServiceDependency = Annotated[ReportService, Depends(get_report_service)]
TenantContextDependency = Annotated[TenantContext, Depends(require_tenant_context)]


@router.get(
    "/reports/daily-sales",
    response_model=DailySalesSummarySchema,
    summary="What the business sold, day by day",
)
async def read_daily_sales(
    tenant_context: TenantContextDependency,
    service: ReportServiceDependency,
    since: Annotated[
        datetime | None,
        Query(description="Start of the period, inclusive. Defaults to seven days ago."),
    ] = None,
    until: Annotated[
        datetime | None,
        Query(description="End of the period, exclusive. Defaults to the end of today."),
    ] = None,
) -> DailySalesSummarySchema:
    """Return the period's trading, day by day and in total.

    Cancelled sales are excluded: a cancelled sale is money that came back, and the receipt, the
    lines and the ledger still hold its story.
    """
    summary = await service.daily_sales_summary(tenant_context, since=since, until=until)
    return DailySalesSummarySchema.from_projection(summary)


@router.get(
    "/reports/top-products",
    response_model=list[ProductPerformanceSchema],
    summary="What sold most in a period",
)
async def read_top_products(
    tenant_context: TenantContextDependency,
    service: ReportServiceDependency,
    since: Annotated[datetime | None, Query(description="Start of the period, inclusive.")] = None,
    until: Annotated[datetime | None, Query(description="End of the period, exclusive.")] = None,
    limit: Annotated[ReportLimit, Query(description="How many products to return.")] = 10,
) -> list[ProductPerformanceSchema]:
    """Return the products sold most, best first.

    Grouped by the name the receipt printed: a product renamed last week keeps one line of history
    rather than two.
    """
    performance = await service.top_products(tenant_context, since=since, until=until, limit=limit)
    return [ProductPerformanceSchema.from_projection(entry) for entry in performance]


@router.get(
    "/reports/low-stock",
    response_model=list[LowStockProductSchema],
    summary="What is running out",
)
async def read_low_stock(
    tenant_context: TenantContextDependency,
    service: ReportServiceDependency,
    limit: Annotated[ReportLimit, Query(description="How many products to return.")] = 50,
) -> list[LowStockProductSchema]:
    """Return the products at or below the threshold their business set.

    A threshold of zero, which is the default, reports a product when the shelf is empty: the alert
    nobody has to ask for. The emptiest first, because that is the order a person restocking reads.
    """
    low_stock = await service.low_stock_products(tenant_context, limit=limit)
    return [LowStockProductSchema.from_projection(entry) for entry in low_stock]


@router.post(
    "/reports/export",
    response_model=ReportExportResponseSchema,
    status_code=201,
    summary="Write a report out as a file and share it",
)
async def export_report(
    payload: ReportExportRequestSchema,
    tenant_context: TenantContextDependency,
    service: ReportServiceDependency,
) -> ReportExportResponseSchema:
    """Write the report out, store it, and return the link that opens it.

    A failed upload is recorded and reported rather than raised: the export exists, its status says
    what happened, and the client can offer to retry instead of showing an error that says nothing.
    """
    issued = await service.export_report(
        tenant_context,
        report_type=payload.report_type,
        since=payload.since,
        until=payload.until,
        lifetime=timedelta(days=payload.lifetime_days),
    )
    return ReportExportResponseSchema.from_projection(issued)


@router.get(
    "/reports/exports",
    response_model=list[ReportExportResponseSchema],
    summary="What this business has exported",
)
async def list_report_exports(
    tenant_context: TenantContextDependency,
    service: ReportServiceDependency,
    limit: Annotated[ReportLimit, Query(description="How many exports to return.")] = 20,
) -> list[ReportExportResponseSchema]:
    """Return the business's exports.

    The share token is absent here, and that is not a formatting choice: the server does not
    have it. A business that needs a new link exports again, which also produces a fresh artifact
    rather than reviving an address somebody may already hold.
    """
    exports = await service.list_exports(tenant_context, limit=limit)
    return [
        ReportExportResponseSchema(
            id=export.id,
            report_type=export.report_type,
            status=export.status,
            row_count=export.row_count,
            size_bytes=export.size_bytes,
            period_since=export.period_since,
            period_until=export.period_until,
            created_at=export.created_at,
            # Nothing about the link, because there is nothing to show: the server keeps a digest
            # and not a token, so a business that needs a link exports again - which also produces
            # a fresh artifact rather than reviving an address somebody may already hold.
            share_link_id=None,
            share_token=None,
            public_path=None,
        )
        for export in exports
    ]
