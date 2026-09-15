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
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.errors import InvalidInputError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions.report_permissions import REPORTS_READ
from ahia.core.ports.storage_port import (
    StoragePort,
    StorageUploadRequest,
    compute_sha256,
    key_belongs_to_tenant,
)
from ahia.core.tenant_context import TenantContext
from ahia.crud import inventory_crud, product_crud, report_export_crud, sale_crud
from ahia.crud.sale_performance_read_model import (
    DEFAULT_PERFORMANCE_LIMIT,
    revenue_by_product_for_period,
)
from ahia.crud.sale_performance_read_model import (
    performance_for_period as read_performance_for_period,
)
from ahia.models.entities.audit_event_model import AuditOutcome
from ahia.models.entities.report_export_model import (
    ExportStatus,
    ReportExportModel,
    ReportType,
)
from ahia.models.entities.share_link_model import DEFAULT_LIFETIME
from ahia.schemas.money_format import money_text, quantity_text
from ahia.services.audit_event_service import AuditEventService
from ahia.services.share_link_service import ShareLinkService

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


@dataclass(frozen=True, slots=True)
class IssuedReportExport:
    """A report that was written out, and the link that opens it.

    The link is here rather than fetched separately because an export nobody can open is not an
    export: a business exports in order to hand the file to somebody, and asking for a second call
    to learn the address would be a flow that can be left half-finished.

    The link's own fields are flattened rather than nested, because the token is the one value a
    caller cannot ask for again - a second `link.link.token` in the response builder is the kind of
    indirection that turns into `AttributeError` in production, which is exactly how this class
    started.
    """

    export: ReportExportModel
    share_link_id: UUID
    token: str

    @property
    def public_path(self) -> str:
        return f"/share/report/{self.token}"

    @property
    def is_available(self) -> bool:
        return self.export.is_available()


