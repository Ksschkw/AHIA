"""Disclosure tests for the external error surface.

The rule under test: a client learns that something failed, and nothing about how
the system is built. These tests drive real failures through the real stack and
inspect the bytes that come back.

They are written the way a curious client would probe: read the body, read the
headers, look for a path, a driver name, a query, a hostname, a port or a
traceback. Anything that helps an attacker map the system is a finding.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.security import TokenService
from ahia.main import create_application

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)

#: Substrings that must never appear in a response body. Each one is something a
#: reader could use: an internal path, a framework name, a query fragment, a
#: network location, or the shape of the failure.
FORBIDDEN_IN_RESPONSE: tuple[str, ...] = (
    "traceback",
    "stack trace",
    "sqlalchemy",
    "asyncpg",
    "psycopg",
    "postgres",
    "select ",
    "insert ",
    "update ",
    "delete from",
    "relation ",
    "constraint",
    "/home/",
    "/usr/",
    "site-packages",
    ".py",
    "127.0.0.1",
    "localhost",
    "59998",
    "5432",
    "internal server",
    "exception",
    "notimplemented",
    "keyerror",
    "valueerror",
)

#: Headers that would advertise the implementation. `server` is set by the ASGI
#: server in a real deployment and is not under our control here; what matters is
#: that we add nothing of our own.
FORBIDDEN_HEADER_NAMES: tuple[str, ...] = (
    "x-powered-by",
    "x-aspnet-version",
    "x-debug",
    "x-internal-trace",
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
        "rate_limit_write_per_minute": 1_000,
    }
    baseline.update(overrides)
    return Settings(**baseline)


@asynccontextmanager
async def running_application(settings: Settings | None = None) -> AsyncIterator[AsyncClient]:
    application = create_application(settings or build_settings())
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="https://testserver") as client:
            yield client


def assert_no_disclosure(response_text: str) -> None:
    lowered = response_text.lower()
    for forbidden in FORBIDDEN_IN_RESPONSE:
        assert forbidden not in lowered, f"the response disclosed {forbidden!r}"


def assert_standard_envelope(response_text: str) -> dict[str, Any]:
    payload = json.loads(response_text)
    assert set(payload) == {"error"}
    assert set(payload["error"]) == {"code", "message", "correlation_id"}
    assert payload["error"]["correlation_id"]
    assert isinstance(payload["error"]["message"], str)
    assert payload["error"]["message"].endswith(".")
    return payload


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unauthenticated_request_discloses_nothing() -> None:
    async with running_application() as client:
        response = await client.get("/api/v1/users/me")

    assert response.status_code == 401
    assert_standard_envelope(response.text)
    assert_no_disclosure(response.text)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_malformed_token_discloses_nothing() -> None:
    async with running_application() as client:
        response = await client.get(
            "/api/v1/users/me", headers={"Authorization": "Bearer not.a.jwt"}
        )

    assert response.status_code == 401
    assert_standard_envelope(response.text)
    assert_no_disclosure(response.text)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unknown_route_discloses_nothing() -> None:
    async with running_application() as client:
        response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert_standard_envelope(response.text)
    assert_no_disclosure(response.text)
    # The path a client guessed is not echoed back into the response.
    assert "does-not-exist" not in response.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_validation_failure_names_no_field_value() -> None:
    async with running_application() as client:
        response = await client.post(
            "/api/v1/users/me",
            json={"email": "a-reflected-value@example.com"},
        )

    assert response.status_code in {404, 405, 422}
    if response.headers.get("content-type", "").startswith("application/json"):
        assert_standard_envelope(response.text)
        assert "a-reflected-value@example.com" not in response.text
        assert_no_disclosure(response.text)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_database_failure_discloses_nothing() -> None:
    """A real connection failure travels the whole stack."""
    unreachable = build_settings(
        database_url="postgresql+asyncpg://nobody:nobody@127.0.0.1:59998/absent"
    )

    async with running_application(unreachable) as client:
        token = _issue_foreign_token(unreachable)
        response = await client.get(
            "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
        )

    assert_standard_envelope(response.text)
    assert_no_disclosure(response.text)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_docs_route_is_absent_in_production_and_leaks_nothing() -> None:
    """Interactive documentation enumerates the attack surface."""
    production = build_settings(
        app_env=AppEnvironment.PRODUCTION,
        log_format="json",
        database_require_ssl=True,
        cors_allowed_origins="https://app.ahia.app",
        jwt_secret="p" * 48,
        refresh_token_pepper="q" * 48,
    )

    async with running_application(production) as client:
        docs = await client.get("/docs")
        schema = await client.get("/openapi.json")

    assert docs.status_code == 404
    assert schema.status_code == 404
    assert_standard_envelope(docs.text)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rate_limit_rejection_discloses_nothing_but_the_limit() -> None:
    limited = build_settings(rate_limit_global_per_minute=1)

    async with running_application(limited) as client:
        await client.get("/health")
        response = await client.get("/health")

    payload = assert_standard_envelope(response.text)

    assert response.status_code == 429
    assert payload["error"]["code"] == "RATE_LIMITED"
    assert_no_disclosure(response.text)


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "path",
    ["/health", "/api/v1/users/me", "/api/v1/does-not-exist"],
)
async def test_responses_advertise_no_implementation(path: str) -> None:
    async with running_application() as client:
        response = await client.get(path)

    for header_name in FORBIDDEN_HEADER_NAMES:
        assert header_name not in {name.lower() for name in response.headers}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_error_responses_carry_the_same_security_headers_as_successes() -> None:
    """A header applied only to success protects nothing."""
    async with running_application() as client:
        success = await client.get("/health")
        failure = await client.get("/api/v1/users/me")

    for header_name in (
        "x-content-type-options",
        "x-frame-options",
        "referrer-policy",
        "content-security-policy",
    ):
        assert success.headers[header_name] == failure.headers[header_name]


def _issue_foreign_token(settings: Settings) -> str:
    """Issue a token with the same signing material but no matching account.

    The signature is valid, so the request reaches the service, which is where the
    database failure happens. This is the path that must not leak a driver error.
    """
    token_service = TokenService(
        secret=settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        access_token_ttl_minutes=settings.access_token_ttl_minutes,
        refresh_token_pepper=settings.refresh_token_pepper.get_secret_value(),
        public_token_bytes=settings.public_token_bytes,
    )
    token, _ = token_service.issue_access_token(subject=str(uuid4()))
    return token
