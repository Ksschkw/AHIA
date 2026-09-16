"""A load smoke test for the sale path.

    python scripts/load_smoke_sale.py --sales 200 --concurrency 20

**What this measures, and what it does not.** The requests go through the real ASGI application:
the real middleware stack, the real authorization, the real service, the real database, over an
in-process transport instead of a socket. That removes the network and the load balancer from the
measurement, which is what makes the number comparable between runs, and it also means the number
is *not* a capacity figure for a deployment. It is a smoke test: it says the sale path holds under
concurrent use with the database on the same machine, and it produces a number a later change can be
compared against.

**Every request is a real sale.** A business is registered, a product created and stocked, and then
N sales are recorded concurrently, each with its own operation identifier. A failing request is
counted and reported with its status and correlation ID, and the process exits non-zero: a smoke
test that reports a number while requests were failing hides the outage it was run to find.

**The rate limiter is configured high for the run.** The default write limit exists to protect the
service and it works; measuring it is not this script's job, and a run that spends its budget on
429s measures nothing. The limits used are printed in the summary, so the number is never read as
though the defaults had applied.

**The database is a local one.** The schema is created from the models if it is missing, and the
rows the run creates stay there. Never point this at a database whose data matters.

**No credential is committed.** The signing secret, the token pepper, the storage keys and the
metrics token are generated per run, and the account password is generated too, because the point of
the script is a throwaway business rather than a reusable login.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.metrics import normalise_route
from ahia.crud.table_registry import import_all_record_modules
from ahia.main import create_application

#: The local test database. Overridable with `--database-url`, because a smoke test pointed at the
#: wrong database is either useless or destructive.
DEFAULT_DATABASE_URL: Final[str] = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)

#: Generated per run: the account is created by this script and used only by this script.
ACCOUNT_PASSWORD: Final[str] = secrets.token_urlsafe(24)
METRICS_TOKEN: Final[str] = secrets.token_urlsafe(32)

STOCK_QUANTITY: Final[str] = "900000.000"
SALE_QUANTITY: Final[str] = "2.000"
SELLING_PRICE: Final[str] = "45000.00"
PAYMENT_AMOUNT: Final[str] = "90000.00"
SALE_ROUTE_TEMPLATE: Final[str] = "/api/v1/tenants/{tenant_id}/sales"

#: The rate limits the run uses, reported in the summary so the numbers can never be misread as
#: having been produced under the defaults in `core/config.py`. The write limit is at its configured
#: ceiling: a local run is far below it, and a limit below the run's own throughput would turn this
#: into a measurement of the limiter.
LOAD_RATE_LIMITS: Final[dict[str, Any]] = {
    "rate_limit_auth_per_minute": 1_000,
    "rate_limit_write_per_minute": 10_000,
    "rate_limit_global_per_minute": 100_000,
    "rate_limit_public_read_per_minute": 100_000,
    "rate_limit_password_reset_per_hour": 1_000,
}


@dataclass(frozen=True, slots=True)
class Arguments:
    """The command line, parsed and typed."""

    sales: int
    concurrency: int
    warmup: int
    database_url: str


@dataclass(slots=True)
class Observation:
    """One sale request's outcome."""

    duration_seconds: float
    status_code: int
    correlation_id: str | None


@dataclass(slots=True)
class Summary:
    """What the run measured."""

    requested: int
    observations: list[Observation] = field(default_factory=list)

    @property
    def durations(self) -> list[float]:
        return [observation.duration_seconds for observation in self.observations]

    @property
    def failures(self) -> list[Observation]:
        return [observation for observation in self.observations if observation.status_code != 201]

    def percentile(self, proportion: float) -> float:
        """Return the latency at the given percentile, in seconds.

        Nearest-rank on the sorted samples, rather than a mean of anything: a percentile is an order
        statistic, and averaging is how a p95 quietly becomes a p50.
        """
        ordered = sorted(self.durations)
        if not ordered:
            return 0.0
        index = min(len(ordered) - 1, max(0, round(proportion * len(ordered)) - 1))
        return ordered[index]


def parse_arguments(argv: list[str] | None = None) -> Arguments:
    """Parse the command line, refusing values that would make the run meaningless."""
    parser = argparse.ArgumentParser(description="Load smoke test for the sale endpoint.")
    parser.add_argument("--sales", type=int, default=200, help="sales to record (default: 200)")
    parser.add_argument(
        "--concurrency", type=int, default=20, help="requests in flight (default: 20)"
    )
    parser.add_argument(
        "--warmup", type=int, default=10, help="sequential sales before measuring (default: 10)"
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="database to run against (default: the local test database)",
    )
    parsed = parser.parse_args(argv)
    if parsed.sales < 1 or parsed.concurrency < 1 or parsed.warmup < 0:
        parser.error("--sales and --concurrency must be at least 1, and --warmup at least 0")
    return Arguments(
        sales=parsed.sales,
        concurrency=parsed.concurrency,
        warmup=parsed.warmup,
        database_url=parsed.database_url or DEFAULT_DATABASE_URL,
    )


