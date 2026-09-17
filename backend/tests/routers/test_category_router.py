"""End-to-end tests for the category endpoints.

Real application, real PostgreSQL, real sessions. What is tested here is the part that
only exists over HTTP: the contract a client sees, the status codes, and the envelope
that must never carry internal detail.

Authorization is tested at the service layer as well
(`tests/services/test_category_service.py`), and deliberately so: a check that only
exists in a router can be bypassed by a CLI command, so the router test below proves
the check is reachable through HTTP, not that it lives here.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
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
        # The whole schema, created from the models. A table's foreign keys require
        # the tables they reference to exist first, and creating everything in
        # dependency order is exactly what create_all does.
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(sync_connection, checkfirst=True)
        )
        await connection.execute(
            text("TRUNCATE TABLE categories, tenant_memberships, tenants, users CASCADE")
        )
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


def categories_path(tenant_id: str) -> str:
    return f"/api/v1/tenants/{tenant_id}/categories"


# ---------------------------------------------------------------------------
# Creating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_creating_a_category_returns_it_with_a_derived_slug(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        response = await client.post(
            categories_path(tenant["id"]),
            headers=auth(owner),
            json={"name": "Cold Drinks", "description": "Everything chilled"},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Cold Drinks"
    assert body["slug"] == "cold-drinks"
    assert body["tenant_id"] == tenant["id"]
    assert body["description"] == "Everything chilled"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_client_cannot_send_a_slug(database: Database) -> None:
    """The domain derives it, so a second value that disagrees must not be accepted."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        response = await client.post(
            categories_path(tenant["id"]),
            headers=auth(owner),
            json={"name": "Cold Drinks", "slug": "something-else"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_empty_name_is_rejected_at_the_edge(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        response = await client.post(
            categories_path(tenant["id"]), headers=auth(owner), json={"name": "   "}
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_duplicate_name_is_a_conflict_without_leaking_internals(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        await client.post(
            categories_path(tenant["id"]), headers=auth(owner), json={"name": "Drinks"}
        )
        duplicate = await client.post(
            categories_path(tenant["id"]), headers=auth(owner), json={"name": "drinks"}
        )

    assert duplicate.status_code == 409
    body = duplicate.json()
    assert body["error"]["code"] == "CONFLICT"
    assert body["error"]["correlation_id"]

    # The external view says what happened and nothing about the schema.
    rendered = duplicate.text
    for internal in ("uq_categories", "categories", "INSERT", "sqlalchemy", "tenant_id"):
        assert internal not in rendered, f"the response leaked {internal}"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_listing_returns_the_businesss_categories_in_reading_order(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        for name in ("Snacks", "Drinks", "Appliances"):
            created = await client.post(
                categories_path(tenant["id"]), headers=auth(owner), json={"name": name}
            )
            assert created.status_code == 201, created.text

        listed = await client.get(categories_path(tenant["id"]), headers=auth(owner))

    assert listed.status_code == 200
    assert [category["name"] for category in listed.json()] == ["Appliances", "Drinks", "Snacks"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reading_one_category_by_identifier(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await client.post(
            categories_path(tenant["id"]), headers=auth(owner), json={"name": "Drinks"}
        )
        fetched = await client.get(
            f"{categories_path(tenant['id'])}/{created.json()['id']}", headers=auth(owner)
        )

    assert fetched.status_code == 200
    assert fetched.json() == created.json()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unknown_category_is_a_404_in_the_standard_envelope(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        response = await client.get(
            f"{categories_path(tenant['id'])}/{uuid4()}", headers=auth(owner)
        )

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["correlation_id"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_caller_outside_the_business_cannot_read_its_categories(
    database: Database,
) -> None:
    """Membership is the proof. A tenant identifier in the path is a hint, not access."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        await client.post(
            categories_path(tenant["id"]), headers=auth(owner), json={"name": "Drinks"}
        )

        outsider = await register(client)
        response = await client.get(categories_path(tenant["id"]), headers=auth(outsider))

    assert response.status_code in {403, 404}
    assert "Drinks" not in response.text


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_rename_keeps_the_slug(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await client.post(
            categories_path(tenant["id"]), headers=auth(owner), json={"name": "Drinks"}
        )
        renamed = await client.patch(
            f"{categories_path(tenant['id'])}/{created.json()['id']}",
            headers=auth(owner),
            json={"name": "Cold Drinks"},
        )

    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Cold Drinks"
    assert renamed.json()["slug"] == created.json()["slug"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_description_can_be_cleared_by_sending_null(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await client.post(
            categories_path(tenant["id"]),
            headers=auth(owner),
            json={"name": "Drinks", "description": "Everything cold"},
        )
        cleared = await client.patch(
            f"{categories_path(tenant['id'])}/{created.json()['id']}",
            headers=auth(owner),
            json={"description": None},
        )

    assert cleared.status_code == 200
    assert cleared.json()["description"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_update_that_omits_a_field_leaves_it_alone(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await client.post(
            categories_path(tenant["id"]),
            headers=auth(owner),
            json={"name": "Drinks", "description": "Everything cold"},
        )
        renamed = await client.patch(
            f"{categories_path(tenant['id'])}/{created.json()['id']}",
            headers=auth(owner),
            json={"name": "Cold Drinks"},
        )

    assert renamed.json()["description"] == "Everything cold"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_update_cannot_change_the_slug(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await client.post(
            categories_path(tenant["id"]), headers=auth(owner), json={"name": "Drinks"}
        )
        response = await client.patch(
            f"{categories_path(tenant['id'])}/{created.json()['id']}",
            headers=auth(owner),
            json={"slug": "cold-drinks"},
        )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Authorization over HTTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_salesperson_can_read_but_not_create(database: Database) -> None:
    async with running_application() as (client, application):
        owner, tenant = await owner_with_business(client)
        await client.post(
            categories_path(tenant["id"]), headers=auth(owner), json={"name": "Drinks"}
        )

        worker = await register(client)
        await add_member(
            application.state.container.database,
            tenant_id=UUID(tenant["id"]),
            user_id=UUID(worker["user"]["id"]),
            role_name="SALES",
        )

        listed = await client.get(categories_path(tenant["id"]), headers=auth(worker))
        refused = await client.post(
            categories_path(tenant["id"]), headers=auth(worker), json={"name": "Snacks"}
        )

    assert listed.status_code == 200
    assert [category["name"] for category in listed.json()] == ["Drinks"]
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "FORBIDDEN"
    assert "products.create" not in refused.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unauthenticated_request_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        _owner, tenant = await owner_with_business(client)
        # No credentials at all: the setup above signed somebody in, and a browser would send that
        # session cookie. An unauthenticated caller is one with neither a header nor a cookie.
        client.cookies.clear()
        response = await client.get(categories_path(tenant["id"]))

    assert response.status_code == 401
