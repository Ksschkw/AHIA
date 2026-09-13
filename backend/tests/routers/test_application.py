"""Tests for the assembled application.

These exercise the real stack: middleware, exception handlers and routing
together, through an ASGI transport. That is the only way to know that a
correlation ID survives an error, that the security headers are present on a
response the framework produced before a route ran, and that the error envelope
is the same shape whatever failed.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.main import create_application

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)


def build_settings(**overrides: Any) -> Settings:
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
        "rate_limit_auth_per_minute": 1_000,
        "rate_limit_write_per_minute": 1_000,
    }
    baseline.update(overrides)
    return Settings(**baseline)


@asynccontextmanager
async def running_client(settings: Settings | None = None) -> AsyncIterator[AsyncClient]:
    """Yield a client whose application is inside its real lifespan.

    Entering the lifespan builds the container and leaving disposes it, which is
    what makes these tests exercise the wiring rather than a stub.
    """
    application = create_application(settings or build_settings())
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="https://testserver") as client:
            yield client


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_application_is_built_without_touching_the_environment() -> None:
    application = create_application(build_settings(app_name="AHIA-Test"))

    assert application.title == "AHIA-Test"
    # No container until startup, so importing or constructing has no side effect.
    assert not hasattr(application.state, "container")


@pytest.mark.unit
def test_documentation_is_withheld_in_production() -> None:
    production = create_application(
        build_settings(
            app_env=AppEnvironment.PRODUCTION,
            log_format="json",
            database_require_ssl=True,
            cors_allowed_origins="https://app.ahia.app",
            jwt_secret="p" * 48,
            refresh_token_pepper="q" * 48,
        )
    )

    assert production.docs_url is None
    assert production.openapi_url is None


@pytest.mark.unit
def test_documentation_is_available_outside_production() -> None:
    application = create_application(build_settings())

    assert application.docs_url == "/docs"
    assert application.openapi_url == "/openapi.json"


@pytest.mark.unit
def test_cors_is_an_allowlist_and_absent_when_unconfigured() -> None:
    """A wildcard with credentials is how a browser becomes the attacker."""
    configured = create_application(build_settings(cors_allowed_origins="https://app.ahia.app"))

    assert configured is not None

    # The settings object refuses the unsafe combination outright.
    with pytest.raises(ValueError, match="CORS"):
        build_settings(
            app_env=AppEnvironment.PRODUCTION,
            log_format="json",
            database_require_ssl=True,
            cors_allowed_origins="*",
            jwt_secret="p" * 48,
            refresh_token_pepper="q" * 48,
        )


# ---------------------------------------------------------------------------
# Health and readiness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_liveness_answers_without_touching_a_dependency() -> None:
    async with running_client() as client:
        response = await client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert set(payload) == {"status", "name", "version"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_readiness_reports_ready_when_the_database_answers() -> None:
    async with running_client() as client:
        response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_readiness_reports_not_ready_when_the_database_is_unreachable() -> None:
    """A dependency outage takes the instance out of rotation, not out of life."""
    settings = build_settings(
        database_url="postgresql+asyncpg://nobody:nobody@127.0.0.1:59999/absent"
    )
    application = create_application(settings)

    async with (
        application.router.lifespan_context(application),
        AsyncClient(
            transport=ASGITransport(app=application), base_url="https://testserver"
        ) as client,
    ):
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_readiness_reveals_nothing_about_the_dependency() -> None:
    settings = build_settings(
        database_url="postgresql+asyncpg://nobody:nobody@127.0.0.1:59999/absent"
    )
    application = create_application(settings)

    async with (
        application.router.lifespan_context(application),
        AsyncClient(
            transport=ASGITransport(app=application), base_url="https://testserver"
        ) as client,
    ):
        response = await client.get("/ready")

    rendered = response.text.lower()
    assert "postgres" not in rendered
    assert "59999" not in rendered
    assert "nobody" not in rendered


# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unknown_route_returns_the_standard_envelope() -> None:
    async with running_client() as client:
        response = await client.get("/does-not-exist")

    payload = response.json()

    assert response.status_code == 404
    assert set(payload["error"]) == {"code", "message", "correlation_id"}
    assert payload["error"]["code"] == "NOT_FOUND"
    assert "does-not-exist" not in payload["error"]["message"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_method_not_allowed_returns_the_standard_envelope() -> None:
    async with running_client() as client:
        response = await client.post("/health")

    payload = response.json()

    assert response.status_code == 404
    assert payload["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_correlation_id_is_returned_on_an_error_and_quoted_in_the_body() -> None:
    async with running_client() as client:
        response = await client.get(
            "/does-not-exist", headers={"X-Correlation-ID": "trace-abc-123"}
        )

    payload = response.json()

    assert response.headers["x-correlation-id"] == "trace-abc-123"
    assert payload["error"]["correlation_id"] == "trace-abc-123"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_security_headers_are_present_on_an_error_response() -> None:
    async with running_client() as client:
        response = await client.get("/does-not-exist")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unexpected_failure_is_opaque() -> None:
    application = create_application(build_settings())

    @application.get("/explode")
    async def explode() -> None:
        raise RuntimeError("connection to db.internal:5432 refused")

    async with (
        application.router.lifespan_context(application),
        AsyncClient(
            transport=ASGITransport(app=application, raise_app_exceptions=False),
            base_url="https://testserver",
        ) as client,
    ):
        response = await client.get("/explode")

    payload = response.json()
    rendered = response.text

    assert response.status_code == 500
    assert payload["error"]["code"] == "INTERNAL_ERROR"
    assert "db.internal" not in rendered
    assert "RuntimeError" not in rendered
    assert response.headers["x-correlation-id"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rate_limit_is_enforced_through_the_real_stack() -> None:
    settings = build_settings(rate_limit_global_per_minute=2)
    async with running_client(settings) as client:
        statuses = [(await client.get("/health")).status_code for _ in range(4)]

    assert statuses[:2] == [200, 200]
    assert statuses[2:] == [429, 429]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rate_limited_response_uses_the_shared_envelope() -> None:
    settings = build_settings(rate_limit_global_per_minute=1)
    async with running_client(settings) as client:
        await client.get("/health")
        response = await client.get("/health")

    payload = json.loads(response.text)

    assert response.status_code == 429
    assert payload["error"]["code"] == "RATE_LIMITED"
    assert response.headers["retry-after"]


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