def build_settings(database_url: str) -> Settings:
    """Build the settings the run uses.

    `_env_file=None` on purpose: a developer's `.env` may hold a production URL, and a load test
    that quietly used it would be the worst outcome this script can have.
    """
    return Settings(
        _env_file=None,
        app_env=AppEnvironment.TEST,
        database_url=database_url,
        jwt_secret=secrets.token_urlsafe(48),
        refresh_token_pepper=secrets.token_urlsafe(48),
        storage_provider=StorageProviderName.R2,
        r2_endpoint="https://account.r2.cloudflarestorage.com",
        r2_access_key_id=uuid4().hex,
        r2_secret_access_key=uuid4().hex,
        r2_bucket="ahia-load-smoke",
        argon2_time_cost=1,
        argon2_memory_cost_kib=8_192,
        argon2_parallelism=1,
        log_level="WARNING",
        metrics_auth_token=METRICS_TOKEN,
        **LOAD_RATE_LIMITS,
    )


async def prepare_schema(settings: Settings) -> None:
    """Create the schema from the models if it is not there yet.

    The models rather than the migrations: the run needs a schema, not a rollout. The migration
    chain is verified by the migration tests, and applying it here would make a smoke test fail for
    a reason that has nothing to do with load.
    """
    import_all_record_modules()
    database = Database(settings)
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(sync_connection, checkfirst=True)
            )
    finally:
        await database.dispose()


def fail(message: str) -> None:
    """Report a setup failure and stop.

    A setup failure means the run never started; continuing would produce a number for a path
    that was never exercised.
    """
    raise SystemExit(f"[FAIL] {message}")


async def register_business(client: AsyncClient) -> tuple[dict[str, str], str, str]:
    """Register a trader, open a business, and put one product on the shelf.

    Through the ordinary endpoints, because a load test that seeds its data another way measures a
    path no client uses.
    """
    registration = await client.post(
        "/api/v1/auth/register",
        json={
            "first_name": "Load",
            "last_name": "Smoke",
            "email": f"load.{uuid4().hex[:12]}@example.com",
            "password": ACCOUNT_PASSWORD,
        },
    )
    if registration.status_code != 201:
        fail(f"registration answered {registration.status_code}: {registration.text}")
    session = registration.json()
    headers = {"Authorization": f"Bearer {session['access_token']}"}

    tenant = await client.post(
        "/api/v1/tenants", headers=headers, json={"name": "Load Smoke Store"}
    )
    if tenant.status_code != 201:
        fail(f"tenant creation answered {tenant.status_code}: {tenant.text}")
    tenant_id = tenant.json()["id"]

    product = await client.post(
        f"/api/v1/tenants/{tenant_id}/products",
        headers=headers,
        json={"name": "Load Smoke Product", "selling_price": SELLING_PRICE},
    )
    if product.status_code != 201:
        fail(f"product creation answered {product.status_code}: {product.text}")
    product_id = product.json()["id"]

    receipt = await client.post(
        f"/api/v1/tenants/{tenant_id}/inventory/{product_id}/receipts",
        headers=headers,
        json={"quantity": STOCK_QUANTITY},
    )
    if receipt.status_code != 201:
        fail(f"stock receipt answered {receipt.status_code}: {receipt.text}")

    return headers, tenant_id, product_id


def sale_body(product_id: str) -> dict[str, Any]:
    """Return one sale: two units, paid in full, with a fresh operation identifier.

    The identifier is what makes the request a distinct sale rather than a replay, so it is
    generated per request exactly as a point-of-sale client would.
    """
    return {
        "lines": [{"product_id": product_id, "quantity": SALE_QUANTITY}],
        "payments": [{"amount": PAYMENT_AMOUNT, "method": "CASH"}],
        "operation_id": str(uuid4()),
    }


async def record_one_sale(
    client: AsyncClient,
    *,
    tenant_id: UUID | str,
    product_id: str,
    headers: dict[str, str],
) -> Observation:
    """Record one sale and time it end to end."""
    started = time.perf_counter()
    response = await client.post(
        f"/api/v1/tenants/{tenant_id}/sales",
        headers=headers,
        json=sale_body(product_id),
    )
    return Observation(
        duration_seconds=time.perf_counter() - started,
        status_code=response.status_code,
        correlation_id=response.headers.get("X-Correlation-ID"),
    )


