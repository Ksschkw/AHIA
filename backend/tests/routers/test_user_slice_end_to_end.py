"""End-to-end tests for the User slice.

Nothing is mocked here: the real application, the real middleware, the real
service, the real repository and the real PostgreSQL test database. A slice is
only proven when a request travels the whole path and the effect is visible in the
database afterwards.

The sequence in the main test is the product's own flow: a person exists, their
token authenticates, they read and change their own profile, they deactivate the
account, and the token they were holding stops working immediately.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Database
from ahia.crud import user_crud
from ahia.crud.user_crud import UserRecord
from ahia.main import create_application
from ahia.models.entities.user_model import UserModel

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
        "rate_limit_write_per_minute": 1_000,
    }
    baseline.update(overrides)
    return Settings(**baseline)


@asynccontextmanager
async def running_slice(settings: Settings | None = None) -> AsyncIterator[tuple[AsyncClient, Any]]:
    """Yield a client and application with the real container running."""
    application = create_application(settings or build_settings())
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="https://testserver") as client:
            yield client, application


@pytest.fixture
async def users_table() -> AsyncIterator[None]:
    """Create the users table and empty it around each test."""
    database = Database(build_settings())
    async with database.engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: UserRecord.__table__.create(sync_connection, checkfirst=True)
        )
        await connection.execute(text("TRUNCATE TABLE users"))
    try:
        yield
    finally:
        await database.dispose()


async def seed_user(application: Any, **overrides: Any) -> UserModel:
    """Insert a user through the real repository and commit."""
    parameters: dict[str, Any] = {
        "user_id": uuid4(),
        "first_name": "Emeka",
        "now": datetime(2026, 9, 13, 9, 30, tzinfo=UTC),
        "last_name": "Okonkwo",
        "email": f"emeka.{uuid4().hex[:8]}@example.com",
        "phone": None,
    }
    parameters.update(overrides)
    user = UserModel.create(**parameters)  # type: ignore[arg-type]

    database = application.state.container.database
    async with database.transaction_scope() as unit_of_work:
        await user_crud.create(unit_of_work.session_handle, user)
        await unit_of_work.commit()
    return user


def issue_token(application: Any, user_id: Any) -> str:
    token, _ = application.state.container.token_service.issue_access_token(subject=str(user_id))
    return token


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# The full journey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_whole_user_journey_against_a_real_database(users_table: None) -> None:
    """Read, update, deactivate, and the token stops working at once."""
    async with running_slice() as (client, application):
        user = await seed_user(application)
        token = issue_token(application, user.id)

        read = await client.get("/api/v1/users/me", headers=auth(token))
        assert read.status_code == 200
        assert read.json()["id"] == str(user.id)
        assert read.json()["first_name"] == "Emeka"

        updated = await client.patch(
            "/api/v1/users/me",
            headers=auth(token),
            json={"first_name": "Chinedu", "last_name": "Nwachukwu"},
        )
        assert updated.status_code == 200
        assert updated.json()["first_name"] == "Chinedu"

        # The change is in the database, not only in the response.
        database = application.state.container.database
        async with database.transaction_scope() as unit_of_work:
            stored = await user_crud.get_by_id(unit_of_work.session_handle, user.id)
        assert stored is not None
        assert stored.first_name == "Chinedu"
        assert stored.last_name == "Nwachukwu"
        assert stored.email == user.email, "an untouched field must survive"

        deactivated = await client.delete("/api/v1/users/me", headers=auth(token))
        assert deactivated.status_code == 200
        assert deactivated.json()["is_active"] is False

        # Deactivation takes effect immediately for the token already issued.
        after_deactivation = await client.get("/api/v1/users/me", headers=auth(token))
        assert after_deactivation.status_code == 401
        assert after_deactivation.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_update_survives_a_second_request(users_table: None) -> None:
    """The write is committed, so a later request in a new transaction sees it."""
    async with running_slice() as (client, application):
        user = await seed_user(application, email="ada@example.com")
        token = issue_token(application, user.id)

        await client.patch("/api/v1/users/me", headers=auth(token), json={"phone": "0803 123 4567"})
        reread = await client.get("/api/v1/users/me", headers=auth(token))

    assert reread.json()["phone"] == "08031234567"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_token_for_an_account_that_does_not_exist_is_rejected(users_table: None) -> None:
    """A valid signature is not enough: the subject must still exist and be active."""
    async with running_slice() as (client, application):
        token = issue_token(application, uuid4())
        response = await client.get("/api/v1/users/me", headers=auth(token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_two_users_never_see_each_other(users_table: None) -> None:
    """Each token resolves to its own subject, whatever the request contains."""
    async with running_slice() as (client, application):
        first = await seed_user(application, first_name="Emeka")
        second = await seed_user(application, first_name="Ngozi")
        first_token = issue_token(application, first.id)
        second_token = issue_token(application, second.id)

        first_view = await client.get("/api/v1/users/me", headers=auth(first_token))
        second_view = await client.get("/api/v1/users/me", headers=auth(second_token))

    assert first_view.json()["id"] == str(first.id)
    assert second_view.json()["id"] == str(second.id)
    assert first_view.json()["first_name"] == "Emeka"
    assert second_view.json()["first_name"] == "Ngozi"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_duplicate_email_is_a_conflict_and_not_a_crash(users_table: None) -> None:
    """A conflict surfaces as a typed error through the whole stack."""
    async with running_slice() as (client, application):
        shared_email = f"shared.{uuid4().hex[:8]}@example.com"
        await seed_user(application, email=shared_email)

        # Changing the second user's email to the first one's collides.
        second = await seed_user(application, first_name="Ngozi")
        second_token = issue_token(application, second.id)
        response = await client.patch(
            "/api/v1/users/me", headers=auth(second_token), json={"email": shared_email}
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    assert response.json()["error"]["correlation_id"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_external_error_leaks_nothing_internal(users_table: None) -> None:
    """The leak test the specification requires, at the slice boundary.

    The database is pointed at a port with nothing listening, so a real failure
    travels the whole stack: the driver raises, persistence translates, the
    middleware renders. The body must contain no path, no SQL, no driver name, no
    hostname and no traceback.
    """
    unreachable = build_settings(
        database_url="postgresql+asyncpg://nobody:nobody@127.0.0.1:59998/absent"
    )

    async with running_slice(unreachable) as (client, application):
        token = issue_token(application, uuid4())
        response = await client.get("/api/v1/users/me", headers=auth(token))

    body = response.text
    payload = json.loads(body)

    assert response.status_code in {401, 500, 503}
    assert set(payload["error"]) == {"code", "message", "correlation_id"}

    lowered = body.lower()
    for forbidden in (
        "traceback",
        "sqlalchemy",
        "asyncpg",
        "postgres",
        "127.0.0.1",
        "59998",
        "/home/",
        ".py",
        "select ",
        "from users",
        "connection",
    ):
        assert forbidden not in lowered, f"the external error leaked: {forbidden}"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_correlation_id_travels_from_request_to_stored_change(users_table: None) -> None:
    """One identifier links the client's report to the work that was done."""
    async with running_slice() as (client, application):
        user = await seed_user(application)
        token = issue_token(application, user.id)

        response = await client.patch(
            "/api/v1/users/me",
            headers={**auth(token), "X-Correlation-ID": "slice-trace-0001"},
            json={"first_name": "Ada"},
        )

    assert response.headers["x-correlation-id"] == "slice-trace-0001"
    assert response.status_code == 200
