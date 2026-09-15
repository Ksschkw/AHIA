"""Report use cases: what a business asks about itself.

Named after the use case rather than an entity, because a report owns no table. It reads the sales,
the lines, the catalogue and the stock projection and answers a question; forcing one of those names
onto this file would tell a reader it owns that table, which it does not. It is the same exception
`auth_service`, `iam_seed_service` and `sync_service` take.

**Every report is a period, and the period is bounded.** "How much did we sell" without a start and
an end is a number that grows every day and can be compared with nothing, so a caller either states
a period or gets the default of the last seven days. The ceiling exists because a report is a screen
and an unbounded range is a query that one day takes a minute: ninety days is the widest window the
product offers, and anything longer is an export.

**The arithmetic happens in the database.** A month of sales summed in Python is the thing that
stops working on the busiest month, so the totals are `GROUP BY` queries in the entity's own
reader - and the one report that needs two tables at once goes through a read model written for
that purpose, because an entity repository never joins.

**Low stock is a comparison, not a query across tables.** The threshold lives on the product and the
quantity lives in the stock projection, and they belong to different entities. Rather than teach one
repository about the other, this service reads both and compares them, which is what the layer rule
asks for: the only place that knows two entities at once is a service.

**Reading a report needs `reports.read`.** It is the permission the specification defines for
"business reports, the ledger and audit history", and it is held by the owner and the manager. A
report is the business's own numbers: a salesperson sees what they sold, not what the business made.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Final
from uuid import UUID

from ahia.core.database import UnitOfWork
from ahia.core.errors import InvalidInputError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions.report_permissions import REPORTS_READ
from ahia.core.tenant_context import TenantContext
from ahia.crud import inventory_crud, product_crud, sale_crud
from ahia.crud.sale_performance_read_model import (
    DEFAULT_PERFORMANCE_LIMIT,
)
from ahia.crud.sale_performance_read_model import (
    performance_for_period as read_performance_for_period,
)

_REPORT_LOGGER_NAME: Final[str] = "ahia.services.report"

#: What a caller gets when they do not state a period. A week is long enough to see a trend and
#: short enough to answer instantly.
DEFAULT_PERIOD_DAYS: Final[int] = 7

#: The widest window a report offers. Beyond this, a caller wants an export rather than a screen.
MAXIMUM_PERIOD_DAYS: Final[int] = 90


@dataclass(frozen=True, slots=True)
class DailySales:
    """One day's trading."""

    sold_on: date
    revenue: Decimal
    sale_count: int


@dataclass(frozen=True, slots=True)
class DailySalesSummary:
    """What the business sold in a period, day by day and in total."""

    since: datetime
    until: datetime
    days: tuple[DailySales, ...]
    total_revenue: Decimal
    total_sales: int


@dataclass(frozen=True, slots=True)
class ProductPerformance:
    """What one product sold in a period."""

    product_name: str
    quantity_sold: Decimal
    revenue: Decimal


@dataclass(frozen=True, slots=True)
class LowStockProduct:
    """A product at or below the threshold its business set for it."""

    product_id: UUID
    product_name: str
    quantity_on_hand: Decimal
    low_stock_threshold: Decimal

    @property
    def is_out_of_stock(self) -> bool:
        return self.quantity_on_hand <= 0


