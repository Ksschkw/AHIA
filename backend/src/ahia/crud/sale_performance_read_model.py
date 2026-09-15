"""A read model for what sold: the one place two tables are joined for a report.

A read model rather than a repository, and the distinction is the whole reason this file exists. An
entity repository touches one entity's storage and never joins, so that the only place that knows
about two entities at once is a service - that rule is what keeps a change to one table from
requiring a reader of another to be re-read. A report is the case where the database should do the
composing anyway: summing a month of sale lines in Python is the thing that stops working on the
busiest month, and the join is the same fact a service would assemble, computed where the rows are.

It is named for what it answers rather than for a table, because it owns no table. It reads two, and
writes neither, and a test asserts that: no insert, update or delete function exists in this module.

The grouping is by the name snapshot
    `sale_items.product_name_snapshot` is what the customer's receipt said. Grouping by the
    product identifier would split a renamed product's history in two, and grouping by the current
    name would rewrite it; the snapshot is the only value that was true at the time of each sale.

Only completed sales count
    A cancelled sale's goods came back. The lines are still there, because the money and the stock
    moved and moved back, and the revenue figure is what the business kept.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ahia.crud.sale_crud import SaleRecord
from ahia.crud.sale_item_crud import SaleItemRecord
from ahia.models.entities.sale_model import SaleStatus

#: How many products a "what sells most" report returns. A report is a screen, and a screen shows
#: the top of a list; the rest is an export.
DEFAULT_PERFORMANCE_LIMIT: Final[int] = 10


async def performance_for_period(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    since: datetime,
    until: datetime,
    limit: int = DEFAULT_PERFORMANCE_LIMIT,
) -> list[tuple[str, Decimal, Decimal]]:
    """Return the products sold most in a period: name, quantity and revenue, best first."""
    revenue = func.sum(SaleItemRecord.line_total)
    quantity = func.sum(SaleItemRecord.quantity)
    result = await session.execute(
        select(
            SaleItemRecord.product_name_snapshot,
            quantity.label("quantity"),
            revenue.label("revenue"),
        )
        .join(SaleRecord, SaleRecord.id == SaleItemRecord.sale_id)
        .where(SaleItemRecord.tenant_id == tenant_id)
        .where(SaleRecord.tenant_id == tenant_id)
        .where(SaleRecord.status == SaleStatus.COMPLETED.value)
        .where(SaleRecord.occurred_at >= since)
        .where(SaleRecord.occurred_at < until)
        .group_by(SaleItemRecord.product_name_snapshot)
        .order_by(revenue.desc(), SaleItemRecord.product_name_snapshot)
        .limit(limit)
    )
    return [
        (str(row.product_name_snapshot), Decimal(row.quantity), Decimal(row.revenue))
        for row in result.all()
    ]


async def revenue_by_product_for_period(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    since: datetime,
    until: datetime,
) -> list[tuple[str, Decimal, Decimal]]:
    """Return every product that sold in a period, for an export rather than a screen."""
    return await performance_for_period(session, tenant_id, since=since, until=until, limit=10_000)
