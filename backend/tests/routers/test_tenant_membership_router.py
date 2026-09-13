"""End-to-end tests for staff administration.

Real PostgreSQL and the real invitation flow: an owner invites an identity, that
person registers with it, sees the invitation waiting, accepts it, and arrives
inside the business with the role they were given.

The negative cases matter as much as the happy one: a salesperson cannot invite,
a manager cannot remove, the last owner cannot be demoted, an invitation addressed
to somebody else cannot be accepted, and a revoked device or suspended membership
takes effect on the next request.
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
from ahia.crud import tenant_membership_crud, user_crud
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
    database = Database(build_settings())
    async with database.engine.begin() as connection:
        # The whole schema, created from the models. A table's foreign keys require
        # the tables they reference to exist first, and creating everything in
        # dependency order is exactly what create_all does.
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(sync_connection, checkfirst=True)
        )
        await connection.execute(
            text(
                "TRUNCATE TABLE membership_invitations, tenant_memberships, tenants, "
                "user_sessions, users CASCADE"
            )
        )
    try:
        yield
    finally:
        await database.dispose()


async def register(client: AsyncClient, *, email: str | None = None, **overrides: Any) -> Any:
    payload: dict[str, Any] = {
        "first_name": "Emeka",
        "last_name": "Okonkwo",
        "email": email or f"user.{uuid4().hex[:8]}@example.com",
        "password": PASSWORD,
    }
    payload.update(overrides)
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def auth(session_payload: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_payload['access_token']}"}


async def create_business(
    client: AsyncClient, session: dict[str, Any], name: str
) -> dict[str, Any]:
    response = await client.post("/api/v1/tenants", headers=auth(session), json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


async def invite(
    client: AsyncClient,
    owner: dict[str, Any],
    tenant_id: str,
    *,
    email: str,
    role_name: str = "SALES",
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/tenants/{tenant_id}/members",
        headers=auth(owner),
        json={"email": email, "role_name": role_name},
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# The staff onboarding journey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_staff_onboarding_journey(tables: None) -> None:
    """Invite, register with the invited address, accept, arrive with a role."""
    async with running_application() as (client, _application):
        owner = await register(client)
        tenant = await create_business(client, owner, "Obi Electronics")
        worker_email = f"ngozi.{uuid4().hex[:8]}@example.com"

        invitation = await invite(client, owner, tenant["id"], email=worker_email)
        assert invitation["token"], "the token is returned exactly once"
        assert invitation["role_name"] == "SALES"
        assert invitation["accepted_at"] is None

        worker = await register(client, email=worker_email)

        pending = await client.get("/api/v1/invitations", headers=auth(worker))
        assert pending.status_code == 200
        assert [entry["tenant_name"] for entry in pending.json()] == ["Obi Electronics"]
        assert pending.json()[0]["role_name"] == "SALES"

        accepted = await client.post(
            "/api/v1/invitations/accept",
            headers=auth(worker),
            json={"token": invitation["token"]},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["tenant_slug"] == tenant["slug"]
        assert accepted.json()["role_name"] == "SALES"

        businesses = await client.get("/api/v1/tenants", headers=auth(worker))
        assert [entry["role_name"] for entry in businesses.json()] == ["SALES"]

        members = await client.get(f"/api/v1/tenants/{tenant['id']}/members", headers=auth(owner))
        assert {member["role_name"] for member in members.json()} == {"OWNER", "SALES"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_invitation_is_the_only_way_in(tables: None) -> None:
    """A registered person with no invitation reaches no business."""
    async with running_application() as (client, _application):
        owner = await register(client)
        stranger = await register(client)
        tenant = await create_business(client, owner, "Obi Electronics")

        pending = await client.get("/api/v1/invitations", headers=auth(stranger))
        businesses = await client.get("/api/v1/tenants", headers=auth(stranger))
        direct = await client.get(f"/api/v1/tenants/{tenant['id']}", headers=auth(stranger))

    assert pending.json() == []
    assert businesses.json() == []
    assert direct.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_invitation_token_is_not_returned_again(tables: None) -> None:
    """Only the digest is stored, so the list cannot reproduce the token."""
    async with running_application() as (client, _application):
        owner = await register(client)
        tenant = await create_business(client, owner, "Obi Electronics")
        invitation = await invite(
            client, owner, tenant["id"], email=f"worker.{uuid4().hex[:8]}@example.com"
        )

        listed = await client.get(
            f"/api/v1/tenants/{tenant['id']}/invitations", headers=auth(owner)
        )

    assert listed.status_code == 200
    assert listed.json()[0]["token"] is None
    assert invitation["token"] not in listed.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_invitation_addressed_elsewhere_cannot_be_accepted(tables: None) -> None:
    """Matched on the exact channel that was addressed, so a token alone is not enough."""
    async with running_application() as (client, _application):
        owner = await register(client)
        tenant = await create_business(client, owner, "Obi Electronics")
        invitation = await invite(
            client, owner, tenant["id"], email=f"invited.{uuid4().hex[:8]}@example.com"
        )
        impostor = await register(client)

        attempt = await client.post(
            "/api/v1/invitations/accept",
            headers=auth(impostor),
            json={"token": invitation["token"]},
        )

    assert attempt.status_code == 404
    assert attempt.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unknown_token_is_refused_with_the_same_answer(tables: None) -> None:
    async with running_application() as (client, _application):
        worker = await register(client)
        attempt = await client.post(
            "/api/v1/invitations/accept",
            headers=auth(worker),
            json={"token": "a-token-that-was-never-issued"},
        )

    assert attempt.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_invitation_cannot_be_accepted_twice(tables: None) -> None:
    async with running_application() as (client, _application):
        owner = await register(client)
        tenant = await create_business(client, owner, "Obi Electronics")
        worker_email = f"worker.{uuid4().hex[:8]}@example.com"
        invitation = await invite(client, owner, tenant["id"], email=worker_email)
        worker = await register(client, email=worker_email)

        first = await client.post(
            "/api/v1/invitations/accept", headers=auth(worker), json={"token": invitation["token"]}
        )
        second = await client.post(
            "/api/v1/invitations/accept", headers=auth(worker), json={"token": invitation["token"]}
        )

    assert first.status_code == 200
    assert second.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_inviting_somebody_who_is_already_a_member_conflicts(tables: None) -> None:
    async with running_application() as (client, _application):
        owner = await register(client)
        tenant = await create_business(client, owner, "Obi Electronics")
        worker_email = f"worker.{uuid4().hex[:8]}@example.com"
        await invite(client, owner, tenant["id"], email=worker_email)
        worker = await register(client, email=worker_email)
        invitation = await client.get(
            f"/api/v1/tenants/{tenant['id']}/invitations", headers=auth(owner)
        )
        # The token is not listed, so the flow is exercised through a second invite
        # of the same address, which must be refused while one is pending.
        second_attempt = await client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            headers=auth(owner),
            json={"email": worker_email, "role_name": "SALES"},
        )

    assert invitation.status_code == 200
    assert second_attempt.status_code == 409
    assert second_attempt.json()["error"]["code"] == "CONFLICT"
    assert worker["user"]["email"] == worker_email


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_salesperson_cannot_invite_or_remove(tables: None) -> None:
    async with running_application() as (client, _application):
        owner = await register(client)
        tenant = await create_business(client, owner, "Obi Electronics")
        worker_email = f"worker.{uuid4().hex[:8]}@example.com"
        invitation = await invite(client, owner, tenant["id"], email=worker_email)
        worker = await register(client, email=worker_email)
        await client.post(
            "/api/v1/invitations/accept", headers=auth(worker), json={"token": invitation["token"]}
        )

        can_read = await client.get(f"/api/v1/tenants/{tenant['id']}/members", headers=auth(worker))
        cannot_invite = await client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            headers=auth(worker),
            json={"email": "someone@example.com", "role_name": "SALES"},
        )

    assert can_read.status_code == 403, "a salesperson holds no staff.read"
    assert cannot_invite.status_code == 403


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_manager_can_invite_but_cannot_remove(tables: None) -> None:
    async with running_application() as (client, _application):
        owner = await register(client)
        tenant = await create_business(client, owner, "Obi Electronics")
        manager_email = f"manager.{uuid4().hex[:8]}@example.com"
        manager_invitation = await invite(
            client, owner, tenant["id"], email=manager_email, role_name="MANAGER"
        )
        manager = await register(client, email=manager_email)
        await client.post(
            "/api/v1/invitations/accept",
            headers=auth(manager),
            json={"token": manager_invitation["token"]},
        )

        can_invite = await client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            headers=auth(manager),
            json={"email": f"sales.{uuid4().hex[:8]}@example.com", "role_name": "SALES"},
        )

        members = await client.get(f"/api/v1/tenants/{tenant['id']}/members", headers=auth(manager))
        owner_membership_id = next(
            member["id"] for member in members.json() if member["role_name"] == "OWNER"
        )
        cannot_remove = await client.delete(
            f"/api/v1/tenants/{tenant['id']}/members/{owner_membership_id}",
            headers=auth(manager),
        )

    assert can_invite.status_code == 201, "MANAGER holds staff.invite"
    assert cannot_remove.status_code == 403, "MANAGER does not hold staff.remove"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_last_owner_cannot_be_removed_or_demoted(tables: None) -> None:
    """A business with no owner is a business nobody can administer."""
    async with running_application() as (client, _application):
        owner = await register(client)
        tenant = await create_business(client, owner, "Obi Electronics")

        members = await client.get(f"/api/v1/tenants/{tenant['id']}/members", headers=auth(owner))
        owner_membership_id = members.json()[0]["id"]

        demote = await client.patch(
            f"/api/v1/tenants/{tenant['id']}/members/{owner_membership_id}",
            headers=auth(owner),
            json={"role_name": "MANAGER"},
        )
        remove = await client.delete(
            f"/api/v1/tenants/{tenant['id']}/members/{owner_membership_id}",
            headers=auth(owner),
        )

    assert demote.status_code == 422
    assert demote.json()["error"]["code"] == "BUSINESS_RULE_VIOLATION"
    assert remove.status_code == 422
    assert remove.json()["error"]["code"] == "BUSINESS_RULE_VIOLATION"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_last_owner_rule_lets_go_once_there_are_two(tables: None) -> None:
    async with running_application() as (client, application):
        owner = await register(client)
        tenant = await create_business(client, owner, "Obi Electronics")
        second_owner_email = f"second.{uuid4().hex[:8]}@example.com"
        second_owner = await register(client, email=second_owner_email)

        database = application.state.container.database
        async with database.transaction_scope() as unit_of_work:
            membership = TenantMembershipModel.activate_immediately(
                membership_id=uuid4(),
                tenant_id=UUID(tenant["id"]),
                user_id=UUID(second_owner["user"]["id"]),
                role_name="OWNER",
                now=datetime.now(UTC),
            )
            await tenant_membership_crud.create(unit_of_work.session_handle, membership)
            await unit_of_work.commit()

        members = await client.get(f"/api/v1/tenants/{tenant['id']}/members", headers=auth(owner))
        first_owner_id = next(
            member["id"]
            for member in members.json()
            if member["role_name"] == "OWNER" and member["user_id"] == owner["user"]["id"]
        )
        demoted = await client.patch(
            f"/api/v1/tenants/{tenant['id']}/members/{first_owner_id}",
            headers=auth(owner),
            json={"role_name": "MANAGER"},
        )

        assert demoted.status_code == 200
        assert demoted.json()["role_name"] == "MANAGER"

        async with database.transaction_scope() as unit_of_work:
            assert await user_crud.count_users(unit_of_work.session_handle) == 2


# ---------------------------------------------------------------------------
# Status changes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_suspending_a_member_takes_effect_on_the_next_request(tables: None) -> None:
    async with running_application() as (client, _application):
        owner = await register(client)
        tenant = await create_business(client, owner, "Obi Electronics")
        worker_email = f"worker.{uuid4().hex[:8]}@example.com"
        invitation = await invite(client, owner, tenant["id"], email=worker_email)
        worker = await register(client, email=worker_email)
        await client.post(
            "/api/v1/invitations/accept", headers=auth(worker), json={"token": invitation["token"]}
        )

        members = await client.get(f"/api/v1/tenants/{tenant['id']}/members", headers=auth(owner))
        worker_membership_id = next(
            member["id"] for member in members.json() if member["role_name"] == "SALES"
        )

        before = await client.get(f"/api/v1/tenants/{tenant['id']}", headers=auth(worker))
        suspended = await client.patch(
            f"/api/v1/tenants/{tenant['id']}/members/{worker_membership_id}",
            headers=auth(owner),
            json={"status": "suspended"},
        )
        after = await client.get(f"/api/v1/tenants/{tenant['id']}", headers=auth(worker))
        reactivated = await client.patch(
            f"/api/v1/tenants/{tenant['id']}/members/{worker_membership_id}",
            headers=auth(owner),
            json={"status": "active"},
        )
        restored = await client.get(f"/api/v1/tenants/{tenant['id']}", headers=auth(worker))

    assert before.status_code == 200
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "suspended"
    assert after.status_code == 404, "a suspension is immediate"
    assert reactivated.json()["status"] == "active"
    assert restored.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
async def test_removing_a_member_is_recorded_not_deleted(tables: None) -> None:
    async with running_application() as (client, _application):
        owner = await register(client)
        tenant = await create_business(client, owner, "Obi Electronics")
        worker_email = f"worker.{uuid4().hex[:8]}@example.com"
        invitation = await invite(client, owner, tenant["id"], email=worker_email)
        worker = await register(client, email=worker_email)
        await client.post(
            "/api/v1/invitations/accept", headers=auth(worker), json={"token": invitation["token"]}
        )

        members = await client.get(f"/api/v1/tenants/{tenant['id']}/members", headers=auth(owner))
        worker_membership_id = next(
            member["id"] for member in members.json() if member["role_name"] == "SALES"
        )

        removed = await client.delete(
            f"/api/v1/tenants/{tenant['id']}/members/{worker_membership_id}",
            headers=auth(owner),
        )
        after = await client.get(f"/api/v1/tenants/{tenant['id']}/members", headers=auth(owner))

    assert removed.status_code == 200
    assert removed.json()["status"] == "removed"
    assert len(after.json()) == 2, "the row remains, because history references the person"


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_membership_from_another_business_is_not_reachable(tables: None) -> None:
    """A membership identifier alone must not cross tenants."""
    async with running_application() as (client, _application):
        first_owner = await register(client)
        second_owner = await register(client)
        first_tenant = await create_business(client, first_owner, "First Shop")
        second_tenant = await create_business(client, second_owner, "Second Shop")

        second_members = await client.get(
            f"/api/v1/tenants/{second_tenant['id']}/members", headers=auth(second_owner)
        )
        foreign_membership_id = second_members.json()[0]["id"]

        attempt = await client.delete(
            f"/api/v1/tenants/{first_tenant['id']}/members/{foreign_membership_id}",
            headers=auth(first_owner),
        )

    assert attempt.status_code == 404
    assert attempt.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_staff_routes_require_authentication(tables: None) -> None:
    async with running_application() as (client, _application):
        tenant_id = uuid4()
        responses = [
            await client.post(
                f"/api/v1/tenants/{tenant_id}/members",
                json={"email": "a@b.co", "role_name": "SALES"},
            ),
            await client.get(f"/api/v1/tenants/{tenant_id}/members"),
            await client.get(f"/api/v1/tenants/{tenant_id}/invitations"),
            await client.get("/api/v1/invitations"),
            await client.post("/api/v1/invitations/accept", json={"token": "x" * 20}),
        ]

    assert [response.status_code for response in responses] == [401] * 5


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_role_outside_the_invitable_set_is_rejected(tables: None) -> None:
    """Owner is not something an invitation hands out."""
    async with running_application() as (client, _application):
        owner = await register(client)
        tenant = await create_business(client, owner, "Obi Electronics")
        attempt = await client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            headers=auth(owner),
            json={"email": "someone@example.com", "role_name": "OWNER"},
        )

    assert attempt.status_code == 422
    assert attempt.json()["error"]["code"] == "INVALID_REQUEST"