async def run_measured_load(
    client: AsyncClient,
    *,
    tenant_id: str,
    product_id: str,
    headers: dict[str, str],
    arguments: Arguments,
) -> Summary:
    """Record `--sales` sales with at most `--concurrency` in flight, and time each one."""
    summary = Summary(requested=arguments.sales)
    semaphore = asyncio.Semaphore(arguments.concurrency)

    async def bounded() -> Observation:
        async with semaphore:
            return await record_one_sale(
                client, tenant_id=tenant_id, product_id=product_id, headers=headers
            )

    observations = await asyncio.gather(*(bounded() for _ in range(arguments.sales)))
    summary.observations.extend(observations)
    return summary


async def confirm_the_metrics_agree(client: AsyncClient, *, sale_path: str, expected: int) -> int:
    """Return the request count the application's own metrics recorded for the sale route.

    A client-side number nobody cross-checks can be produced by a server that dropped half the
    requests, so the application's counter is read back and printed beside it. The route label is
    computed with the same function the middleware uses, and the line is matched on that label
    rather than on a fixed column position, so the check does not depend on the order the labels
    happen to be rendered in.
    """
    response = await client.get("/metrics", headers={"Authorization": f"Bearer {METRICS_TOKEN}"})
    if response.status_code != 200:
        fail(f"the metrics endpoint answered {response.status_code}")
    wanted = f'route="{normalise_route(sale_path)}"'
    total = 0
    for line in response.text.splitlines():
        if not line.startswith("ahia_http_requests_total{"):
            continue
        labels, _, value = line.rpartition(" ")
        if wanted in labels:
            total += int(float(value))
    if total < expected:
        fail(
            f"the application counted {total} requests on the sale route, "
            f"expected at least {expected}"
        )
    return total


def render(summary: Summary, *, arguments: Arguments, elapsed_seconds: float, measured: int) -> str:
    """Return the plain-ASCII summary. No emoji, no box drawing, no colour."""
    durations = summary.durations
    requests_per_second = len(durations) / elapsed_seconds if elapsed_seconds > 0 else 0.0
    maximum = f"{max(durations) * 1000:.1f} ms" if durations else "n/a"
    mean = f"{statistics.fmean(durations) * 1000:.1f} ms" if durations else "n/a"
    lines = [
        "[OK] sale path load smoke test",
        f"     sales requested:      {summary.requested}",
        f"     sales measured:       {measured} (after {arguments.warmup} warm-up)",
        f"     concurrency:          {arguments.concurrency}",
        f"     wall clock:           {elapsed_seconds:.2f}s",
        f"     throughput:           {requests_per_second:.1f} sales/s",
        f"     latency p50:          {summary.percentile(0.50) * 1000:.1f} ms",
        f"     latency p95:          {summary.percentile(0.95) * 1000:.1f} ms",
        f"     latency p99:          {summary.percentile(0.99) * 1000:.1f} ms",
        f"     latency max:          {maximum}",
        f"     latency mean:         {mean}",
        f"     failures:             {len(summary.failures)}",
        f"     rate limits in use:   write {LOAD_RATE_LIMITS['rate_limit_write_per_minute']}/min, "
        f"global {LOAD_RATE_LIMITS['rate_limit_global_per_minute']}/min",
    ]
    for failure in summary.failures[:5]:
        lines.append(
            f"[FAIL] status={failure.status_code} correlation_id={failure.correlation_id or 'none'}"
        )
    return "\n".join(lines)


async def run(arguments: Arguments) -> int:
    """Run the smoke test and return the exit code."""
    settings = build_settings(arguments.database_url)
    await prepare_schema(settings)

    application = create_application(settings)
    transport = ASGITransport(app=application, raise_app_exceptions=False)
    async with (
        application.router.lifespan_context(application),
        AsyncClient(transport=transport, base_url="https://load-smoke") as client,
    ):
        headers, tenant_id, product_id = await register_business(client)

        for _ in range(arguments.warmup):
            warmup = await record_one_sale(
                client, tenant_id=tenant_id, product_id=product_id, headers=headers
            )
            if warmup.status_code != 201:
                fail(
                    f"warm-up sale answered {warmup.status_code} "
                    f"correlation_id={warmup.correlation_id or 'none'}"
                )

        started = time.perf_counter()
        summary = await run_measured_load(
            client,
            tenant_id=tenant_id,
            product_id=product_id,
            headers=headers,
            arguments=arguments,
        )
        elapsed = time.perf_counter() - started

        counted = await confirm_the_metrics_agree(
            client,
            sale_path=SALE_ROUTE_TEMPLATE.format(tenant_id=tenant_id),
            expected=arguments.sales,
        )

    print(render(summary, arguments=arguments, elapsed_seconds=elapsed, measured=summary.requested))
    print(f"     application counted:  {counted} requests on the sale route")
    return 1 if summary.failures else 0


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    arguments = parse_arguments(argv)
    print(f"[INFO] database host: {arguments.database_url.rsplit('@', 1)[-1]}")
    return asyncio.run(run(arguments))


if __name__ == "__main__":
    sys.exit(main())