class ReportService:
    """Report use cases."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        storage: StoragePort,
        share_link_service: ShareLinkService,
        audit_event_service: AuditEventService,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._storage = storage
        self._share_links = share_link_service
        self._audit = audit_event_service
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
    # Exporting
    # ------------------------------------------------------------------

    async def export_report(
        self,
        tenant_context: TenantContext,
        *,
        report_type: ReportType,
        since: datetime | None = None,
        until: datetime | None = None,
        lifetime: timedelta = DEFAULT_LIFETIME,
    ) -> IssuedReportExport:
        """Write a report out as a CSV, store it, and hand back a link that opens it.

        The upload happens before the row is written and the row is written either way: a failed
        upload is recorded with its reason, because a business that asks for an export and receives
        nothing needs to be able to tell a failure from a request that was never made.

        The permission is checked once, here, and the share link inherits it: sharing a report needs
        `reports.read` because reading one does.
        """
        tenant_context.require_permission(
            REPORTS_READ,
            operation="export_report",
            resource_type="report",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )

        period_start: datetime | None = None
        period_end: datetime | None = None
        if report_type is not ReportType.LOW_STOCK:
            # A stock report is about a moment; the other two are about a range, and the range is
            # resolved through the same bounds a read uses so an export and a screen agree.
            period_start, period_end = self._period(since=since, until=until)

        rows = await self._report_rows(
            tenant_context,
            report_type=report_type,
            since=period_start,
            until=period_end,
        )
        content = _csv_document(report_type=report_type, rows=rows)

        export_id = uuid4()
        now = datetime.now(UTC)
        key = _object_key(
            tenant_id=tenant_context.tenant_id, report_type=report_type, export_id=export_id
        )
        # The key is built here from server-side identifiers, and this asserts the rule the storage
        # port will enforce anyway: an object lives under its business's prefix, or it is a
        # cross-tenant reference. A failure here names the rule rather than the provider.
        if not key_belongs_to_tenant(key, str(tenant_context.tenant_id)):
            raise InvalidInputError(
                operation="export_report",
                entity="report_export",
                detail="the built object key is not under this business's prefix",
            )
        checksum = compute_sha256(content)
        stored = await self._storage.upload(
            StorageUploadRequest(
                key=key,
                content=content,
                mime_type="text/csv",
                tenant_id=str(tenant_context.tenant_id),
                filename=_filename(report_type=report_type, export_id=export_id),
                metadata={"report_type": report_type.value},
            )
        )

        if stored.is_degraded:
            record = ReportExportModel.failed(
                export_id=export_id,
                tenant_id=tenant_context.tenant_id,
                report_type=report_type,
                storage_provider=stored.provider,
                storage_key=stored.key,
                checksum_sha256=checksum,
                now=now,
                reason=stored.degradation_reason or "the object store refused the upload",
                created_by_user_id=tenant_context.user_id,
                period_since=period_start,
                period_until=period_end,
            )
        else:
            record = ReportExportModel.ready(
                export_id=export_id,
                tenant_id=tenant_context.tenant_id,
                report_type=report_type,
                storage_provider=stored.provider,
                storage_key=stored.key,
                size_bytes=stored.size_bytes or len(content),
                checksum_sha256=checksum,
                row_count=len(rows),
                now=now,
                created_by_user_id=tenant_context.user_id,
                period_since=period_start,
                period_until=period_end,
            )

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            stored_record = await report_export_crud.create(session, record)
            # Exporting the business's numbers is worth a trail entry of its own: it is the action
            # that moves them out of the product, and "who exported what, and when" is the question
            # asked after a file turns up somewhere it should not be. A failed export is recorded as
            # a failure, because "somebody tried and it did not work" is a different fact.
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="export_report",
                entity_type="report_export",
                entity_id=stored_record.id,
                now=now,
                outcome=(
                    AuditOutcome.FAILED
                    if stored_record.status is ExportStatus.FAILED
                    else AuditOutcome.SUCCEEDED
                ),
                detail=stored_record.describe_for_audit(),
            )
            await unit_of_work.commit()

        issued = await self._share_links.share_report(
            tenant_context, report_export_id=stored_record.id, lifetime=lifetime
        )
        self._logger.info(
            "report_exported",
            **stored_record.describe_for_audit(),
            actor_id=str(tenant_context.user_id),
        )
        return IssuedReportExport(
            export=stored_record,
            share_link_id=issued.link.id,
            token=issued.token,
        )

    async def list_exports(
        self, tenant_context: TenantContext, *, limit: int = 50
    ) -> list[ReportExportModel]:
        """Return the business's exports, most recent first."""
        tenant_context.require_permission(
            REPORTS_READ,
            operation="list_report_exports",
            resource_type="report",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await report_export_crud.list_for_tenant(
                unit_of_work.session_handle, tenant_context.tenant_id, limit=limit
            )

    async def _report_rows(
        self,
        tenant_context: TenantContext,
        *,
        report_type: ReportType,
        since: datetime | None,
        until: datetime | None,
    ) -> list[list[str]]:
        """Return the rows of one report as text, ready for a CSV.

        The values are rendered through the same helpers the API uses, so a number in an export and
        the same number on a screen are the same string - which is the whole reason a business
        exports rather than reads.
        """
        unit_of_work = self._unit_of_work_factory()
        if report_type is ReportType.DAILY_SALES:
            summary = await self.daily_sales_summary(tenant_context, since=since, until=until)
            return [
                [
                    day.sold_on.isoformat(),
                    money_text(day.revenue),
                    str(day.sale_count),
                ]
                for day in summary.days
            ]
        if report_type is ReportType.PRODUCT_PERFORMANCE:
            assert since is not None and until is not None
            async with unit_of_work:
                rows = await revenue_by_product_for_period(
                    unit_of_work.session_handle,
                    tenant_context.tenant_id,
                    since=since,
                    until=until,
                )
            return [
                [name, quantity_text(quantity), money_text(revenue)]
                for name, quantity, revenue in rows
            ]
        low_stock = await self.low_stock_products(tenant_context, limit=200)
        return [
            [
                entry.product_name,
                quantity_text(entry.quantity_on_hand),
                quantity_text(entry.low_stock_threshold),
                "yes" if entry.is_out_of_stock else "no",
            ]
            for entry in low_stock
        ]

    async def low_stock_for_tenant(
        self, *, tenant_id: UUID, limit: int = 200
    ) -> list[LowStockProduct]:
        """Return the low-stock products of one business, for a caller with no identity.

        The scheduled evaluator is a system caller: it has no user, no membership and no context,
        and
        it is the only legitimate one. Rather than let it construct a context that pretends to be
        somebody - which would put a person's name on an alert nobody's action produced - the system
        path is stated here by name, and it takes a tenant and nothing else. It is deliberately not
        reachable from the API: there is no route that calls it, and a route added later would have
        to
        say what authorized it.

        The comparison itself is unchanged: this is the same code the report screen runs.
        """
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            products = await product_crud.list_for_tenant(session, tenant_id)
            levels = await inventory_crud.list_for_tenant(session, tenant_id)

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

#: The one line a CSV needs to be read by a person: a header, and the columns the rows carry.
_CSV_HEADERS: Final[dict[ReportType, tuple[str, ...]]] = {
    ReportType.DAILY_SALES: ("sold_on", "revenue", "sale_count"),
    ReportType.PRODUCT_PERFORMANCE: ("product_name", "quantity_sold", "revenue"),
    ReportType.LOW_STOCK: (
        "product_name",
        "quantity_on_hand",
        "low_stock_threshold",
        "out_of_stock",
    ),
}

#: Characters a spreadsheet treats as the start of a formula. A product called `=cmd|...` is a
#: product, not an instruction, and an export that executes one is an export that ran a customer's
#: data as code on the machine of whoever opened it.
_FORMULA_PREFIXES: Final[tuple[str, ...]] = ("=", "+", "-", "@", "\t", "\r")


def _csv_document(*, report_type: ReportType, rows: list[list[str]]) -> bytes:
    """Render a report as a CSV, neutralising anything a spreadsheet would execute."""
    header = _CSV_HEADERS[report_type]
    lines = [_csv_line(list(header))]
    lines.extend(_csv_line(row) for row in rows)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _csv_line(fields: list[str]) -> str:
    return ",".join(_csv_field(field) for field in fields)


def _csv_field(value: str) -> str:
    """Quote one field, and defuse a value that a spreadsheet would treat as a formula.

    RFC 4180 quoting handles the commas, the quotes and the newlines. It does not handle the
    spreadsheet: a field beginning `=` or `+` is executed when the file is opened, so a leading
    apostrophe is inserted and the cell reads as text. Both matter, and only one of them is about
    commas.
    """
    text = value
    if text.startswith(_FORMULA_PREFIXES):
        text = "'" + text
    if any(character in text for character in (",", '"', "\n", "\r")):
        return '"' + text.replace('"', '""') + '"'
    return text


def _object_key(*, tenant_id: UUID, report_type: ReportType, export_id: UUID) -> str:
    """Build the key from server-side identifiers, inside the business's prefix."""
    return f"tenants/{tenant_id}/reports/{report_type.value.lower()}/{export_id.hex}.csv"


def _filename(*, report_type: ReportType, export_id: UUID) -> str:
    return f"{report_type.value.lower()}_{export_id.hex[:8]}.csv"
