"""End-to-end tests for the inventory endpoints.

Real application, real PostgreSQL, real row locks. What is tested here is the part that
only exists over HTTP: the quantity contract, the status codes, the route ordering that
makes `GET /inventory/movements` work at all, and the policy endpoint that a business uses
to change its own rule.
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
            text(
                "TRUNCATE TABLE inventory_movements, inventory, products, "
                "tenant_memberships, tenants, users CASCADE"
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


async def business_with_product(
    client: AsyncClient, *, name: str = "Rice 50kg"
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    owner = await register(client)
    tenant = await client.post(
        "/api/v1/tenants", headers=auth(owner), json={"name": "Obi Electronics"}
    )
    assert tenant.status_code == 201, tenant.text
    product = await client.post(
        f"/api/v1/tenants/{tenant.json()['id']}/products",
        headers=auth(owner),
        json={"name": name, "selling_price": "45000.00"},
    )
    assert product.status_code == 201, product.text
    return owner, tenant.json(), product.json()


def inventory_path(tenant_id: str, *parts: str) -> str:
    suffix = "".join(f"/{part}" for part in parts)
    return f"/api/v1/tenants/{tenant_id}/inventory{suffix}"


# ---------------------------------------------------------------------------
# Receiving and reading
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_receiving_stock_returns_the_movement_and_the_new_level(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_product(client)
        response = await client.post(
            inventory_path(tenant["id"], product["id"], "receipts"),
            headers=auth(owner),
            json={"quantity": "50.000", "note": "delivery from Musa"},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["movement"]["movement_type"] == "STOCK_RECEIVED"
    assert body["movement"]["quantity_before"] == "0.000"
    assert body["movement"]["quantity_after"] == "50.000"
    assert body["movement"]["quantity_delta"] == "50.000"
    assert body["inventory"]["quantity_on_hand"] == "50.000"
    assert body["inventory"]["version"] == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_quantities_leave_as_decimal_strings(database: Database) -> None:
    """A client must not receive a stock count as a binary float."""
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_product(client)
        await client.post(
            inventory_path(tenant["id"], product["id"], "receipts"),
            headers=auth(owner),
            json={"quantity": 2.5},
        )
        level = await client.get(inventory_path(tenant["id"], product["id"]), headers=auth(owner))

    assert '"quantity_on_hand":"2.500"' in level.text
    assert '"available_quantity":"2.500"' in level.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_quantity_with_too_many_places_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_product(client)
        response = await client.post(
            inventory_path(tenant["id"], product["id"], "receipts"),
            headers=auth(owner),
            json={"quantity": "2.5001"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_negative_receipt_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_product(client)
        response = await client.post(
            inventory_path(tenant["id"], product["id"], "receipts"),
            headers=auth(owner),
            json={"quantity": "-5"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_uncounted_product_reads_as_zero(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_product(client)
        response = await client.get(
            inventory_path(tenant["id"], product["id"]), headers=auth(owner)
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["quantity_on_hand"] == "0.000"
    assert body["is_out_of_stock"] is True
    assert body["product_name"] == "Rice 50kg"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_stock_screen_lists_every_product(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, first = await business_with_product(client, name="Rice 50kg")
        await client.post(
            f"/api/v1/tenants/{tenant['id']}/products",
            headers=auth(owner),
            json={"name": "Beans 50kg", "selling_price": "55000.00"},
        )
        await client.post(
            inventory_path(tenant["id"], first["id"], "receipts"),
            headers=auth(owner),
            json={"quantity": "7"},
        )
        listing = await client.get(inventory_path(tenant["id"]), headers=auth(owner))

    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert [level["product_name"] for level in body] == ["Beans 50kg", "Rice 50kg"]
    assert [level["quantity_on_hand"] for level in body] == ["0.000", "7.000"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_history_route_is_not_read_as_a_product_identifier(
    database: Database,
) -> None:
    """Route order: `movements` is a literal segment and must be matched as one."""
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_product(client)
        await client.post(
            inventory_path(tenant["id"], product["id"], "receipts"),
            headers=auth(owner),
            json={"quantity": "3"},
        )
        history = await client.get(inventory_path(tenant["id"], "movements"), headers=auth(owner))

    assert history.status_code == 200, history.text
    assert [entry["movement_type"] for entry in history.json()] == ["STOCK_RECEIVED"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_history_can_be_limited_to_one_product(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, first = await business_with_product(client, name="Rice 50kg")
        second = await client.post(
            f"/api/v1/tenants/{tenant['id']}/products",
            headers=auth(owner),
            json={"name": "Beans 50kg", "selling_price": "55000.00"},
        )
        await client.post(
            inventory_path(tenant["id"], first["id"], "receipts"),
            headers=auth(owner),
            json={"quantity": "3"},
        )
        await client.post(
            inventory_path(tenant["id"], second.json()["id"], "receipts"),
            headers=auth(owner),
            json={"quantity": "4"},
        )
        history = await client.get(
            inventory_path(tenant["id"], "movements"),
            headers=auth(owner),
            params={"product_id": first["id"]},
        )

    assert history.status_code == 200
    assert len(history.json()) == 1


# ---------------------------------------------------------------------------
# Adjusting, damage and transfers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_adjustment_requires_a_reason(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_product(client)
        response = await client.post(
            inventory_path(tenant["id"], product["id"], "adjustments"),
            headers=auth(owner),
            json={"delta": "-1.000"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_adjustment_moves_stock_down(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_product(client)
        await client.post(
            inventory_path(tenant["id"], product["id"], "receipts"),
            headers=auth(owner),
            json={"quantity": "10"},
        )
        adjusted = await client.post(
            inventory_path(tenant["id"], product["id"], "adjustments"),
            headers=auth(owner),
            json={"delta": "-2.500", "reason": "count came out lower"},
        )

    assert adjusted.status_code == 200, adjusted.text
    assert adjusted.json()["inventory"]["quantity_on_hand"] == "7.500"
    assert adjusted.json()["movement"]["note"] == "count came out lower"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_damage_is_recorded_with_its_reason(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_product(client)
        await client.post(
            inventory_path(tenant["id"], product["id"], "receipts"),
            headers=auth(owner),
            json={"quantity": "10"},
        )
        damaged = await client.post(
            inventory_path(tenant["id"], product["id"], "damage"),
            headers=auth(owner),
            json={"quantity": "1.5", "reason": "torn bag", "note": "store room leak"},
        )

    assert damaged.status_code == 201, damaged.text
    body = damaged.json()
    assert body["movement"]["movement_type"] == "DAMAGE"
    assert body["movement"]["quantity_delta"] == "-1.500"
    assert body["movement"]["note"] == "torn bag: store room leak"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_transfer_reports_both_sides(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, carton = await business_with_product(client, name="Rice carton")
        unit = await client.post(
            f"/api/v1/tenants/{tenant['id']}/products",
            headers=auth(owner),
            json={"name": "Rice 5kg", "selling_price": "5000.00"},
        )
        await client.post(
            inventory_path(tenant["id"], carton["id"], "receipts"),
            headers=auth(owner),
            json={"quantity": "10"},
        )
        transferred = await client.post(
            inventory_path(tenant["id"], "transfers"),
            headers=auth(owner),
            json={
                "source_product_id": carton["id"],
                "destination_product_id": unit.json()["id"],
                "quantity": "4",
                "reason": "opened cartons for retail",
            },
        )

    assert transferred.status_code == 201, transferred.text
    body = transferred.json()
    assert body["source"]["quantity_on_hand"] == "6.000"
    assert body["destination"]["quantity_on_hand"] == "4.000"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_transfer_to_the_same_product_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_product(client)
        response = await client.post(
            inventory_path(tenant["id"], "transfers"),
            headers=auth(owner),
            json={
                "source_product_id": product["id"],
                "destination_product_id": product["id"],
                "quantity": "1",
                "reason": "pointless",
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


# ---------------------------------------------------------------------------
# The policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_policy_is_published_on_the_business(database: Database) -> None:
    async with running_application() as (client, _application):
        owner = await register(client)
        tenant = await client.post(
            "/api/v1/tenants", headers=auth(owner), json={"name": "Obi Electronics"}
        )

    assert tenant.json()["negative_stock_policy"] == "BLOCK_NEGATIVE_STOCK"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_business_can_allow_negative_stock(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_product(client)

        refused = await client.post(
            inventory_path(tenant["id"], product["id"], "adjustments"),
            headers=auth(owner),
            json={"delta": "-1", "reason": "sold ahead of delivery"},
        )
        policy = await client.put(
            f"/api/v1/tenants/{tenant['id']}/stock-policy",
            headers=auth(owner),
            json={"policy": "ALLOW_WITH_WARNING"},
        )
        allowed = await client.post(
            inventory_path(tenant["id"], product["id"], "adjustments"),
            headers=auth(owner),
            json={"delta": "-1", "reason": "sold ahead of delivery"},
        )

    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "BUSINESS_RULE_VIOLATION"
    assert policy.status_code == 200, policy.text
    assert policy.json()["negative_stock_policy"] == "ALLOW_WITH_WARNING"
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["movement"]["is_overdraw"] is True
    assert allowed.json()["inventory"]["quantity_on_hand"] == "-1.000"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unknown_policy_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, _product = await business_with_product(client)
        response = await client.put(
            f"/api/v1/tenants/{tenant['id']}/stock-policy",
            headers=auth(owner),
            json={"policy": "MAYBE"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_salesperson_cannot_change_the_policy(database: Database) -> None:
    """Allowing negative stock changes what every number in the business means."""
    async with running_application() as (client, application):
        _owner, tenant, _product = await business_with_product(client)
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

        response = await client.put(
            f"/api/v1/tenants/{tenant['id']}/stock-policy",
            headers=auth(worker),
            json={"policy": "ALLOW_NEGATIVE_STOCK"},
        )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Tenancy and authorization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_stock_cannot_be_read_through_another_business(database: Database) -> None:
    async with running_application() as (client, _application):
        _owner, _tenant, product = await business_with_product(client)
        outsider = await register(client)
        outsider_tenant = await client.post(
            "/api/v1/tenants", headers=auth(outsider), json={"name": "Somewhere Else"}
        )
        response = await client.get(
            inventory_path(outsider_tenant.json()["id"], product["id"]), headers=auth(outsider)
        )

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_stock_cannot_be_received_against_another_businesss_product(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        _owner, _tenant, product = await business_with_product(client)
        outsider = await register(client)
        outsider_tenant = await client.post(
            "/api/v1/tenants", headers=auth(outsider), json={"name": "Somewhere Else"}
        )
        response = await client.post(
            inventory_path(outsider_tenant.json()["id"], product["id"], "receipts"),
            headers=auth(outsider),
            json={"quantity": "5"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_salesperson_can_read_stock_and_cannot_change_it(database: Database) -> None:
    async with running_application() as (client, application):
        owner, tenant, product = await business_with_product(client)
        await client.post(
            inventory_path(tenant["id"], product["id"], "receipts"),
            headers=auth(owner),
            json={"quantity": "5"},
        )
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

        readable = await client.get(
            inventory_path(tenant["id"], product["id"]), headers=auth(worker)
        )
        refused = await client.post(
            inventory_path(tenant["id"], product["id"], "receipts"),
            headers=auth(worker),
            json={"quantity": "1"},
        )

    assert readable.status_code == 200
    assert readable.json()["quantity_on_hand"] == "5.000"
    assert refused.status_code == 403


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unauthenticated_request_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        _owner, tenant, _product = await business_with_product(client)
        response = await client.get(inventory_path(tenant["id"]))

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_business_rule_refusal_leaks_nothing_internal(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_product(client)
        response = await client.post(
            inventory_path(tenant["id"], product["id"], "adjustments"),
            headers=auth(owner),
            json={"delta": "-1", "reason": "nothing to sell"},
        )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "BUSINESS_RULE_VIOLATION"
    assert body["error"]["correlation_id"]
    for internal in ("inventory_movements", "quantity_after", "NegativeStockPolicy", "row"):
        assert internal not in response.text, f"the response leaked {internal}"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_transfer_between_two_businesses_products_is_refused(
    database: Database,
) -> None:
    """The composite product reference refuses it; the service refuses it first."""
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_product(client)
        await client.post(
            inventory_path(tenant["id"], product["id"], "receipts"),
            headers=auth(owner),
            json={"quantity": "5"},
        )
        outsider = await register(client)
        outsider_tenant = await client.post(
            "/api/v1/tenants", headers=auth(outsider), json={"name": "Somewhere Else"}
        )
        outsider_product = await client.post(
            f"/api/v1/tenants/{outsider_tenant.json()['id']}/products",
            headers=auth(outsider),
            json={"name": "Their rice", "selling_price": "100.00"},
        )

        response = await client.post(
            inventory_path(tenant["id"], "transfers"),
            headers=auth(owner),
            json={
                "source_product_id": product["id"],
                "destination_product_id": outsider_product.json()["id"],
                "quantity": "1",
                "reason": "across businesses",
            },
        )
        level = await client.get(inventory_path(tenant["id"], product["id"]), headers=auth(owner))

    assert response.status_code == 404
    assert level.json()["quantity_on_hand"] == "5.000", "the source is untouched"