class ReportService:
    """Report use cases."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._logger = (logger or get_logger(_REPORT_LOGGER_NAME)).bind(
            component="report_service", layer="service"
        )

    # ------------------------------------------------------------------
    # Sales
    # ------------------------------------------------------------------

    async def daily_sales_summary(
        self,
        tenant_context: TenantContext,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> DailySalesSummary:
        """Return the period's trading, day by day.

        Days with no sales are absent rather than zero: the caller knows the period it asked for,
        and inserting empty days here would be this layer deciding what a chart plots.
        """
        tenant_context.require_permission(
            REPORTS_READ,
            operation="read_daily_sales_summary",
            resource_type="report",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )
        period_start, period_end = self._period(since=since, until=until)

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            rows = await sale_crud.daily_totals(
                session, tenant_context.tenant_id, since=period_start, until=period_end
            )
            total_revenue, total_sales = await sale_crud.completed_total(
                session, tenant_context.tenant_id, since=period_start, until=period_end
            )

        return DailySalesSummary(
            since=period_start,
            until=period_end,
            days=tuple(
                DailySales(sold_on=sold_on, revenue=revenue, sale_count=count)
                for sold_on, revenue, count in rows
            ),
            total_revenue=total_revenue,
            total_sales=total_sales,
        )

    async def top_products(
        self,
        tenant_context: TenantContext,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = DEFAULT_PERFORMANCE_LIMIT,
    ) -> list[ProductPerformance]:
        """Return what sold most in the period, best first."""
        tenant_context.require_permission(
            REPORTS_READ,
            operation="read_product_performance",
            resource_type="report",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )
        period_start, period_end = self._period(since=since, until=until)

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            rows = await read_performance_for_period(
                unit_of_work.session_handle,
                tenant_context.tenant_id,
                since=period_start,
                until=period_end,
                limit=limit,
            )

        return [
            ProductPerformance(product_name=name, quantity_sold=quantity, revenue=revenue)
            for name, quantity, revenue in rows
        ]

    # ------------------------------------------------------------------
    # Stock
    # ------------------------------------------------------------------

    async def low_stock_products(
        self,
        tenant_context: TenantContext,
        *,
        limit: int = 50,
    ) -> list[LowStockProduct]:
        """Return the products at or below the threshold their business set.

        The threshold belongs to the product and the quantity to the stock projection, so the
        comparison happens here rather than in either reader: a repository that joined them would
        be a repository that knows another entity's table, which the layer rule forbids.

        A threshold of zero is the default and it means "tell me when it runs out", which is the
        alert nobody has to ask for. A product is reported when its quantity is at or below the
        threshold, so zero reports it when the shelf is empty rather than when it is nearly empty.
        """
        tenant_context.require_permission(
            REPORTS_READ,
            operation="read_low_stock_report",
            resource_type="report",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            products = await product_crud.list_for_tenant(session, tenant_context.tenant_id)
            levels = await inventory_crud.list_for_tenant(session, tenant_context.tenant_id)

        quantity_by_product = {level.product_id: level.quantity_on_hand for level in levels}
        low: list[LowStockProduct] = []
        for product in products:
            threshold = product.low_stock_threshold
            quantity = quantity_by_product.get(product.id, Decimal("0.000"))
            if quantity > threshold:
                continue
            low.append(
                LowStockProduct(
                    product_id=product.id,
                    product_name=product.name,
                    quantity_on_hand=quantity,
                    low_stock_threshold=threshold,
                )
            )

        # The emptiest shelf first, then the products closest to their threshold: the order a person
        # restocking wants to read, and derived from the numbers rather than from insertion order.
        low.sort(key=lambda entry: (entry.quantity_on_hand, entry.product_name))
        return low[:limit]

    # ------------------------------------------------------------------
    # The period
    # ------------------------------------------------------------------

    def _period(
        self, *, since: datetime | None, until: datetime | None
    ) -> tuple[datetime, datetime]:
        """Resolve a caller's period, or the default one, and refuse an impossible range."""
        today = datetime.now(UTC).date()
        period_end = until or datetime.combine(today + timedelta(days=1), time.min, tzinfo=UTC)
        period_start = since or datetime.combine(
            today - timedelta(days=DEFAULT_PERIOD_DAYS - 1), time.min, tzinfo=UTC
        )
        if period_end <= period_start:
            raise InvalidInputError(
                operation="read_report",
                entity="report",
                detail="the period ends before it starts; a report needs a window with length",
            )
        if period_end - period_start > timedelta(days=MAXIMUM_PERIOD_DAYS):
            raise InvalidInputError(
                operation="read_report",
                entity="report",
                detail=(
                    f"a report covers at most {MAXIMUM_PERIOD_DAYS} days; a wider range is an "
                    "export rather than a screen"
                ),
            )
        return period_start, period_end


__all__ = [
    "DailySales",
    "DailySalesSummary",
    "LowStockProduct",
    "ProductPerformance",
    "ReportService",
]
