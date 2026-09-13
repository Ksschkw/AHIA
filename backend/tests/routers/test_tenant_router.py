"""End-to-end tests for the tenant slice.

Real PostgreSQL, real membership resolution, real permission checks. The tests
follow the product's own first-run journey and then attack it: another user
asking for the same business, a salesperson trying to change the business
profile, and a member whose access was suspended.
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
from sqlalchemy import select, text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.crud import tenant_membership_crud
from ahia.crud.tenant_membership_crud import TenantMembershipRecord
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


@asynccontextmanager
async def running_application(settings: Settings | None = None) -> AsyncIterator[Any]:
    application = create_application(settings or build_settings())
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="https://testserver") as client:
            yield client, application


@pytest.fixture
async def tables() -> AsyncIterator[None]:
    """Create every table the slice touches and empty them around each test."""
    database = Database(build_settings())
    async with database.engine.begin() as connection:
        # The whole schema, created from the models. A table's foreign keys require
        # the tables they reference to exist first, and creating everything in
        # dependency order is exactly what create_all does.
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(sync_connection, checkfirst=True)
        )
        await connection.execute(
            text("TRUNCATE TABLE tenant_memberships, tenants, user_sessions, users CASCADE")
        )
    try:
        yield
    finally:
        await database.dispose()


async def register(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "first_name": "Emeka",
        "last_name": "Okonkwo",
        "email": f"emeka.{uuid4().hex[:8]}@example.com",
        "password": PASSWORD,
    }
    payload.update(overrides)
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def auth(session_payload: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_payload['access_token']}"}


async def add_member(
    application: Any,
    *,
    tenant_id: UUID,
    user_id: UUID,
    role_name: str,
) -> TenantMembershipModel:
    """Insert a membership directly, for cases the product cannot reach yet."""
    database = application.state.container.database
    membership = TenantMembershipModel.activate_immediately(
        membership_id=uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        role_name=role_name,
        now=datetime.now(UTC),
    )
    async with database.transaction_scope() as unit_of_work:
        session = unit_of_work.session_handle
        await tenant_membership_crud.create(session, membership)
        await unit_of_work.commit()
    return membership


# ---------------------------------------------------------------------------
# The first-run journey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_first_run_journey(tables: None) -> None:
    """Register, create a business, see it listed, read it, rename it."""
    async with running_application() as (client, _application):
        owner = await register(client)

        created = await client.post(
            "/api/v1/tenants",
            headers=auth(owner),
            json={"name": "Obi Electronics", "city": "Lagos", "business_type": "Electronics"},
        )
        assert created.status_code == 201, created.text
        tenant = created.json()
        assert tenant["slug"] == "obi-electronics"
        assert tenant["public_path"] == "/shop/obi-electronics"
        assert tenant["currency"] == "NGN"
        assert tenant["timezone"] == "Africa/Lagos"

        listed = await client.get("/api/v1/tenants", headers=auth(owner))
        assert listed.status_code == 200
        assert [entry["id"] for entry in listed.json()] == [tenant["id"]]
        assert listed.json()[0]["role_name"] == "OWNER"

        read = await client.get(f"/api/v1/tenants/{tenant['id']}", headers=auth(owner))
        assert read.status_code == 200
        assert read.json()["name"] == "Obi Electronics"

        renamed = await client.patch(
            f"/api/v1/tenants/{tenant['id']}",
            headers=auth(owner),
            json={"name": "Obi Home Appliances"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "Obi Home Appliances"
        assert renamed.json()["slug"] == "obi-electronics", "a published slug must not change"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_creating_a_business_makes_the_caller_its_owner(tables: None) -> None:
    """One transaction: a business without an owner would be unreachable."""
    async with running_application() as (client, application):
        owner = await register(client)
        created = await client.post(
            "/api/v1/tenants", headers=auth(owner), json={"name": "Chukwu Appliances"}
        )
        tenant_id = UUID(created.json()["id"])

        database = application.state.container.database
        async with database.transaction_scope() as unit_of_work:
            result = await unit_of_work.session_handle.execute(
                select(TenantMembershipRecord.role_name, TenantMembershipRecord.status).where(
                    TenantMembershipRecord.tenant_id == tenant_id
                )
            )
            rows = [tuple(row) for row in result.all()]

    assert rows == [("OWNER", "active")]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_slug_is_derived_from_the_name_and_nudged_when_taken(tables: None) -> None:
    """A person never chose the derived slug, so an address beats an error."""
    async with running_application() as (client, _application):
        first = await register(client)
        second = await register(client)

        await client.post("/api/v1/tenants", headers=auth(first), json={"name": "XYZ Traders"})
        second_attempt = await client.post(
            "/api/v1/tenants", headers=auth(second), json={"name": "XYZ Traders"}
        )

    assert second_attempt.status_code == 201
    assert second_attempt.json()["slug"] == "xyz-traders-2"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_requested_slug_that_is_taken_is_a_conflict(tables: None) -> None:
    """The person chose this one, so being told beats silently receiving another."""
    async with running_application() as (client, _application):
        first = await register(client)
        second = await register(client)

        await client.post(
            "/api/v1/tenants",
            headers=auth(first),
            json={"name": "Obi Electronics", "slug": "obi-electronics"},
        )
        collision = await client.post(
            "/api/v1/tenants",
            headers=auth(second),
            json={"name": "Another Shop", "slug": "obi-electronics"},
        )

    assert collision.status_code == 409
    assert collision.json()["error"]["code"] == "CONFLICT"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_reserved_slug_is_rejected_and_the_list_stays_private(tables: None) -> None:
    """Rejected as an invalid request, without publishing which names are reserved.

    The error envelope is three fields for every failure in this product, so a
    validation failure says that the request was invalid and nothing about the
    rule that was applied or the value that was sent. A client validates the slug
    shape locally and offers alternatives; it does not need our reserved list.
    """
    async with running_application() as (client, _application):
        owner = await register(client)
        response = await client.post(
            "/api/v1/tenants",
            headers=auth(owner),
            json={"name": "Admin Shop", "slug": "admin"},
        )
        allowed = await client.post(
            "/api/v1/tenants",
            headers=auth(owner),
            json={"name": "Admin Shop", "slug": "admin-shop"},
        )

    assert response.status_code == 422
    assert set(response.json()["error"]) == {"code", "message", "correlation_id"}
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert "admin" not in response.json()["error"]["message"]
    # The same name with an eligible slug is accepted, so the rule is about the
    # slug and not about the word.
    assert allowed.status_code == 201
    assert allowed.json()["slug"] == "admin-shop"


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_stranger_cannot_read_another_business(tables: None) -> None:
    """Denied exactly as if the business did not exist, so identifiers cannot be probed."""
    async with running_application() as (client, _application):
        owner = await register(client)
        stranger = await register(client)
        created = await client.post(
            "/api/v1/tenants", headers=auth(owner), json={"name": "Obi Electronics"}
        )
        tenant_id = created.json()["id"]

        as_stranger = await client.get(f"/api/v1/tenants/{tenant_id}", headers=auth(stranger))
        as_stranger_missing = await client.get(f"/api/v1/tenants/{uuid4()}", headers=auth(stranger))

    assert as_stranger.status_code == 404
    assert as_stranger.json()["error"]["code"] == "NOT_FOUND"
    assert as_stranger.json()["error"]["message"] == as_stranger_missing.json()["error"]["message"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_stranger_cannot_change_another_business(tables: None) -> None:
    async with running_application() as (client, _application):
        owner = await register(client)
        stranger = await register(client)
        created = await client.post(
            "/api/v1/tenants", headers=auth(owner), json={"name": "Obi Electronics"}
        )

        attempt = await client.patch(
            f"/api/v1/tenants/{created.json()['id']}",
            headers=auth(stranger),
            json={"name": "Mine Now"},
        )

    assert attempt.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_list_only_contains_the_callers_businesses(tables: None) -> None:
    async with running_application() as (client, _application):
        first = await register(client)
        second = await register(client)
        await client.post("/api/v1/tenants", headers=auth(first), json={"name": "First Shop"})
        await client.post("/api/v1/tenants", headers=auth(second), json={"name": "Second Shop"})

        first_list = await client.get("/api/v1/tenants", headers=auth(first))
        second_list = await client.get("/api/v1/tenants", headers=auth(second))

    assert [entry["name"] for entry in first_list.json()] == ["First Shop"]
    assert [entry["name"] for entry in second_list.json()] == ["Second Shop"]


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_salesperson_cannot_change_the_business_profile(tables: None) -> None:
    """The role decides, and the service decides on every request."""
    async with running_application() as (client, application):
        owner = await register(client)
        salesperson = await register(client)
        created = await client.post(
            "/api/v1/tenants", headers=auth(owner), json={"name": "Obi Electronics"}
        )
        tenant_id = UUID(created.json()["id"])
        salesperson_id = UUID(salesperson["user"]["id"])
        await add_member(
            application, tenant_id=tenant_id, user_id=salesperson_id, role_name="SALES"
        )

        readable = await client.get(f"/api/v1/tenants/{tenant_id}", headers=auth(salesperson))
        writable = await client.patch(
            f"/api/v1/tenants/{tenant_id}",
            headers=auth(salesperson),
            json={"name": "Renamed By Sales"},
        )

    assert readable.status_code == 200, "a salesperson may read the business they work in"
    assert readable.json()["name"] == "Obi Electronics"
    assert writable.status_code == 403
    assert writable.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_only_an_owner_can_close_the_business(tables: None) -> None:
    """Deactivation takes everybody's access away, so it is the owner's alone."""
    async with running_application() as (client, application):
        owner = await register(client)
        manager = await register(client)
        created = await client.post(
            "/api/v1/tenants", headers=auth(owner), json={"name": "Obi Electronics"}
        )
        tenant_id = UUID(created.json()["id"])
        await add_member(
            application,
            tenant_id=tenant_id,
            user_id=UUID(manager["user"]["id"]),
            role_name="MANAGER",
        )

        by_manager = await client.delete(f"/api/v1/tenants/{tenant_id}", headers=auth(manager))
        by_owner = await client.delete(f"/api/v1/tenants/{tenant_id}", headers=auth(owner))

    assert by_manager.status_code == 403
    assert by_owner.status_code == 200
    assert by_owner.json()["is_active"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_suspended_member_loses_access_immediately(tables: None) -> None:
    async with running_application() as (client, application):
        owner = await register(client)
        worker = await register(client)
        created = await client.post(
            "/api/v1/tenants", headers=auth(owner), json={"name": "Obi Electronics"}
        )
        tenant_id = UUID(created.json()["id"])
        membership = await add_member(
            application, tenant_id=tenant_id, user_id=UUID(worker["user"]["id"]), role_name="SALES"
        )

        before = await client.get(f"/api/v1/tenants/{tenant_id}", headers=auth(worker))

        database = application.state.container.database
        async with database.transaction_scope() as unit_of_work:
            suspended = membership.suspend(at=datetime.now(UTC))
            await tenant_membership_crud.update(unit_of_work.session_handle, suspended)
            await unit_of_work.commit()

        after = await client.get(f"/api/v1/tenants/{tenant_id}", headers=auth(worker))

    assert before.status_code == 200
    assert after.status_code == 404, "a suspension takes effect on the next request"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_closed_business_stops_answering(tables: None) -> None:
    async with running_application() as (client, _application):
        owner = await register(client)
        created = await client.post(
            "/api/v1/tenants", headers=auth(owner), json={"name": "Obi Electronics"}
        )
        tenant_id = created.json()["id"]

        await client.delete(f"/api/v1/tenants/{tenant_id}", headers=auth(owner))
        after_close = await client.get(f"/api/v1/tenants/{tenant_id}", headers=auth(owner))

    assert after_close.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_authentication_is_required_for_every_tenant_route(tables: None) -> None:
    async with running_application() as (client, _application):
        responses = [
            await client.post("/api/v1/tenants", json={"name": "No Auth Shop"}),
            await client.get("/api/v1/tenants"),
            await client.get(f"/api/v1/tenants/{uuid4()}"),
            await client.patch(f"/api/v1/tenants/{uuid4()}", json={"name": "X"}),
            await client.delete(f"/api/v1/tenants/{uuid4()}"),
        ]

    assert [response.status_code for response in responses] == [401] * 5


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_slug_cannot_be_changed_through_a_profile_update(tables: None) -> None:
    async with running_application() as (client, _application):
        owner = await register(client)
        created = await client.post(
            "/api/v1/tenants", headers=auth(owner), json={"name": "Obi Electronics"}
        )
        tenant_id = created.json()["id"]

        attempt = await client.patch(
            f"/api/v1/tenants/{tenant_id}",
            headers=auth(owner),
            json={"slug": "new-slug"},
        )

    assert attempt.status_code == 422
    assert attempt.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_tenant_errors_disclose_nothing_internal(tables: None) -> None:
    async with running_application() as (client, _application):
        owner = await register(client)
        await client.post("/api/v1/tenants", headers=auth(owner), json={"name": "Obi Electronics"})
        response = await client.get(f"/api/v1/tenants/{uuid4()}", headers=auth(owner))

    lowered = response.text.lower()
    for forbidden in ("sqlalchemy", "asyncpg", "traceback", "select ", "/home/", "membership"):
        assert forbidden not in lowered
    assert set(response.json()["error"]) == {"code", "message", "correlation_id"}
