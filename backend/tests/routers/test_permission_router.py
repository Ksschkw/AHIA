"""End-to-end tests for the IAM surface.

The catalogue and the roles are exercised through HTTP with real PostgreSQL, real
membership resolution and real permission checks, because the interesting
properties are about who may see and change what.
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
from ahia.core.permissions.permissions_registry import ALL_PERMISSIONS, SYSTEM_ROLES
from ahia.crud import tenant_membership_crud
from ahia.crud.permission_crud import PermissionRecord
from ahia.crud.role_crud import RoleRecord
from ahia.crud.role_permission_crud import RolePermissionRecord
from ahia.crud.session_crud import SessionRecord
from ahia.crud.tenant_crud import TenantRecord
from ahia.crud.tenant_membership_crud import TenantMembershipRecord
from ahia.crud.user_crud import UserRecord
from ahia.main import create_application
from ahia.models.entities.tenant_membership_model import TenantMembershipModel
from ahia.services.iam_seed_service import IamSeedService

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
PASSWORD = "a-good-enough-password"

TABLE_RECORDS = (
    UserRecord,
    SessionRecord,
    TenantRecord,
    TenantMembershipRecord,
    RoleRecord,
    PermissionRecord,
    RolePermissionRecord,
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
                "TRUNCATE TABLE role_permissions, roles, permissions, tenant_memberships, "
                "tenants, user_sessions, users CASCADE"
            )
        )
    # The registry is provisioned before the application starts, exactly as a
    # deployment would do it.
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


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_catalogue_lists_every_declared_permission(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        response = await client.get(
            f"/api/v1/tenants/{tenant['id']}/permissions", headers=auth(owner)
        )

    assert response.status_code == 200
    codes = {entry["code"] for entry in response.json()}
    assert codes == {definition.code for definition in ALL_PERMISSIONS}
    assert all(entry["module"] for entry in response.json())


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_roles_list_matches_the_registry(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        response = await client.get(f"/api/v1/tenants/{tenant['id']}/roles", headers=auth(owner))

    assert response.status_code == 200
    by_name = {entry["name"]: entry for entry in response.json()}
    assert set(by_name) == set(SYSTEM_ROLES)
    assert set(by_name["OWNER"]["permission_codes"]) == {
        definition.code for definition in ALL_PERMISSIONS
    }
    assert "reports.read" not in by_name["SALES"]["permission_codes"]
    assert by_name["SALES"]["is_system_role"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_ordinary_member_may_read_the_catalogue(database: Database) -> None:
    """A person cannot judge a role they are given without knowing what it means."""
    async with running_application() as (client, application):
        _owner, tenant = await owner_with_business(client)
        worker = await register(client)
        await add_member(
            application.state.container.database,
            tenant_id=UUID(tenant["id"]),
            user_id=UUID(worker["user"]["id"]),
            role_name="SALES",
        )

        permissions = await client.get(
            f"/api/v1/tenants/{tenant['id']}/permissions", headers=auth(worker)
        )
        roles = await client.get(f"/api/v1/tenants/{tenant['id']}/roles", headers=auth(worker))

    assert permissions.status_code == 200
    assert roles.status_code == 200
    assert len(permissions.json()) == len(ALL_PERMISSIONS)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_stranger_cannot_read_another_businesss_roles(database: Database) -> None:
    async with running_application() as (client, _application):
        _owner, tenant = await owner_with_business(client)
        stranger = await register(client)
        response = await client.get(f"/api/v1/tenants/{tenant['id']}/roles", headers=auth(stranger))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Custom roles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_owner_can_create_a_role_for_their_business(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await client.post(
            f"/api/v1/tenants/{tenant['id']}/roles",
            headers=auth(owner),
            json={
                "name": "supervisor",
                "description": "Watches the shop",
                "permission_codes": ["products.read", "inventory.read"],
            },
        )
        listed = await client.get(f"/api/v1/tenants/{tenant['id']}/roles", headers=auth(owner))

    assert created.status_code == 201, created.text
    assert created.json()["name"] == "SUPERVISOR", "role names are normalized to uppercase"
    assert created.json()["is_system_role"] is False
    assert created.json()["permission_codes"] == ["inventory.read", "products.read"]

    custom = [entry for entry in listed.json() if not entry["is_system_role"]]
    assert [entry["name"] for entry in custom] == ["SUPERVISOR"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_custom_role_is_invisible_to_another_business(database: Database) -> None:
    async with running_application() as (client, _application):
        first_owner, first_tenant = await owner_with_business(client)
        second_owner, second_tenant = await owner_with_business(client)

        await client.post(
            f"/api/v1/tenants/{first_tenant['id']}/roles",
            headers=auth(first_owner),
            json={
                "name": "SUPERVISOR",
                "description": "First business only",
                "permission_codes": ["products.read"],
            },
        )
        listed_elsewhere = await client.get(
            f"/api/v1/tenants/{second_tenant['id']}/roles", headers=auth(second_owner)
        )

    assert [entry["name"] for entry in listed_elsewhere.json()] == sorted(SYSTEM_ROLES)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_member_cannot_create_a_role(database: Database) -> None:
    async with running_application() as (client, application):
        _owner, tenant = await owner_with_business(client)
        worker = await register(client)
        await add_member(
            application.state.container.database,
            tenant_id=UUID(tenant["id"]),
            user_id=UUID(worker["user"]["id"]),
            role_name="SALES",
        )

        response = await client.post(
            f"/api/v1/tenants/{tenant['id']}/roles",
            headers=auth(worker),
            json={
                "name": "SUPERVISOR",
                "description": "Not allowed",
                "permission_codes": ["products.read"],
            },
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_manager_cannot_grant_what_they_do_not_hold(database: Database) -> None:
    """The escalation rule, through the API rather than the service."""
    async with running_application() as (client, application):
        _owner, tenant = await owner_with_business(client)
        manager = await register(client)
        await add_member(
            application.state.container.database,
            tenant_id=UUID(tenant["id"]),
            user_id=UUID(manager["user"]["id"]),
            role_name="MANAGER",
        )

        response = await client.post(
            f"/api/v1/tenants/{tenant['id']}/roles",
            headers=auth(manager),
            json={
                "name": "SUPERVISOR",
                "description": "An attempt to grant more than the caller holds",
                "permission_codes": ["tenants.deactivate"],
            },
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_role_name_may_not_shadow_a_system_role(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        response = await client.post(
            f"/api/v1/tenants/{tenant['id']}/roles",
            headers=auth(owner),
            json={
                "name": "OWNER",
                "description": "An attempt to redefine the owner",
                "permission_codes": ["products.read"],
            },
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_role_must_grant_something(database: Database) -> None:
    """A role that grants nothing is a mistake, and the edge says so."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        response = await client.post(
            f"/api/v1/tenants/{tenant['id']}/roles",
            headers=auth(owner),
            json={
                "name": "EMPTY",
                "description": "Grants nothing",
                "permission_codes": [],
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_custom_roles_permissions_can_be_replaced(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        await client.post(
            f"/api/v1/tenants/{tenant['id']}/roles",
            headers=auth(owner),
            json={
                "name": "SUPERVISOR",
                "description": "Watches the shop",
                "permission_codes": ["products.read"],
            },
        )

        updated = await client.patch(
            f"/api/v1/tenants/{tenant['id']}/roles/SUPERVISOR/permissions",
            headers=auth(owner),
            json={"permission_codes": ["products.read", "reports.read"]},
        )

    assert updated.status_code == 200
    assert updated.json()["permission_codes"] == ["products.read", "reports.read"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_system_role_cannot_be_edited(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        response = await client.patch(
            f"/api/v1/tenants/{tenant['id']}/roles/SALES/permissions",
            headers=auth(owner),
            json={"permission_codes": ["tenants.deactivate"]},
        )
        listed = await client.get(f"/api/v1/tenants/{tenant['id']}/roles", headers=auth(owner))

    assert response.status_code == 404
    sales = next(entry for entry in listed.json() if entry["name"] == "SALES")
    assert "tenants.deactivate" not in sales["permission_codes"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_iam_routes_require_authentication(database: Database) -> None:
    async with running_application() as (client, _application):
        tenant_id = uuid4()
        responses = [
            await client.get(f"/api/v1/tenants/{tenant_id}/permissions"),
            await client.get(f"/api/v1/tenants/{tenant_id}/roles"),
            await client.post(
                f"/api/v1/tenants/{tenant_id}/roles",
                json={"name": "X", "description": "y", "permission_codes": ["products.read"]},
            ),
        ]

    assert [response.status_code for response in responses] == [401] * 3
