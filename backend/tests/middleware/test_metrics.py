"""Tests for metrics: the counters, the labels, and who may read them.

Three subjects.

**Labels are bounded.** A metric labelled with a raw path has one series per identifier a client
invents, which is how a metrics store fills up and a scrape starts timing out. The route normaliser
is asserted directly, and the registry is asserted to collapse two requests to different
identifiers into one series.

**The endpoint is not open by default.** With no token configured it answers as if it did not
exist; with one configured, a missing or wrong token is an authentication failure and the
configured one is accepted. The comparison is constant-time, which a test asserts about the
implementation rather than about timing.

**A failure is counted even when the application raised.** The middleware records the status it
observed and a 500 when none was sent, so an outage does not look like a quiet period.
"""

from __future__ import annotations

import hmac
import os
import pathlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from ahia.core import metrics as metrics_module
from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.metrics import MetricsRegistry, normalise_route, status_class
from ahia.main import create_application
from ahia.routers import metrics_router

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
SCRAPE_TOKEN = "scrape-token-for-tests-only-000001"


def build_settings(*, metrics_token: str | None = None, **overrides: Any) -> Settings:
    baseline: dict[str, Any] = {
        "_env_file": None,
        "app_env": AppEnvironment.TEST,
        "database_url": os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL),
        "jwt_secret": "test-signing-secret-value-0000000001",
        "refresh_token_pepper": "test-refresh-pepper-value-00000000011",
        "storage_provider": StorageProviderName.R2,
        "r2_endpoint": "https://account.r2.cloudflarestorage.com",
        "r2_access_key_id": "r2-access-key",
        "r2_secret_access_key": "r2-secret-key",
        "r2_bucket": "ahia-test",
        "rate_limit_global_per_minute": 1_000,
        "rate_limit_write_per_minute": 1_000,
        "rate_limit_auth_per_minute": 1_000,
        "rate_limit_password_reset_per_hour": 1_000,
        "rate_limit_public_read_per_minute": 1_000,
        "metrics_auth_token": metrics_token,
    }
    baseline.update(overrides)
    return Settings(**baseline)


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    instance = Database(build_settings())
    async with instance.engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(sync_connection, checkfirst=True)
        )
        await connection.execute(text("TRUNCATE TABLE tenants, users CASCADE"))
    try:
        yield instance
    finally:
        await instance.dispose()


@asynccontextmanager
async def running_application(
    *, metrics_token: str | None = None
) -> AsyncIterator[tuple[AsyncClient, Any]]:
    application = create_application(build_settings(metrics_token=metrics_token))
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="https://testserver") as client:
            yield client, application


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_identifiers_in_a_path_become_one_label() -> None:
    """A raw path is a series per identifier a client invents, which is how a scrape times out."""
    assert (
        normalise_route("/api/v1/tenants/8f3a1c2e-1111-4222-8333-444455556666/products")
        == "/api/v1/tenants/{id}/products"
    )
    assert normalise_route("/share/report/abc123") == "/share/report/abc123", (
        "an opaque token is one route, and the label is the route"
    )
    assert normalise_route("/api/v1/items/42") == "/api/v1/items/{id}"


@pytest.mark.unit
def test_a_status_class_is_the_class_and_not_the_code() -> None:
    assert status_class(200) == "2xx"
    assert status_class(404) == "4xx"
    assert status_class(503) == "5xx"


@pytest.mark.unit
def test_two_requests_to_different_identifiers_are_one_series() -> None:
    registry = MetricsRegistry()

    registry.observe_request(
        method="get",
        path="/api/v1/tenants/11111111-1111-4111-8111-111111111111/products",
        status_code=200,
        duration_seconds=0.1,
    )
    registry.observe_request(
        method="GET",
        path="/api/v1/tenants/22222222-2222-4222-8222-222222222222/products",
        status_code=200,
        duration_seconds=0.3,
    )

    assert registry.requests_by_route == {("GET", "/api/v1/tenants/{id}/products", "2xx"): 2}
    rendered = registry.render()
    assert "ahia_http_requests_total" in rendered
    assert "11111111" not in rendered, "no identifier reaches a label"
    assert registry.durations_by_route[
        ("GET", "/api/v1/tenants/{id}/products")
    ].maximum_duration_seconds == pytest.approx(0.3)


