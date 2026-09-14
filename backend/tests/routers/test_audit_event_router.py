"""End-to-end tests for the audit endpoints.

Real application, real PostgreSQL. What is tested here is what a trail is worth over HTTP: that
a business can read its own, that an ordinary member cannot, that another business sees nothing,
and that no request can change or remove an entry.

**The absence of a write route is asserted over HTTP.** `POST`, `PATCH` and `DELETE` on the
trail reach no handler. The database refuses UPDATE and DELETE by trigger as well, so the answer
does not depend on this router; the test covers the whole stack a client can reach.

**A refusal is readable as a refusal.** `is_refusal` is derived from the outcome and travels, so
a client does not have to know the vocabulary to show "this was denied" differently from "this
was done".
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.crud import tenant_membership_crud
from ahia.main import create_application
from ahia.models.entities.tenant_membership_model import TenantMembershipModel
from ahia.services.iam_seed_service import IamSeedService

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
        "argon2_time_cost": 1,
        "argon2_memory_cost_kib": 8_192,
        "argon2_parallelism": 1,
        "rate_limit_global_per_minute": 1_000,
        "rate_limit_write_per_minute": 1_000,
        "rate_limit_auth_per_minute": 1_000,
        "rate_limit_password_reset_per_hour": 1_000,
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
        await connection.execute(
            text(
                "TRUNCATE TABLE audit_events, expenses, ledger_entries, role_permissions, roles, "
                "permissions, tenant_memberships, tenants, user_sessions, users CASCADE"
            )
        )
    await IamSeedService(unit_of_work_factory=instance.unit_of_work_factory()).install_registry()
    try:
        yield instance
    finally:
        await instance.dispose()


@asynccontextmanager
async def running_application(settings: Settings | None = None) -> AsyncIterator[Any]:
    application = create_application(settings or build_settings())
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="https://testserver") as client:
            yield client, application


async def register(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "first_name": "Emeka",
        "last_name": "Okonkwo",
        "email": f"user.{uuid4().hex[:8]}@example.com",
        "password": PASSWORD,
    }
    payload.update(overrides)
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def auth(session_payload: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_payload['access_token']}"}


async def owner_with_business(client: AsyncClient) -> tuple[dict[str, Any], dict[str, Any]]:
    owner = await register(client)
    created = await client.post(
        "/api/v1/tenants", headers=auth(owner), json={"name": "Obi Electronics"}
    )
    assert created.status_code == 201, created.text
    return owner, created.json()


async def add_member(database: Database, *, tenant_id: UUID, user_id: UUID, role_name: str) -> None:
    membership = TenantMembershipModel.activate_immediately(
        membership_id=uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        role_name=role_name,
        now=datetime.now(UTC),
    )
    async with database.transaction_scope() as unit_of_work:
        await tenant_membership_crud.create(unit_of_work.session_handle, membership)
        await unit_of_work.commit()


def trail_path(tenant_id: str, *parts: str) -> str:
    suffix = "".join(f"/{part}" for part in parts)
    return f"/api/v1/tenants/{tenant_id}/audit-events{suffix}"


async def record_expense(
    client: AsyncClient, owner: dict[str, Any], tenant: dict[str, Any]
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/expenses",
        headers=auth(owner),
        json={"category": "TRANSPORT", "amount": "3500.00"},
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_owner_reads_the_trail_of_their_business(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        await record_expense(client, owner, tenant)

        response = await client.get(trail_path(tenant["id"]), headers=auth(owner))

    assert response.status_code == 200, response.text
    events = response.json()
    assert [event["action"] for event in events] == ["record_expense"]
    assert events[0]["outcome"] == "SUCCEEDED"
    assert events[0]["is_refusal"] is False
    assert events[0]["actor_id"] == owner["user"]["id"]
    assert events[0]["detail"]["category"] == "TRANSPORT"
    assert events[0]["occurred_at"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_one_records_history_is_returned_oldest_first(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        expense = await record_expense(client, owner, tenant)
        await client.post(
            f"/api/v1/tenants/{tenant['id']}/expenses/{expense['id']}/reverse",
            headers=auth(owner),
            json={"reason": "the driver never came"},
        )

        response = await client.get(
            trail_path(tenant["id"], "history", "expense", expense["id"]),
            headers=auth(owner),
        )

    assert response.status_code == 200, response.text
    assert [event["action"] for event in response.json()] == [
        "record_expense",
        "reverse_expense",
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_trail_can_be_narrowed_by_action_and_by_person(
    database: Database,
) -> None:
    async with running_application() as (client, application):
        owner, tenant = await owner_with_business(client)
        other = await register(client)
        await add_member(
            application.state.container.database,
            tenant_id=UUID(tenant["id"]),
            user_id=UUID(other["user"]["id"]),
            role_name="MANAGER",
        )
        await record_expense(client, owner, tenant)
        await record_expense(client, other, tenant)

        by_action = await client.get(
            trail_path(tenant["id"]), headers=auth(owner), params={"entity_type": "expense"}
        )
        by_actor = await client.get(
            trail_path(tenant["id"]),
            headers=auth(owner),
            params={"actor_id": other["user"]["id"]},
        )

    assert by_action.status_code == 200
    assert len(by_action.json()) == 2
    assert len(by_actor.json()) == 1
    assert by_actor.json()[0]["actor_id"] == other["user"]["id"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_period_narrows_the_trail(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        await record_expense(client, owner, tenant)

        since = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        until = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
        inside = await client.get(
            trail_path(tenant["id"]),
            headers=auth(owner),
            params={"since": since, "until": until},
        )
        before = await client.get(
            trail_path(tenant["id"]),
            headers=auth(owner),
            params={
                "since": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
                "until": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            },
        )

    assert len(inside.json()) == 1
    assert before.json() == []


# ---------------------------------------------------------------------------
# Nothing can be written, changed or removed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_no_request_can_add_change_or_remove_an_event(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        await record_expense(client, owner, tenant)
        listed = await client.get(trail_path(tenant["id"]), headers=auth(owner))
        event_id = listed.json()[0]["id"]

        created = await client.post(
            trail_path(tenant["id"]),
            headers=auth(owner),
            json={"action": "invent_history", "entity_type": "expense"},
        )
        changed = await client.patch(
            trail_path(tenant["id"]) + f"/{event_id}",
            headers=auth(owner),
            json={"outcome": "SUCCEEDED"},
        )
        removed = await client.delete(
            trail_path(tenant["id"]) + f"/{event_id}", headers=auth(owner)
        )

    for response in (created, changed, removed):
        assert response.status_code in {404, 405}, response.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_trail_still_holds_the_event_after_those_attempts(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        await record_expense(client, owner, tenant)
        listed = await client.get(trail_path(tenant["id"]), headers=auth(owner))
        event_id = listed.json()[0]["id"]

        await client.delete(trail_path(tenant["id"]) + f"/{event_id}", headers=auth(owner))
        after = await client.get(trail_path(tenant["id"]), headers=auth(owner))

    assert [event["id"] for event in after.json()] == [event_id]


# ---------------------------------------------------------------------------
# Authorization and tenant scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_salesperson_cannot_read_the_trail(database: Database) -> None:
    async with running_application() as (client, application):
        owner, tenant = await owner_with_business(client)
        await record_expense(client, owner, tenant)
        worker = await register(client)
        await add_member(
            application.state.container.database,
            tenant_id=UUID(tenant["id"]),
            user_id=UUID(worker["user"]["id"]),
            role_name="SALES",
        )

        response = await client.get(trail_path(tenant["id"]), headers=auth(worker))

    assert response.status_code == 403
    assert "record_expense" not in response.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_another_business_cannot_read_the_trail(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        await record_expense(client, owner, tenant)
        other_owner, other_tenant = await owner_with_business(client)

        response = await client.get(trail_path(other_tenant["id"]), headers=auth(other_owner))
        history = await client.get(
            trail_path(other_tenant["id"], "history", "expense", str(uuid4())),
            headers=auth(other_owner),
        )

    assert response.status_code == 200
    assert response.json() == [], "another business's trail is empty, not forbidden"
    assert history.status_code == 200
    assert history.json() == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unauthenticated_request_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        _owner, tenant = await owner_with_business(client)

        response = await client.get(trail_path(tenant["id"]))

    assert response.status_code == 401
