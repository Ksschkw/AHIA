"""The scheduled low-stock evaluation.

    python -m ahia.jobs.low_stock_alerts

Run it hourly or daily; the dedupe key makes the frequency a cost decision rather than a correctness
one, and the alerts are one per product per day however often it runs.

The exit code is the contract with whatever runs it: zero when every business was evaluated, one
when
at least one failed or the run could not start. A scheduler that ignores a non-zero exit is a
scheduler that lets a broken job look healthy, and the alerts would simply stop arriving.

Nothing here decides what "low" means. The evaluator calls `ReportService`, which is the same code
the
report screen calls, and this file only builds the dependencies, runs it, and prints what happened.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Final

from ahia.bootstrap import (
    ApplicationContainer,
    build_application_container,
    dispose_application_container,
)
from ahia.core.config import load_settings
from ahia.services.low_stock_alert_service import (
    EvaluationReport,
    LowStockAlertEvaluator,
)


def build_evaluator() -> tuple[LowStockAlertEvaluator, ApplicationContainer]:
    """Build the evaluator and the container it came from.

    The container is returned as well so the caller can dispose of the connection pool: a job that
    exits without closing its engine leaves the database holding a connection until the socket times
    out, and a job that runs every hour leaks one every hour.
    """
    settings = load_settings()
    container = build_application_container(settings)
    evaluator = LowStockAlertEvaluator(
        unit_of_work_factory=container.database.unit_of_work_factory(),
        report_service=container.report_service,
        notification_service=container.notification_service,
        logger=container.logger,
    )
    return evaluator, container


def render(report: EvaluationReport) -> str:
    """Return the ASCII summary a person reads in a scheduler's output.

    Plain tags rather than decoration, for the same reason every other status line in this
    repository
    is plain: the codebase forbids emoji and the log is read in a terminal.
    """
    lines = [
        f"[OK] low-stock evaluation for {report.evaluated_on.isoformat()}",
        f"     businesses evaluated: {len(report.tenants)}",
        f"     notifications raised: {report.raised_count}",
        f"     already raised today: {report.skipped_count}",
    ]
    if report.failures:
        lines.append(f"[FAIL] businesses that could not be evaluated: {len(report.failures)}")
        lines.extend(f"     {tenant_id} ({reason})" for tenant_id, reason in report.failures)
    return "\n".join(lines)


async def run() -> int:
    """Run one evaluation and return the exit code."""
    evaluator, container = build_evaluator()
    try:
        report = await evaluator.evaluate_all()
    finally:
        await dispose_application_container(container)
    print(render(report))
    return 1 if report.failures else 0


def main(argv: list[str] | None = None) -> int:
    """Entry point. Takes no arguments: a job that needs them is a job with a hidden interface."""
    arguments: Final[list[str]] = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        print(f"[FAIL] this job takes no arguments, got: {' '.join(arguments)}")
        return 2
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
