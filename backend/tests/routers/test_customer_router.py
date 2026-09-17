"""End-to-end tests for the customer endpoints.

Real application, real PostgreSQL. What is tested here is the part that only exists over
HTTP: the shape of a creation response that carries a possible duplicate without refusing
the write, the version a client sends back, the lookup route's ordering, and the fact that
a customer of another business is a 404 rather than a 403.
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
            text("TRUNCATE TABLE customers, tenant_memberships, tenants, users CASCADE")
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
    tenant = await client.post(
        "/api/v1/tenants", headers=auth(owner), json={"name": "Obi Electronics"}
    )
    assert tenant.status_code == 201, tenant.text
    return owner, tenant.json()


def customers_path(tenant_id: str, *parts: str) -> str:
    suffix = "".join(f"/{part}" for part in parts)
    return f"/api/v1/tenants/{tenant_id}/customers{suffix}"


async def add_customer(
    client: AsyncClient, owner: dict[str, Any], tenant: dict[str, Any], **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": "Ada Obi", "phone": "0803 123 4567"}
    payload.update(overrides)
    response = await client.post(customers_path(tenant["id"]), headers=auth(owner), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_recording_a_customer_completes_the_phone_number(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        response = await client.post(
            customers_path(tenant["id"]),
            headers=auth(owner),
            json={
                "name": "Ada Obi",
                "phone": "0803 123 4567",
                "email": "Ada@Example.COM",
                "address": "12 Awolowo Road, Ikeja",
                "notes": "Prefers delivery on Saturdays",
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["customer"]["phone"] == "+2348031234567"
    assert body["customer"]["email"] == "ada@example.com"
    assert body["customer"]["version"] == 1
    assert body["customer"]["marketing_opt_in"] is False
    assert body["possible_duplicate_of"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_second_customer_with_the_same_number_is_recorded_and_reported(
    database: Database,
) -> None:
    """A shared household number must not stop the shopkeeper recording the second person."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        first = await add_customer(client, owner, tenant, name="Ada Obi")
        second = await add_customer(client, owner, tenant, name="Chidi Obi")
        listed = await client.get(customers_path(tenant["id"]), headers=auth(owner))

    assert second["possible_duplicate_of"] == first["customer"]["id"]
    assert [customer["name"] for customer in listed.json()] == ["Ada Obi", "Chidi Obi"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_implausible_phone_number_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        response = await client.post(
            customers_path(tenant["id"]),
            headers=auth(owner),
            json={"name": "Ada Obi", "phone": "0803-ABC-4567"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_customer_can_be_recorded_with_only_a_name(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        response = await client.post(
            customers_path(tenant["id"]), headers=auth(owner), json={"name": "Walk-in"}
        )

    assert response.status_code == 201, response.text
    assert response.json()["customer"]["phone"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_marketing_consent_is_opt_in_not_opt_out(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        silent = await add_customer(client, owner, tenant, name="Ada Obi")
        consenting = await add_customer(
            client, owner, tenant, name="Chidi Obi", phone=None, marketing_opt_in=True
        )

    assert silent["customer"]["marketing_opt_in"] is False
    assert consenting["customer"]["marketing_opt_in"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_tenant_field_cannot_be_set_by_a_client(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        response = await client.post(
            customers_path(tenant["id"]),
            headers=auth(owner),
            json={"name": "Ada Obi", "tenant_id": str(uuid4())},
        )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# The counter lookup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_lookup_route_is_not_read_as_a_customer_identifier(
    database: Database,
) -> None:
    """Route order: `lookup` is a literal segment and must be matched as one."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        await add_customer(client, owner, tenant)
        found = await client.get(
            customers_path(tenant["id"], "lookup"),
            headers=auth(owner),
            params={"phone": "08031234567"},
        )

    assert found.status_code == 200, found.text
    assert [match["name"] for match in found.json()["matches"]] == ["Ada Obi"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_lookup_finds_nobody_for_an_unknown_number(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        found = await client.get(
            customers_path(tenant["id"], "lookup"),
            headers=auth(owner),
            params={"phone": "0803 999 8888"},
        )

    assert found.status_code == 200
    assert found.json()["matches"] == []


# ---------------------------------------------------------------------------
# Editing and versions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_partial_edit_leaves_the_unsent_fields_alone(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await add_customer(client, owner, tenant, notes="Pays on delivery")
        updated = await client.patch(
            customers_path(tenant["id"], created["customer"]["id"]),
            headers=auth(owner),
            json={"name": "Ada N. Obi"},
        )

    body = updated.json()
    assert updated.status_code == 200, updated.text
    assert body["name"] == "Ada N. Obi"
    assert body["phone"] == created["customer"]["phone"]
    assert body["notes"] == "Pays on delivery"
    assert body["version"] == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_clearing_a_phone_number_by_sending_null(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await add_customer(client, owner, tenant)
        cleared = await client.patch(
            customers_path(tenant["id"], created["customer"]["id"]),
            headers=auth(owner),
            json={"phone": None},
        )

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["phone"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_stale_version_is_a_conflict_and_names_nothing_internal(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await add_customer(client, owner, tenant, notes="First")
        await client.patch(
            customers_path(tenant["id"], created["customer"]["id"]),
            headers=auth(owner),
            json={"notes": "Phone A's note"},
        )
        stale = await client.patch(
            customers_path(tenant["id"], created["customer"]["id"]),
            headers=auth(owner),
            json={"notes": "Phone B's note", "version": 1},
        )

    assert stale.status_code == 409
    body = stale.json()
    assert body["error"]["code"] == "CONFLICT"
    assert body["error"]["correlation_id"]
    for internal in ("customers", "UPDATE", "sqlalchemy", "tenant_id", "expected version"):
        assert internal not in stale.text, f"the response leaked {internal}"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_edit_with_a_number_for_a_boolean_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await add_customer(client, owner, tenant)
        response = await client.patch(
            customers_path(tenant["id"], created["customer"]["id"]),
            headers=auth(owner),
            json={"marketing_opt_in": "yes"},
        )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Withdrawal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_withdrawing_a_customer_keeps_them_and_hides_them(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await add_customer(client, owner, tenant, notes="Pays on delivery")
        retired = await client.delete(
            customers_path(tenant["id"], created["customer"]["id"]), headers=auth(owner)
        )
        listed = await client.get(customers_path(tenant["id"]), headers=auth(owner))
        everything = await client.get(
            customers_path(tenant["id"]),
            headers=auth(owner),
            params={"include_inactive": "true"},
        )
        revived = await client.post(
            customers_path(tenant["id"], created["customer"]["id"], "reactivate"),
            headers=auth(owner),
        )

    assert retired.status_code == 200, retired.text
    assert retired.json()["is_active"] is False
    assert retired.json()["notes"] == "Pays on delivery"
    assert listed.json() == []
    assert len(everything.json()) == 1
    assert revived.json()["is_active"] is True


# ---------------------------------------------------------------------------
# Tenancy and authorization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_customer_of_another_business_is_not_found(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await add_customer(client, owner, tenant)

        outsider = await register(client)
        outsider_tenant = await client.post(
            "/api/v1/tenants", headers=auth(outsider), json={"name": "Somewhere Else"}
        )
        response = await client.get(
            customers_path(outsider_tenant.json()["id"], created["customer"]["id"]),
            headers=auth(outsider),
        )

    assert response.status_code == 404
    assert "Ada" not in response.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_salesperson_can_record_and_read_customers(database: Database) -> None:
    async with running_application() as (client, application):
        _owner, tenant = await owner_with_business(client)
        worker = await register(client)
        membership = TenantMembershipModel.activate_immediately(
            membership_id=uuid4(),
            tenant_id=UUID(tenant["id"]),
            user_id=UUID(worker["user"]["id"]),
            role_name="SALES",
            now=datetime.now(UTC),
        )
        async with application.state.container.database.transaction_scope() as unit_of_work:
            await tenant_membership_crud.create(unit_of_work.session_handle, membership)
            await unit_of_work.commit()

        recorded = await client.post(
            customers_path(tenant["id"]),
            headers=auth(worker),
            json={"name": "Ada Obi", "phone": "0803 123 4567"},
        )
        listed = await client.get(customers_path(tenant["id"]), headers=auth(worker))
        refused = await client.patch(
            customers_path(tenant["id"], recorded.json()["customer"]["id"]),
            headers=auth(worker),
            json={"name": "Someone else"},
        )

    assert recorded.status_code == 201, recorded.text
    assert listed.status_code == 200
    assert refused.status_code == 403


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unauthenticated_request_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        _owner, tenant = await owner_with_business(client)
        # No credentials at all: the setup above signed somebody in, and a browser would send that
        # session cookie. An unauthenticated caller is one with neither a header nor a cookie.
        client.cookies.clear()
        response = await client.get(customers_path(tenant["id"]))

    assert response.status_code == 401
