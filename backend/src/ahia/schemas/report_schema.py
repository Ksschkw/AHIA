"""Transport contracts for reports.

**Money crosses as decimal strings and quantities as three-place strings.** The same single wire
format the rest of the product uses: a report is compared with a receipt, and a JSON number whose
float arithmetic shaved a kobo would make the two disagree in a way nobody can explain.

**A period is two timestamps, and the bounds are the service's.** The contract accepts what a caller
states and defaults nothing itself: defaults live where the rule lives, and a schema that invented a
default would be a second opinion about what "this week" means.

**The shapes carry no internal identifiers except where a caller needs one.** A low-stock row
carries its product identifier because the screen behind it links to the product; a daily-sales row
carries nothing but the day and the numbers, because a day is not a record this product stores.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ahia.models.entities.report_export_model import ExportStatus, ReportType
from ahia.schemas.money_format import money_text, quantity_text

ReportLimit = Annotated[int, Field(ge=1, le=200, description="How many rows to return.")]


class DailySalesSchema(BaseModel):
    """One day's trading."""

    model_config = ConfigDict(extra="forbid")

    sold_on: date
    revenue: str
    sale_count: int

    @classmethod
    def from_projection(cls, day: Any) -> DailySalesSchema:
        return cls(
            sold_on=day.sold_on,
            revenue=money_text(Decimal(day.revenue)),
            sale_count=day.sale_count,
        )


class DailySalesSummarySchema(BaseModel):
    """A period's trading, day by day and in total.

    Days with no sales are absent rather than zero: the caller knows the period it asked for, and
    filling gaps here would be the API deciding what a chart draws.
    """

    model_config = ConfigDict(extra="forbid")

    since: datetime
    until: datetime
    total_revenue: str
    total_sales: int
    days: list[DailySalesSchema]

    @classmethod
    def from_projection(cls, summary: Any) -> DailySalesSummarySchema:
        return cls(
            since=summary.since,
            until=summary.until,
            total_revenue=money_text(Decimal(summary.total_revenue)),
            total_sales=summary.total_sales,
            days=[DailySalesSchema.from_projection(day) for day in summary.days],
        )


class ProductPerformanceSchema(BaseModel):
    """What one product sold in a period."""

    model_config = ConfigDict(extra="forbid")

    product_name: str
    quantity_sold: str
    revenue: str

    @classmethod
    def from_projection(cls, entry: Any) -> ProductPerformanceSchema:
        return cls(
            product_name=entry.product_name,
            quantity_sold=quantity_text(Decimal(entry.quantity_sold)),
            revenue=money_text(Decimal(entry.revenue)),
        )


class LowStockProductSchema(BaseModel):
    """A product at or below the threshold its business set."""

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    product_name: str
    quantity_on_hand: str
    low_stock_threshold: str
    is_out_of_stock: bool

    @classmethod
    def from_projection(cls, entry: Any) -> LowStockProductSchema:
        return cls(
            product_id=entry.product_id,
            product_name=entry.product_name,
            quantity_on_hand=quantity_text(Decimal(entry.quantity_on_hand)),
            low_stock_threshold=quantity_text(Decimal(entry.low_stock_threshold)),
            is_out_of_stock=entry.is_out_of_stock,
        )


class ReportExportRequestSchema(BaseModel):
    """A request to write a report out as a file.

    The period is optional for the same reason it is optional on a read, and the bounds are the
    service's: a schema that defaulted one would be a second opinion about what "this week" means.
    """

    model_config = ConfigDict(extra="forbid")

    report_type: ReportType
    since: datetime | None = None
    until: datetime | None = None
    lifetime_days: Annotated[
        int, Field(ge=1, le=365, description="How long the share link lasts.")
    ] = 30


class ReportExportResponseSchema(BaseModel):
    """A written-out report, and the link that opens it.

    `token` is the only copy: the server stores a digest, so a client that loses the link asks for a
    new export rather than expecting the server to re-show it.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    report_type: ReportType
    status: ExportStatus
    row_count: int
    size_bytes: int
    period_since: datetime | None
    period_until: datetime | None
    created_at: datetime
    # The link that opens this export, present on the response that minted it and absent from a
    # listing: the server keeps only a digest of the token, so a listing has nothing to show.
    share_link_id: UUID | None
    share_token: str | None
    public_path: str | None

    @classmethod
    def from_projection(cls, issued: Any) -> ReportExportResponseSchema:
        return cls(
            id=issued.export.id,
            report_type=issued.export.report_type,
            status=issued.export.status,
            row_count=issued.export.row_count,
            size_bytes=issued.export.size_bytes,
            period_since=issued.export.period_since,
            period_until=issued.export.period_until,
            created_at=issued.export.created_at,
            share_link_id=issued.share_link_id,
            share_token=issued.token,
            public_path=issued.public_path,
        )
