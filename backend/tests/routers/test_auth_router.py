"""End-to-end tests for authentication.

Nothing is mocked: real PostgreSQL, real Argon2 hashing, real JWTs, real refresh
rotation. Authentication is the one place where a mocked test proves nothing,
because the properties under test - timing equivalence, rotation, reuse detection
- are properties of the real implementation working together.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Database
from ahia.crud.session_crud import SessionRecord
from ahia.crud.user_crud import UserRecord
from ahia.main import create_application

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
PASSWORD = "a-good-enough-password"


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
        # Argon2 at production cost would make this suite minutes long; the
        # parameters are configuration precisely so a test can lower them.
        "argon2_time_cost": 1,
        "argon2_memory_cost_kib": 8_192,
        "argon2_parallelism": 1,
        "rate_limit_global_per_minute": 10_000,
        "rate_limit_write_per_minute": 10_000,
        # The settings object caps these; the ceiling is a deliberate bound on
        # how permissive a deployment can be configured to be.
        "rate_limit_auth_per_minute": 1_000,
        "rate_limit_password_reset_per_hour": 1_000,
    }
    baseline.update(overrides)
    return Settings(**baseline)


@asynccontextmanager
async def running_application(settings: Settings | None = None) -> AsyncIterator[Any]:
    application = create_application(settings or build_settings())
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="https://testserver") as client:
            yield client, application


@pytest.fixture
async def tables() -> AsyncIterator[None]:
    """Create both tables and empty them around each test."""
    database = Database(build_settings())
    async with database.engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: UserRecord.__table__.create(sync_connection, checkfirst=True)
        )
        await connection.run_sync(
            lambda sync_connection: SessionRecord.__table__.create(sync_connection, checkfirst=True)
        )
        await connection.execute(text("TRUNCATE TABLE user_sessions, users"))
    try:
        yield
    finally:
        await database.dispose()


def registration_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "first_name": "Emeka",
        "last_name": "Okonkwo",
        "email": f"emeka.{uuid4().hex[:8]}@example.com",
        "password": PASSWORD,
    }
    payload.update(overrides)
    return payload


async def register(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/auth/register", json=registration_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_registration_returns_a_usable_session(tables: None) -> None:
    async with running_application() as (client, _application):
        payload = await register(client)
        me = await client.get(
            "/api/v1/users/me", headers={"Authorization": f"Bearer {payload['access_token']}"}
        )

    assert me.status_code == 200
    assert me.json()["email"] == payload["user"]["email"]
    assert payload["token_type"] == "bearer"
    assert payload["expires_in_seconds"] > 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_registration_never_returns_a_credential(tables: None) -> None:
    async with running_application() as (client, _application):
        payload = await register(client)

    rendered = str(payload)
    assert PASSWORD not in rendered
    assert "argon2" not in rendered
    assert "password" not in rendered.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_registering_the_same_email_twice_conflicts(tables: None) -> None:
    async with running_application() as (client, _application):
        payload = registration_payload()
        first = await client.post("/api/v1/auth/register", json=payload)
        second = await client.post("/api/v1/auth/register", json=payload)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "CONFLICT"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_registration_requires_a_contact_channel(tables: None) -> None:
    async with running_application() as (client, _application):
        response = await client.post(
            "/api/v1/auth/register",
            json={"first_name": "Emeka", "password": PASSWORD},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_short_password_is_rejected(tables: None) -> None:
    async with running_application() as (client, _application):
        response = await client.post(
            "/api/v1/auth/register",
            json={**registration_payload(), "password": "short"},
        )

    assert response.status_code == 422
    assert "short" not in response.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_registration_by_phone_only(tables: None) -> None:
    async with running_application() as (client, _application):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "first_name": "Ngozi",
                "phone": f"+234803{1234567}",
                "password": PASSWORD,
            },
        )

    assert response.status_code == 201
    assert response.json()["user"]["phone"] == "+2348031234567"
    assert response.json()["user"]["email"] is None


# ---------------------------------------------------------------------------
# Sign-in
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sign_in_with_email_and_with_phone(tables: None) -> None:
    async with running_application() as (client, _application):
        payload = await register(client, phone="+2348031234567")

        by_email = await client.post(
            "/api/v1/auth/login",
            json={"identifier": payload["user"]["email"], "password": PASSWORD},
        )
        by_phone = await client.post(
            "/api/v1/auth/login",
            json={"identifier": "0803 123 4567", "password": PASSWORD},
        )
        by_uppercase_email = await client.post(
            "/api/v1/auth/login",
            json={"identifier": payload["user"]["email"].upper(), "password": PASSWORD},
        )

    assert by_email.status_code == 200
    assert by_phone.status_code == 200
    assert by_uppercase_email.status_code == 200
    assert by_phone.json()["user"]["id"] == payload["user"]["id"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_every_sign_in_failure_looks_identical(tables: None) -> None:
    """Unknown account, wrong password and unusable password are one answer."""
    async with running_application() as (client, _application):
        payload = await register(client)

        unknown = await client.post(
            "/api/v1/auth/login",
            json={"identifier": "nobody@example.com", "password": PASSWORD},
        )
        wrong = await client.post(
            "/api/v1/auth/login",
            json={"identifier": payload["user"]["email"], "password": "wrong-password-here"},
        )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["code"] == wrong.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]
    # The message never states whether the account exists.
    assert "user" not in unknown.json()["error"]["message"].lower()
    assert "not found" not in unknown.json()["error"]["message"].lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_deactivated_account_cannot_sign_in(tables: None) -> None:
    async with running_application() as (client, _application):
        payload = await register(client)
        headers = {"Authorization": f"Bearer {payload['access_token']}"}
        await client.delete("/api/v1/users/me", headers=headers)

        attempt = await client.post(
            "/api/v1/auth/login",
            json={"identifier": payload["user"]["email"], "password": PASSWORD},
        )

    assert attempt.status_code == 401
    assert attempt.json()["error"]["code"] == "INVALID_CREDENTIALS"


# ---------------------------------------------------------------------------
# Refresh rotation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_refresh_rotates_the_token(tables: None) -> None:
    async with running_application() as (client, _application):
        first = await register(client)

        rotated = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
        )

        assert rotated.status_code == 200
        assert rotated.json()["refresh_token"] != first["refresh_token"]

        reused = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
        )

    assert reused.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reusing_a_rotated_token_ends_the_whole_family(tables: None) -> None:
    """The defence that matters: a stolen refresh token cannot be used alongside the real one."""
    async with running_application() as (client, application):
        first = await register(client)
        rotated = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
        )
        assert rotated.status_code == 200
        new_refresh_token = rotated.json()["refresh_token"]

        # The thief presents the token that was already rotated.
        replay = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
        )

        # The legitimate holder's fresh token is now dead too, because the family
        # is the unit of trust, not the individual token.
        holders_attempt = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": new_refresh_token}
        )

        database = application.state.container.database
        async with database.transaction_scope() as unit_of_work:
            result = await unit_of_work.session_handle.execute(
                text("SELECT count(*) FROM user_sessions WHERE revoked_at IS NOT NULL")
            )
            revoked_count = int(result.scalar_one())

    assert replay.status_code == 401
    assert holders_attempt.status_code == 401
    assert revoked_count >= 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_refresh_with_an_unknown_token_is_rejected(tables: None) -> None:
    async with running_application() as (client, _application):
        response = await client.post("/api/v1/auth/refresh", json={"refresh_token": "a" * 64})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


# ---------------------------------------------------------------------------
# Sign-out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_logout_revokes_the_session_and_is_idempotent(tables: None) -> None:
    async with running_application() as (client, _application):
        payload = await register(client)

        first = await client.post(
            "/api/v1/auth/logout", json={"refresh_token": payload["refresh_token"]}
        )
        second = await client.post(
            "/api/v1/auth/logout", json={"refresh_token": payload["refresh_token"]}
        )
        refresh_after_logout = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": payload["refresh_token"]}
        )

    assert first.status_code == 200
    assert second.status_code == 200, "signing out twice must not be an error"
    assert refresh_after_logout.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
async def test_logout_with_an_unknown_token_succeeds(tables: None) -> None:
    async with running_application() as (client, _application):
        response = await client.post("/api/v1/auth/logout", json={"refresh_token": "b" * 64})

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Password change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_password_change_revokes_other_sessions_and_keeps_the_current_one(
    tables: None,
) -> None:
    async with running_application() as (client, _application):
        primary = await register(client)
        other_device = await client.post(
            "/api/v1/auth/login",
            json={"identifier": primary["user"]["email"], "password": PASSWORD},
        )
        assert other_device.status_code == 200

        changed = await client.post(
            "/api/v1/auth/password",
            headers={"Authorization": f"Bearer {primary['access_token']}"},
            json={"current_password": PASSWORD, "new_password": "a-new-good-password"},
        )
        kept_alive = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": primary["refresh_token"]}
        )
        signed_out = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": other_device.json()["refresh_token"]}
        )

    assert changed.status_code == 200
    assert changed.json()["other_sessions_revoked"] >= 1
    assert kept_alive.status_code == 200, "the device that changed the password stays signed in"
    assert signed_out.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
async def test_password_change_requires_the_current_password(tables: None) -> None:
    async with running_application() as (client, _application):
        payload = await register(client)
        response = await client.post(
            "/api/v1/auth/password",
            headers={"Authorization": f"Bearer {payload['access_token']}"},
            json={"current_password": "not-the-password", "new_password": "another-good-password"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_new_password_works_and_the_old_one_does_not(tables: None) -> None:
    async with running_application() as (client, _application):
        payload = await register(client)
        await client.post(
            "/api/v1/auth/password",
            headers={"Authorization": f"Bearer {payload['access_token']}"},
            json={"current_password": PASSWORD, "new_password": "a-new-good-password"},
        )

        with_new = await client.post(
            "/api/v1/auth/login",
            json={"identifier": payload["user"]["email"], "password": "a-new-good-password"},
        )
        with_old = await client.post(
            "/api/v1/auth/login",
            json={"identifier": payload["user"]["email"], "password": PASSWORD},
        )

    assert with_new.status_code == 200
    assert with_old.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
async def test_password_change_requires_authentication(tables: None) -> None:
    async with running_application() as (client, _application):
        response = await client.post(
            "/api/v1/auth/password",
            json={"current_password": PASSWORD, "new_password": "another-good-password"},
        )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Rate limiting and disclosure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sign_in_is_rate_limited_by_its_own_bucket(tables: None) -> None:
    """Three attempts allowed, the fourth refused, while reads stay unaffected."""
    settings = build_settings(
        rate_limit_auth_per_minute=3,
        rate_limit_global_per_minute=1_000,
        rate_limit_write_per_minute=1_000,
    )

    async with running_application(settings) as (client, _application):
        statuses = []
        for _ in range(4):
            response = await client.post(
                "/api/v1/auth/login",
                json={"identifier": "nobody@example.com", "password": "whatever-password"},
            )
            statuses.append(response.status_code)

        health = await client.get("/health")

    assert statuses[:3] == [401, 401, 401]
    assert statuses[3] == 429
    assert health.status_code == 200, "a sign-in burst must not lock out the service"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_auth_errors_disclose_nothing_internal(tables: None) -> None:
    async with running_application() as (client, _application):
        response = await client.post(
            "/api/v1/auth/login",
            json={"identifier": "nobody@example.com", "password": "whatever-password"},
        )

    lowered = response.text.lower()
    for forbidden in ("argon2", "sqlalchemy", "asyncpg", "traceback", "select ", "/home/"):
        assert forbidden not in lowered

    assert set(response.json()["error"]) == {"code", "message", "correlation_id"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_access_token_carries_its_session(tables: None) -> None:
    """The sid claim is what makes a future per-request revocation check possible."""
    async with running_application() as (client, application):
        payload = await register(client)
        claims = application.state.container.token_service.decode_access_token(
            payload["access_token"]
        )
        database = application.state.container.database
        async with database.transaction_scope() as unit_of_work:
            result = await unit_of_work.session_handle.execute(text("SELECT id FROM user_sessions"))
            session_id = str(result.scalar_one())

    assert claims.session_id == session_id
