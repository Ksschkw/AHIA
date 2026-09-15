"""The low-stock evaluator: what a scheduled run does, and why it is a job rather than a rule.

**The rule is not here.** What counts as low is `ReportService.low_stock_products`, which is the
same
call the report screen makes: the threshold on the product, the quantity in the stock projection,
and
the comparison between them. This file decides *when* to ask and *who* to tell. Duplicating the rule
for the job would give the product two definitions of "low", and the one on a screen and the one in
an
alert would eventually disagree - which is the failure a business would notice last.

**A run is idempotent per day, and that is what the dedupe key is for.** The evaluator builds a key
from the product and the day it is evaluating for, so running it twice in one day raises one alert:
the second run finds the first, counts it as skipped, and reports that. A key built from the
*moment*
instead would raise a second alert every hour, which is how a person learns to ignore alerts.

**Who is told: the people who can act on it.** The owner and the managers of the business - the
roles
that hold `reports.read`, which is the same authority the report itself needs. A salesperson is not
told that the shelf is thin: they cannot order stock, and an inbox full of things you cannot act on
is
an inbox you stop reading.

**It runs per tenant, and a failure in one business does not stop the others.** The evaluator
returns a
report of what it did per business rather than raising: a scheduled job that dies on the third
tenant
leaves the fourth through the thousandth unevaluated, and nobody knows.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Final
from uuid import UUID

from ahia.core.database import UnitOfWork
from ahia.core.logging import StructuredLogger, get_logger
from ahia.crud import tenant_crud, tenant_membership_crud
from ahia.models.entities.notification_model import NotificationType
from ahia.models.entities.tenant_membership_model import MembershipStatus
from ahia.services.notification_service import NotificationRequest, NotificationService
from ahia.services.report_service import LowStockProduct, ReportService

_LOW_STOCK_LOGGER_NAME: Final[str] = "ahia.jobs.low_stock"

#: The roles that can act on a stock alert. Named here rather than in the database query because
#: it is a product decision: the people who order stock.
ROLES_TOLD_ABOUT_STOCK: Final[frozenset[str]] = frozenset({"OWNER", "MANAGER"})


@dataclass(frozen=True, slots=True)
class TenantEvaluation:
    """What one business's evaluation produced."""

    tenant_id: UUID
    evaluated_on: date
    low_stock_products: int
    notifications_raised: int
    notifications_skipped: int
    recipients: int


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """What a run produced, business by business."""

    evaluated_on: date
    tenants: list[TenantEvaluation] = field(default_factory=list)
    failures: list[tuple[UUID, str]] = field(default_factory=list)

    @property
    def raised_count(self) -> int:
        return sum(tenant.notifications_raised for tenant in self.tenants)

    @property
    def skipped_count(self) -> int:
        return sum(tenant.notifications_skipped for tenant in self.tenants)


class LowStockAlertEvaluator:
    """Evaluates low stock for one business, or for every business."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        report_service: ReportService,
        notification_service: NotificationService,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._reports = report_service
        self._notifications = notification_service
        self._logger = (logger or get_logger(_LOW_STOCK_LOGGER_NAME)).bind(
            component="low_stock_evaluator", layer="job"
        )

    async def evaluate_all(self, *, today: date | None = None) -> EvaluationReport:
        """Evaluate every active business, and report what happened rather than raising.

        One business's failure is recorded and the run continues: a job that stops at the third
        tenant
        leaves the rest unevaluated and nobody knows which ones.
        """
        evaluated_on = today or datetime.now(UTC).date()
        report = EvaluationReport(evaluated_on=evaluated_on)
        for tenant_id in await self._active_tenant_ids():
            try:
                evaluation = await self.evaluate_tenant(tenant_id=tenant_id, today=evaluated_on)
            except Exception as failure:  # noqa: BLE001 - a run must survive one tenant
                # Logged with the business and the reason, and reported: the alternative is a job
                # that is silently partial, which is worse than one that fails loudly.
                self._logger.error(
                    "low_stock_evaluation_failed",
                    tenant_id=str(tenant_id),
                    evaluated_on=evaluated_on.isoformat(),
                    error_type=type(failure).__name__,
                )
                report.failures.append((tenant_id, type(failure).__name__))
                continue
            report.tenants.append(evaluation)
        self._logger.info(
            "low_stock_evaluation_completed",
            evaluated_on=evaluated_on.isoformat(),
            tenants_evaluated=len(report.tenants),
            tenants_failed=len(report.failures),
            notifications_raised=report.raised_count,
            notifications_skipped=report.skipped_count,
        )
        return report

    async def evaluate_tenant(
        self, *, tenant_id: UUID, today: date | None = None
    ) -> TenantEvaluation:
        """Evaluate one business and tell the people who can act."""
        evaluated_on = today or datetime.now(UTC).date()
        low_stock = await self._reports.low_stock_for_tenant(tenant_id=tenant_id, limit=200)
        recipients = await self._alert_recipients(tenant_id)
        if not low_stock or not recipients:
            return TenantEvaluation(
                tenant_id=tenant_id,
                evaluated_on=evaluated_on,
                low_stock_products=len(low_stock),
                notifications_raised=0,
                notifications_skipped=0,
                recipients=len(recipients),
            )

        raised = 0
        skipped = 0
        for recipient_user_id in recipients:
            outcome = await self._notifications.raise_many(
                tenant_id=tenant_id,
                recipient_user_id=recipient_user_id,
                notifications=[
                    _alert_for(entry, tenant_id=tenant_id, evaluated_on=evaluated_on)
                    for entry in low_stock
                ],
            )
            raised += outcome.raised_count
            skipped += outcome.skipped_duplicates
        return TenantEvaluation(
            tenant_id=tenant_id,
            evaluated_on=evaluated_on,
            low_stock_products=len(low_stock),
            notifications_raised=raised,
            notifications_skipped=skipped,
            recipients=len(recipients),
        )

    async def _active_tenant_ids(self) -> list[UUID]:
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            tenants = await tenant_crud.list_active(unit_of_work.session_handle)
        return [tenant.id for tenant in tenants]

    async def _alert_recipients(self, tenant_id: UUID) -> list[UUID]:
        """Return the memberships that hold a role which can act on a stock alert."""
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            memberships = await tenant_membership_crud.list_for_tenant(
                unit_of_work.session_handle, tenant_id
            )
        return [
            membership.user_id
            for membership in memberships
            if membership.role_name in ROLES_TOLD_ABOUT_STOCK
            and membership.status is MembershipStatus.ACTIVE
        ]


def _alert_for(
    entry: LowStockProduct, *, tenant_id: UUID, evaluated_on: date
) -> NotificationRequest:
    """Build the alert for one product.

    The dedupe key names the product and the day: one alert per product per day, however often the
    evaluator runs. It is the product's identifier rather than its name, so renaming a product does
    not raise a second alert for the same shelf.
    """
    is_out = entry.is_out_of_stock
    return NotificationRequest(
        notification_type=(NotificationType.STOCK_OUT if is_out else NotificationType.LOW_STOCK),
        title=(
            f"{entry.product_name} is out of stock"
            if is_out
            else f"{entry.product_name} is low on stock"
        ),
        body=(
            f"{entry.quantity_on_hand} left, against a threshold of {entry.low_stock_threshold}."
        ),
        entity_type="product",
        entity_id=entry.product_id,
        dedupe_key=(f"low_stock:{entry.product_id}:{evaluated_on.isoformat()}"),
    )


__all__ = [
    "ROLES_TOLD_ABOUT_STOCK",
    "EvaluationReport",
    "LowStockAlertEvaluator",
    "TenantEvaluation",
]