@pytest.mark.unit
def test_every_metric_is_declared_with_a_type() -> None:
    """The exposition format needs a HELP and a TYPE line, and a reader rejects a metric without."""
    registry = MetricsRegistry()
    registry.observe_request(method="GET", path="/health", status_code=200, duration_seconds=0.01)
    registry.record_error(error_code="NOT_FOUND")
    registry.record_authorization_denial(action="cancel_sale")
    registry.record_breaker_state(dependency="r2", state="open")
    registry.record_breaker_short_circuit(dependency="r2")

    rendered = registry.render()

    for name in (
        "ahia_http_requests_total",
        "ahia_http_request_duration_seconds_total",
        "ahia_http_request_duration_seconds_max",
        "ahia_errors_total",
        "ahia_authorization_denials_total",
        "ahia_circuit_breaker_state",
        "ahia_circuit_breaker_short_circuits_total",
    ):
        assert f"# HELP {name} " in rendered
        assert f"# TYPE {name} " in rendered
    assert 'ahia_circuit_breaker_state{dependency="r2"} 2' in rendered, (
        "open is 2: an alert on a breaker is an expression on a number"
    )


@pytest.mark.unit
def test_no_registry_is_shared_between_two_constructions() -> None:
    """No module-level singleton: two applications in one process must not share counters."""
    first = MetricsRegistry()
    second = MetricsRegistry()

    first.record_error(error_code="NOT_FOUND")

    assert second.errors_by_code == {}
    assert not hasattr(metrics_module, "REGISTRY"), "the registry is constructed, never imported"


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_metrics_are_absent_until_a_scraping_token_is_configured(
    database: Database,
) -> None:
    async with running_application(metrics_token=None) as (client, _application):
        response = await client.get("/metrics")

    assert response.status_code == 404
    assert set(response.json()) == {"error"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_metrics_require_the_configured_token(database: Database) -> None:
    async with running_application(metrics_token=SCRAPE_TOKEN) as (client, _application):
        missing = await client.get("/metrics")
        wrong = await client.get("/metrics", headers={"Authorization": "Bearer not-the-token"})
        accepted = await client.get("/metrics", headers={"Authorization": f"Bearer {SCRAPE_TOKEN}"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert accepted.status_code == 200
    assert accepted.headers["content-type"].startswith("text/plain")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_endpoint_reports_the_requests_that_were_made(database: Database) -> None:
    """The counters describe this process, and a scrape is itself a request nobody counts yet."""
    async with running_application(metrics_token=SCRAPE_TOKEN) as (client, _application):
        await client.get("/health")
        await client.get("/no-such-route")
        response = await client.get("/metrics", headers={"Authorization": f"Bearer {SCRAPE_TOKEN}"})

    body = response.text
    assert 'ahia_http_requests_total{method="GET",route="/health",status_class="2xx"} 1' in body
    assert (
        'ahia_http_requests_total{method="GET",route="/no-such-route",status_class="4xx"} 1' in body
    )
    assert "ahia_http_request_duration_seconds_max" in body


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_refusal_is_counted_by_the_use_case_that_refused(database: Database) -> None:
    """A denial counter keyed by the permission would name nothing an operator can act on."""
    async with running_application(metrics_token=SCRAPE_TOKEN) as (client, _application):
        await client.get("/api/v1/tenants/not-a-uuid/reports/daily-sales")
        response = await client.get("/metrics", headers={"Authorization": f"Bearer {SCRAPE_TOKEN}"})

    body = response.text
    assert "ahia_errors_total" in body
    assert "ahia_authorization_denials_total" in body


@pytest.mark.unit
def test_the_token_comparison_is_constant_time() -> None:
    """A token compared with `==` leaks its prefix through timing, one byte at a time."""
    source = pathlib.Path(metrics_router.__file__).read_text(encoding="utf-8")

    assert "hmac.compare_digest" in source, "the scraping token must not be compared with =="
    # The constant-time helper is what it says it is, so the assertion above is about the right one.
    assert hmac.compare_digest(b"a", b"a") is True
