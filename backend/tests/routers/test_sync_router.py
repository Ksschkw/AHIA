"""End-to-end tests for the synchronization endpoints.

Real application, real PostgreSQL, real HTTP. What is tested here is the part that only exists
over the wire: the queue of operations as a client sends it, the flag that gates the whole
feature, and the shape of the answers a device acts on.

**The feature is off by default and answers as if it did not exist.** The test asserts a 404 that
is indistinguishable from an unknown path, because a deployment with the feature switched off must
not be distinguishable from one that never had it.

**A pushed sale goes through the sales use case.** The test pushes a queue over HTTP and then
reads the sale back through the ordinary sales endpoint, which is the proof that the offline path
is the same code as the online one rather than a second implementation.

**A conflict is a 200 with a conflict inside it.** One stale operation must not hide the answers
to the rest of the queue, so the response carries a status per operation and the client reads
`needs_attention`.
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
from ahia.crud import device_crud
from ahia.main import create_application
from ahia.models.entities.device_model import DeviceModel
from ahia.routers import sync_router
from ahia.services.iam_seed_service import IamSeedService

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
PASSWORD = "a-good-enough-password"
NOW = datetime(2026, 9, 14, 16, 0, tzinfo=UTC)


def build_settings(*, offline_sync: bool, **overrides: Any) -> Settings:
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
        "feature_offline_sync": offline_sync,
    }
    baseline.update(overrides)
    return Settings(**baseline)


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    instance = Database(build_settings(offline_sync=True))
    async with instance.engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(sync_connection, checkfirst=True)
        )
        await connection.execute(
            text(
                "TRUNCATE TABLE sync_changes, sync_cursors, sync_operations, audit_events, "
                "ledger_entries, payments, sale_items, sales, receipt_counters, "
                "inventory_movements, inventory, products, customers, devices, "
                "role_permissions, roles, permissions, tenant_memberships, tenants, "
                "user_sessions, users CASCADE"
            )
        )
    await IamSeedService(unit_of_work_factory=instance.unit_of_work_factory()).install_registry()
    try:
        yield instance
    finally:
        await instance.dispose()


@asynccontextmanager
async def running_application(*, offline_sync: bool) -> AsyncIterator[tuple[AsyncClient, Any]]:
    application = create_application(build_settings(offline_sync=offline_sync))
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


async def register_device(database: Database, *, tenant_id: UUID, user_id: UUID) -> UUID:
    """Register a device the way the device endpoint does, so a cursor can belong to it."""
    identifier = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await device_crud.create(
            unit_of_work.session_handle,
            DeviceModel.register(
                device_id=identifier,
                tenant_id=tenant_id,
                user_id=user_id,
                device_identifier=f"device-{identifier.hex[:8]}",
                platform="android",
                now=NOW,
            ),
        )
        await unit_of_work.commit()
    return identifier


def sync_path(tenant_id: str, *parts: str) -> str:
    suffix = "".join(f"/{part}" for part in parts)
    return f"/api/v1/tenants/{tenant_id}/sync{suffix}"


async def create_product(client: AsyncClient, owner: dict[str, Any], tenant: dict[str, Any]) -> str:
    response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/products",
        headers=auth(owner),
        json={"name": f"Rice 50kg {uuid4().hex[:6]}", "selling_price": "45000.00"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def add_stock(
    client: AsyncClient, owner: dict[str, Any], tenant: dict[str, Any], product_id: str
) -> None:
    response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/inventory/{product_id}/receipts",
        headers=auth(owner),
        json={"quantity": "10.000"},
    )
    assert response.status_code in {200, 201}, response.text


def sale_operation(product_id: str, operation_id: str | None = None) -> dict[str, Any]:
    return {
        "operation_id": operation_id or str(uuid4()),
        "operation_type": "complete_sale",
        "payload": {
            "lines": [{"product_id": product_id, "quantity": "2.000"}],
            "payments": [{"amount": "90000.00", "method": "CASH"}],
        },
    }


# ---------------------------------------------------------------------------
# The feature flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sync_answers_as_if_it_did_not_exist_while_the_flag_is_off(
    database: Database,
) -> None:
    async with running_application(offline_sync=False) as (client, _application):
        owner, tenant = await owner_with_business(client)

        pushed = await client.post(
            sync_path(tenant["id"], "push"),
            headers=auth(owner),
            json={"operations": [sale_operation(str(uuid4()))]},
        )
        pulled = await client.post(
            sync_path(tenant["id"], "pull"), headers=auth(owner), json={"after_sequence": 0}
        )

    assert pushed.status_code == 404
    assert pulled.status_code == 404
    assert "offline" not in pushed.text.lower(), "the refusal says nothing about the feature"


# ---------------------------------------------------------------------------
# Pushing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_pushed_sale_is_the_same_sale_the_online_endpoint_makes(
    database: Database,
) -> None:
    async with running_application(offline_sync=True) as (client, _application):
        owner, tenant = await owner_with_business(client)
        product_id = await create_product(client, owner, tenant)
        await add_stock(client, owner, tenant, product_id)

        pushed = await client.post(
            sync_path(tenant["id"], "push"),
            headers=auth(owner),
            json={"operations": [sale_operation(product_id)]},
        )
        sale_id = pushed.json()["results"][0]["entity_id"]
        read_back = await client.get(
            f"/api/v1/tenants/{tenant['id']}/sales/{sale_id}", headers=auth(owner)
        )

    assert pushed.status_code == 200, pushed.text
    result = pushed.json()["results"][0]
    assert result["status"] == "APPLIED"
    assert result["entity_type"] == "sale"
    assert result["needs_attention"] is False
    assert read_back.status_code == 200, read_back.text
    assert read_back.json()["receipt_number"] == result["detail"]["receipt_number"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_retried_queue_is_answered_as_a_replay(database: Database) -> None:
    async with running_application(offline_sync=True) as (client, _application):
        owner, tenant = await owner_with_business(client)
        product_id = await create_product(client, owner, tenant)
        await add_stock(client, owner, tenant, product_id)
        operation = sale_operation(product_id)

        first = await client.post(
            sync_path(tenant["id"], "push"),
            headers=auth(owner),
            json={"operations": [operation]},
        )
        second = await client.post(
            sync_path(tenant["id"], "push"),
            headers=auth(owner),
            json={"operations": [operation]},
        )

    assert first.json()["results"][0]["status"] == "APPLIED"
    assert second.json()["results"][0]["status"] == "REPLAYED"
    assert second.json()["results"][0]["entity_id"] == first.json()["results"][0]["entity_id"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_field_the_operation_does_not_have_is_refused_at_the_edge(
    database: Database,
) -> None:
    """A payload with a field the operation does not have is a 422, not a half-ignored write."""
    async with running_application(offline_sync=True) as (client, _application):
        owner, tenant = await owner_with_business(client)
        product_id = await create_product(client, owner, tenant)

        response = await client.post(
            sync_path(tenant["id"], "push"),
            headers=auth(owner),
            json={
                "operations": [
                    {
                        "operation_id": str(uuid4()),
                        "operation_type": "complete_sale",
                        "payload": {
                            "lines": [
                                {"product_id": product_id, "quantity": "1.000", "price": "1.00"}
                            ]
                        },
                    }
                ]
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_stale_customer_edit_comes_back_as_a_conflict_in_a_200(
    database: Database,
) -> None:
    async with running_application(offline_sync=True) as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await client.post(
            f"/api/v1/tenants/{tenant['id']}/customers",
            headers=auth(owner),
            json={"name": "Ada Obi", "phone": "08031234567"},
        )
        assert created.status_code == 201, created.text
        # The creation response is a wrapper: the customer, and who they may already be.
        customer = created.json()["customer"]
        await client.patch(
            f"/api/v1/tenants/{tenant['id']}/customers/{customer['id']}",
            headers=auth(owner),
            json={"notes": "Prefers delivery on Saturdays"},
        )

        response = await client.post(
            sync_path(tenant["id"], "push"),
            headers=auth(owner),
            json={
                "operations": [
                    {
                        "operation_id": str(uuid4()),
                        "operation_type": "update_customer",
                        "payload": {
                            "customer_id": customer["id"],
                            "expected_version": customer["version"],
                            "address": "12 Awolowo Road",
                        },
                    }
                ]
            },
        )

    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["status"] == "CONFLICT"
    assert result["needs_attention"] is True
    assert int(result["detail"]["server_version"]) == customer["version"] + 1


# ---------------------------------------------------------------------------
# Pulling and the cursor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pulling_returns_the_changes_and_the_latest_sequence(
    database: Database,
) -> None:
    async with running_application(offline_sync=True) as (client, _application):
        owner, tenant = await owner_with_business(client)
        product_id = await create_product(client, owner, tenant)
        await add_stock(client, owner, tenant, product_id)

        pulled = await client.post(
            sync_path(tenant["id"], "pull"), headers=auth(owner), json={"after_sequence": 0}
        )

    assert pulled.status_code == 200, pulled.text
    body = pulled.json()
    assert body["latest_sequence"] >= 1
    assert body["has_more"] is False
    entity_types = {change["entity_type"] for change in body["changes"]}
    assert "product" in entity_types, "the catalogue change is in the feed"
    assert all(change["change_sequence"] >= 1 for change in body["changes"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_cursor_request_from_a_session_without_a_device_is_refused(
    database: Database,
) -> None:
    """A cursor is a position belonging to a device, and a session that is not on one has none.

    The device identifier comes from the authenticated session rather than from a header, which is
    why this request cannot name one: a client cannot move a cursor for a phone it is not holding.
    The successful path - creating the cursor and advancing it forward only - is covered at the
    service layer, where a device context can be built directly.
    """
    async with running_application(offline_sync=True) as (client, _application):
        owner, tenant = await owner_with_business(client)

        response = await client.post(
            sync_path(tenant["id"], "cursor"), headers=auth(owner), json={"sequence": 42}
        )

    # InvalidInputError is a 422 in this API - the request was well formed and refused for a
    # reason: a session that is not on a device cannot hold a device's cursor.
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unauthenticated_push_is_refused(database: Database) -> None:
    async with running_application(offline_sync=True) as (client, _application):
        _owner, tenant = await owner_with_business(client)

        # No credentials at all: the setup above signed somebody in, and a browser would send that

        # session cookie. An unauthenticated caller is one with neither a header nor a cookie.

        client.cookies.clear()

        response = await client.post(
            sync_path(tenant["id"], "push"),
            json={"operations": [sale_operation(str(uuid4()))]},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_empty_queue_is_refused(database: Database) -> None:
    async with running_application(offline_sync=True) as (client, _application):
        owner, tenant = await owner_with_business(client)

        response = await client.post(
            sync_path(tenant["id"], "push"), headers=auth(owner), json={"operations": []}
        )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_another_business_cannot_pull_this_business_feed(
    database: Database,
) -> None:
    async with running_application(offline_sync=True) as (client, _application):
        owner, tenant = await owner_with_business(client)
        product_id = await create_product(client, owner, tenant)
        await add_stock(client, owner, tenant, product_id)
        other_owner, other_tenant = await owner_with_business(client)

        response = await client.post(
            sync_path(other_tenant["id"], "pull"),
            headers=auth(other_owner),
            json={"after_sequence": 0},
        )

    assert response.status_code == 200
    assert response.json()["changes"] == []
    assert response.json()["latest_sequence"] == 0


# ---------------------------------------------------------------------------
# The queue's order and the client's own report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_results_come_back_in_the_order_they_were_pushed(database: Database) -> None:
    async with running_application(offline_sync=True) as (client, _application):
        owner, tenant = await owner_with_business(client)
        product_id = await create_product(client, owner, tenant)
        first = sale_operation(product_id)
        second = sale_operation(product_id)

        response = await client.post(
            sync_path(tenant["id"], "push"),
            headers=auth(owner),
            json={"operations": [first, second]},
        )

    results = response.json()["results"]
    assert [result["operation_id"] for result in results] == [
        first["operation_id"],
        second["operation_id"],
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_sale_without_stock_is_rejected_and_the_next_one_still_applies(
    database: Database,
) -> None:
    """One refused operation must not throw away the queue behind it."""
    async with running_application(offline_sync=True) as (client, _application):
        owner, tenant = await owner_with_business(client)
        stocked = await create_product(client, owner, tenant)
        await add_stock(client, owner, tenant, stocked)
        unstocked = await create_product(client, owner, tenant)

        response = await client.post(
            sync_path(tenant["id"], "push"),
            headers=auth(owner),
            json={
                "operations": [sale_operation(unstocked), sale_operation(stocked)],
            },
        )

    results = response.json()["results"]
    assert results[0]["status"] == "REJECTED"
    assert results[0]["needs_attention"] is True
    assert results[1]["status"] == "APPLIED"


def _published_flag_is_off_by_default() -> bool:
    """The flag register's default, asserted from the settings class rather than a deployment."""
    return Settings.model_fields["feature_offline_sync"].default is False


@pytest.mark.unit
def test_the_offline_sync_flag_is_off_by_default() -> None:
    """New behaviour ships dark: the endpoints exist in the code and answer as absent until asked
    for, and the default is the answer a deployment gets without configuring anything."""
    assert _published_flag_is_off_by_default() is True


@pytest.mark.unit
def test_the_sync_router_is_gated_route_by_route() -> None:
    """Every route in this router carries the flag dependency, so a new route cannot forget it."""
    for route in sync_router.router.routes:
        dependencies = getattr(route, "dependencies", [])
        assert any(
            dependency.dependency is sync_router.require_offline_sync for dependency in dependencies
        ), f"{route.path} is not gated by the offline-sync flag"
