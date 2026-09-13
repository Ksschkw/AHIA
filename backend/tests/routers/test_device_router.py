"""End-to-end tests for devices.

Real PostgreSQL, real sessions, real permission checks. The property that matters
most is the one at the end: revoking a device ends the sessions bound to it, which
is what makes "I lost my phone" an action rather than a hope.
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
from ahia.crud import session_crud, tenant_membership_crud
from ahia.crud.device_crud import DeviceRecord
from ahia.crud.session_crud import SessionRecord
from ahia.crud.tenant_crud import TenantRecord
from ahia.crud.tenant_membership_crud import TenantMembershipRecord
from ahia.crud.user_crud import UserRecord
from ahia.main import create_application
from ahia.models.entities.tenant_membership_model import TenantMembershipModel

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
PASSWORD = "a-good-enough-password"

TABLE_RECORDS = (
    UserRecord,
    SessionRecord,
    TenantRecord,
    TenantMembershipRecord,
    DeviceRecord,
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
            text(
                "TRUNCATE TABLE devices, tenant_memberships, tenants, user_sessions, users CASCADE"
            )
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


def device_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "device_identifier": f"installation-{uuid4().hex[:12]}",
        "platform": "android",
        "device_name": "Obi's phone",
        "app_version": "1.0.0",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Registration and heartbeat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_registering_a_device_returns_it_without_the_identifier(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        payload = device_payload()
        response = await client.post(
            f"/api/v1/tenants/{tenant['id']}/devices", headers=auth(owner), json=payload
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["platform"] == "android"
    assert body["device_name"] == "Obi's phone"
    assert body["is_revoked"] is False
    assert body["first_seen_at"] == body["last_seen_at"]
    assert payload["device_identifier"] not in response.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_registering_the_same_installation_again_is_a_heartbeat(
    database: Database,
) -> None:
    """A client cannot tell its first launch from its hundredth."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        payload = device_payload()

        first = await client.post(
            f"/api/v1/tenants/{tenant['id']}/devices", headers=auth(owner), json=payload
        )
        second = await client.post(
            f"/api/v1/tenants/{tenant['id']}/devices",
            headers=auth(owner),
            json={**payload, "app_version": "1.1.0"},
        )
        listed = await client.get(f"/api/v1/tenants/{tenant['id']}/devices", headers=auth(owner))

    assert first.json()["id"] == second.json()["id"]
    assert second.json()["app_version"] == "1.1.0"
    assert len(listed.json()) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unknown_platform_is_rejected(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        response = await client.post(
            f"/api/v1/tenants/{tenant['id']}/devices",
            headers=auth(owner),
            json=device_payload(platform="windows"),
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_member_cannot_claim_another_members_device(database: Database) -> None:
    """The same installation presented by a second person is a claim, not a registration."""
    async with running_application() as (client, application):
        owner, tenant = await owner_with_business(client)
        worker = await register(client)
        database_instance = application.state.container.database
        await add_member(
            database_instance,
            tenant_id=UUID(tenant["id"]),
            user_id=UUID(worker["user"]["id"]),
            role_name="SALES",
        )

        payload = device_payload()
        await client.post(
            f"/api/v1/tenants/{tenant['id']}/devices", headers=auth(owner), json=payload
        )
        claim = await client.post(
            f"/api/v1/tenants/{tenant['id']}/devices", headers=auth(worker), json=payload
        )

    assert claim.status_code == 409
    assert claim.json()["error"]["code"] == "CONFLICT"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_same_identifier_in_two_businesses_is_two_devices(database: Database) -> None:
    """The identifier is opaque, so uniqueness is per business."""
    async with running_application() as (client, _application):
        first_owner, first_tenant = await owner_with_business(client)
        second_owner, second_tenant = await owner_with_business(client)
        identifier = f"shared-{uuid4().hex[:12]}"

        first = await client.post(
            f"/api/v1/tenants/{first_tenant['id']}/devices",
            headers=auth(first_owner),
            json=device_payload(device_identifier=identifier),
        )
        second = await client.post(
            f"/api/v1/tenants/{second_tenant['id']}/devices",
            headers=auth(second_owner),
            json=device_payload(device_identifier=identifier),
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


# ---------------------------------------------------------------------------
# Listing and permissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_salesperson_cannot_list_the_businesss_devices(database: Database) -> None:
    async with running_application() as (client, application):
        _owner, tenant = await owner_with_business(client)
        worker = await register(client)
        await add_member(
            application.state.container.database,
            tenant_id=UUID(tenant["id"]),
            user_id=UUID(worker["user"]["id"]),
            role_name="SALES",
        )

        business_list = await client.get(
            f"/api/v1/tenants/{tenant['id']}/devices", headers=auth(worker)
        )
        own_list = await client.get(
            f"/api/v1/tenants/{tenant['id']}/devices/mine", headers=auth(worker)
        )

    assert business_list.status_code == 403
    assert own_list.status_code == 200, "a person may always see their own devices"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_device_from_another_business_is_unreachable(database: Database) -> None:
    async with running_application() as (client, _application):
        first_owner, first_tenant = await owner_with_business(client)
        second_owner, second_tenant = await owner_with_business(client)

        created = await client.post(
            f"/api/v1/tenants/{second_tenant['id']}/devices",
            headers=auth(second_owner),
            json=device_payload(),
        )
        attempt = await client.delete(
            f"/api/v1/tenants/{first_tenant['id']}/devices/{created.json()['id']}",
            headers=auth(first_owner),
        )

    assert attempt.status_code == 404
    assert attempt.json()["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Revocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_revoking_a_device_ends_the_sessions_bound_to_it(database: Database) -> None:
    """The property that makes "I lost my phone" an action rather than a hope."""
    async with running_application() as (client, application):
        owner, tenant = await owner_with_business(client)
        database_instance = application.state.container.database

        # Bind the owner's session to a device, as a real client would. The
        # identifier is kept, because re-presenting the same installation is the
        # behaviour under test.
        payload = device_payload()
        device = await client.post(
            f"/api/v1/tenants/{tenant['id']}/devices",
            headers=auth(owner),
            json=payload,
        )
        device_id = UUID(device.json()["id"])
        async with database_instance.transaction_scope() as unit_of_work:
            sessions = await session_crud.list_active_for_user(
                unit_of_work.session_handle,
                user_id=UUID(owner["user"]["id"]),
                at=datetime.now(UTC),
            )
            for session in sessions:
                await session_crud.update(
                    unit_of_work.session_handle, session.bind_to_device(device_id=device_id)
                )
            await unit_of_work.commit()

        revoked = await client.delete(
            f"/api/v1/tenants/{tenant['id']}/devices/{device_id}", headers=auth(owner)
        )
        refresh_after_revocation = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": owner["refresh_token"]}
        )
        register_again = await client.post(
            f"/api/v1/tenants/{tenant['id']}/devices",
            headers=auth(owner),
            json=payload,
        )

    assert revoked.status_code == 200
    assert revoked.json()["device"]["is_revoked"] is True
    assert revoked.json()["sessions_ended"] >= 1
    assert refresh_after_revocation.status_code == 401, "the phone cannot renew itself"
    assert register_again.status_code == 422, "a revoked installation must not return"
    assert register_again.json()["error"]["code"] == "BUSINESS_RULE_VIOLATION"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_revoking_someone_elses_device_needs_the_permission(database: Database) -> None:
    async with running_application() as (client, application):
        owner, tenant = await owner_with_business(client)
        worker = await register(client)
        database_instance = application.state.container.database
        await add_member(
            database_instance,
            tenant_id=UUID(tenant["id"]),
            user_id=UUID(worker["user"]["id"]),
            role_name="SALES",
        )

        device = await client.post(
            f"/api/v1/tenants/{tenant['id']}/devices",
            headers=auth(owner),
            json=device_payload(),
        )
        by_worker = await client.delete(
            f"/api/v1/tenants/{tenant['id']}/devices/{device.json()['id']}",
            headers=auth(worker),
        )
        by_owner = await client.delete(
            f"/api/v1/tenants/{tenant['id']}/devices/{device.json()['id']}",
            headers=auth(owner),
        )

    assert by_worker.status_code == 403, "SALES holds no devices.revoke"
    assert by_owner.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_member_can_revoke_their_own_device_without_a_permission(
    database: Database,
) -> None:
    """Signing your own phone out must always be available."""
    async with running_application() as (client, application):
        _owner, tenant = await owner_with_business(client)
        worker = await register(client)
        await add_member(
            application.state.container.database,
            tenant_id=UUID(tenant["id"]),
            user_id=UUID(worker["user"]["id"]),
            role_name="SALES",
        )

        device = await client.post(
            f"/api/v1/tenants/{tenant['id']}/devices",
            headers=auth(worker),
            json=device_payload(),
        )
        revoked = await client.delete(
            f"/api/v1/tenants/{tenant['id']}/devices/{device.json()['id']}",
            headers=auth(worker),
        )

    assert device.status_code == 201
    assert revoked.status_code == 200
    assert revoked.json()["device"]["is_revoked"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_device_routes_require_authentication(database: Database) -> None:
    async with running_application() as (client, _application):
        tenant_id = uuid4()
        responses = [
            await client.post(
                f"/api/v1/tenants/{tenant_id}/devices",
                json={"device_identifier": "installation-12345678", "platform": "android"},
            ),
            await client.get(f"/api/v1/tenants/{tenant_id}/devices"),
            await client.get(f"/api/v1/tenants/{tenant_id}/devices/mine"),
            await client.delete(f"/api/v1/tenants/{tenant_id}/devices/{uuid4()}"),
        ]

    assert [response.status_code for response in responses] == [401] * 4
