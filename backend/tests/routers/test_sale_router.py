"""End-to-end tests for the sales endpoints.

What is tested here is the part that only exists over HTTP: that a whole sale is one request,
that money leaves as decimal strings, that a replayed operation is a 201 rather than an
error, that a sale of another business is a 404, and that the two permissions this slice
needs are enforced where a client meets them.
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
                "TRUNCATE TABLE ledger_entries, payments, sale_items, sales, receipt_counters, "
                "inventory_movements, inventory, product_images, products, customers, "
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


async def business_with_stock(
    client: AsyncClient, *, quantity: str = "10", price: str = "45000.00"
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """A business with a product on the shelf, through the ordinary endpoints."""
    owner = await register(client)
    tenant = await client.post(
        "/api/v1/tenants", headers=auth(owner), json={"name": "Obi Electronics"}
    )
    assert tenant.status_code == 201, tenant.text
    tenant_id = tenant.json()["id"]

    product = await client.post(
        f"/api/v1/tenants/{tenant_id}/products",
        headers=auth(owner),
        json={"name": "Rice 50kg", "selling_price": price},
    )
    assert product.status_code == 201, product.text

    receipt = await client.post(
        f"/api/v1/tenants/{tenant_id}/inventory/{product.json()['id']}/receipts",
        headers=auth(owner),
        json={"quantity": quantity},
    )
    assert receipt.status_code == 201, receipt.text
    return owner, tenant.json(), product.json()


def sales_path(tenant_id: str, *parts: str) -> str:
    suffix = "".join(f"/{part}" for part in parts)
    return f"/api/v1/tenants/{tenant_id}/sales{suffix}"


def sale_payload(product_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "lines": [{"product_id": product_id, "quantity": "2.000"}],
        "payments": [{"amount": "90000.00", "method": "CASH"}],
    }
    payload.update(overrides)
    return payload


async def add_member(application: Any, *, tenant_id: UUID, user_id: UUID, role_name: str) -> None:
    membership = TenantMembershipModel.activate_immediately(
        membership_id=uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        role_name=role_name,
        now=datetime.now(UTC),
    )
    async with application.state.container.database.transaction_scope() as unit_of_work:
        await tenant_membership_crud.create(unit_of_work.session_handle, membership)
        await unit_of_work.commit()


# ---------------------------------------------------------------------------
# Recording a sale
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_sale_is_one_request(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_stock(client)
        response = await client.post(
            sales_path(tenant["id"]), headers=auth(owner), json=sale_payload(product["id"])
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["was_replayed"] is False
    sale = body["sale"]
    assert sale["receipt_number"] == "OBI-000001"
    assert sale["total_amount"] == "90000.00"
    assert sale["payment_status"] == "PAID"
    assert sale["is_settled"] is True
    assert len(sale["items"]) == 1
    assert len(sale["payments"]) == 1
    assert sale["items"][0]["product_name_snapshot"] == "Rice 50kg"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_money_leaves_as_decimal_strings(database: Database) -> None:
    """A client must never receive a monetary amount as a binary float."""
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_stock(client)
        response = await client.post(
            sales_path(tenant["id"]),
            headers=auth(owner),
            json=sale_payload(
                product["id"],
                discount_amount="5000.00",
                # The discount reduces what is owed, so the payment matches the total: the
                # service refuses a payment larger than the sale, because change given is
                # not a payment.
                payments=[{"amount": "85000.00", "method": "CASH"}],
            ),
        )

    body = response.json()["sale"]
    assert '"total_amount":"85000.00"' in response.text
    assert body["subtotal"] == "90000.00"
    assert body["discount_amount"] == "5000.00"
    assert body["items"][0]["line_total"] == "90000.00"
    assert body["items"][0]["quantity"] == "2.000"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_sale_reduces_the_stock(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_stock(client)
        await client.post(
            sales_path(tenant["id"]), headers=auth(owner), json=sale_payload(product["id"])
        )
        level = await client.get(
            f"/api/v1/tenants/{tenant['id']}/inventory/{product['id']}", headers=auth(owner)
        )

    assert level.json()["quantity_on_hand"] == "8.000"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_empty_sale_is_refused_by_the_contract(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_stock(client)
        response = await client.post(
            sales_path(tenant["id"]),
            headers=auth(owner),
            json=sale_payload(product["id"], lines=[]),
        )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_sale_with_no_payment_is_recorded_as_unpaid(database: Database) -> None:
    """A shopkeeper writing down what a customer took on credit has not been paid."""
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_stock(client)
        response = await client.post(
            sales_path(tenant["id"]),
            headers=auth(owner),
            json=sale_payload(product["id"], payments=[]),
        )

    assert response.status_code == 201, response.text
    assert response.json()["sale"]["payment_status"] == "UNPAID"
    assert response.json()["sale"]["is_settled"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_change_given_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_stock(client)
        response = await client.post(
            sales_path(tenant["id"]),
            headers=auth(owner),
            json=sale_payload(product["id"], payments=[{"amount": "100000.00", "method": "CASH"}]),
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_selling_more_than_is_in_stock_is_a_business_refusal(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_stock(client, quantity="1")
        response = await client.post(
            sales_path(tenant["id"]),
            headers=auth(owner),
            json=sale_payload(product["id"]),
        )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "BUSINESS_RULE_VIOLATION"
    assert body["error"]["correlation_id"]
    for internal in ("inventory_movements", "quantity_after", "NegativeStockPolicy"):
        assert internal not in response.text, f"the response leaked {internal}"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_withdrawn_product_cannot_be_sold(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_stock(client)
        await client.delete(
            f"/api/v1/tenants/{tenant['id']}/products/{product['id']}", headers=auth(owner)
        )
        response = await client.post(
            sales_path(tenant["id"]), headers=auth(owner), json=sale_payload(product["id"])
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "BUSINESS_RULE_VIOLATION"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_sale_can_name_a_customer(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_stock(client)
        customer = await client.post(
            f"/api/v1/tenants/{tenant['id']}/customers",
            headers=auth(owner),
            json={"name": "Ada Obi", "phone": "0803 123 4567"},
        )
        response = await client.post(
            sales_path(tenant["id"]),
            headers=auth(owner),
            json=sale_payload(
                product["id"], customer_id=customer.json()["customer"]["id"], payments=[]
            ),
        )

    assert response.status_code == 201, response.text
    assert response.json()["sale"]["customer_id"] == customer.json()["customer"]["id"]


# ---------------------------------------------------------------------------
# Replays
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_replayed_operation_returns_the_original_receipt(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_stock(client)
        operation_id = str(uuid4())
        payload = sale_payload(product["id"], operation_id=operation_id)

        first = await client.post(sales_path(tenant["id"]), headers=auth(owner), json=payload)
        second = await client.post(sales_path(tenant["id"]), headers=auth(owner), json=payload)
        level = await client.get(
            f"/api/v1/tenants/{tenant['id']}/inventory/{product['id']}", headers=auth(owner)
        )

    assert first.json()["was_replayed"] is False
    assert second.status_code == 201, second.text
    assert second.json()["was_replayed"] is True
    assert second.json()["sale"]["id"] == first.json()["sale"]["id"]
    assert second.json()["sale"]["receipt_number"] == "OBI-000001"
    assert level.json()["quantity_on_hand"] == "8.000", "the basket was sold once"


# ---------------------------------------------------------------------------
# Listing and reading
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_sales_list_shows_receipts_without_their_lines(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_stock(client)
        await client.post(
            sales_path(tenant["id"]), headers=auth(owner), json=sale_payload(product["id"])
        )
        listed = await client.get(sales_path(tenant["id"]), headers=auth(owner))

    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert [sale["receipt_number"] for sale in body] == ["OBI-000001"]
    assert "items" not in body[0]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_one_sale_can_be_read_with_its_lines_and_payments(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_stock(client)
        created = await client.post(
            sales_path(tenant["id"]), headers=auth(owner), json=sale_payload(product["id"])
        )
        fetched = await client.get(
            sales_path(tenant["id"], created.json()["sale"]["id"]), headers=auth(owner)
        )

    assert fetched.status_code == 200
    assert fetched.json() == created.json()["sale"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unknown_sale_is_a_404(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, _product = await business_with_stock(client)
        response = await client.get(sales_path(tenant["id"], str(uuid4())), headers=auth(owner))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Cancelling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cancelling_returns_the_stock_and_the_money(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_stock(client)
        created = await client.post(
            sales_path(tenant["id"]), headers=auth(owner), json=sale_payload(product["id"])
        )
        cancelled = await client.post(
            sales_path(tenant["id"], created.json()["sale"]["id"], "cancel"),
            headers=auth(owner),
            json={"reason": "the customer brought it back"},
        )
        level = await client.get(
            f"/api/v1/tenants/{tenant['id']}/inventory/{product['id']}", headers=auth(owner)
        )

    assert cancelled.status_code == 200, cancelled.text
    body = cancelled.json()
    assert body["status"] == "CANCELLED"
    assert body["cancellation_reason"] == "the customer brought it back"
    assert body["payment_status"] == "UNPAID", "the money went back, so nothing is settled"
    assert [payment["status"] for payment in body["payments"]] == ["REFUNDED"]
    assert level.json()["quantity_on_hand"] == "10.000"
    assert body["receipt_number"] == created.json()["sale"]["receipt_number"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cancelling_needs_a_reason(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_stock(client)
        created = await client.post(
            sales_path(tenant["id"]), headers=auth(owner), json=sale_payload(product["id"])
        )
        response = await client.post(
            sales_path(tenant["id"], created.json()["sale"]["id"], "cancel"),
            headers=auth(owner),
            json={"reason": "   "},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_client_cannot_decide_the_consequences_of_a_cancellation(
    database: Database,
) -> None:
    """Restocking, refunding and status are derived; letting a client send them is a hole."""
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_stock(client)
        created = await client.post(
            sales_path(tenant["id"]), headers=auth(owner), json=sale_payload(product["id"])
        )
        response = await client.post(
            sales_path(tenant["id"], created.json()["sale"]["id"], "cancel"),
            headers=auth(owner),
            json={"reason": "changed my mind", "status": "CANCELLED", "refund_amount": "0.00"},
        )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tenancy and authorization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_sale_of_another_business_is_not_found(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant, product = await business_with_stock(client)
        created = await client.post(
            sales_path(tenant["id"]), headers=auth(owner), json=sale_payload(product["id"])
        )

        outsider = await register(client)
        outsider_tenant = await client.post(
            "/api/v1/tenants", headers=auth(outsider), json={"name": "Somewhere Else"}
        )
        response = await client.get(
            sales_path(outsider_tenant.json()["id"], created.json()["sale"]["id"]),
            headers=auth(outsider),
        )

    assert response.status_code == 404
    assert "OBI-000001" not in response.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_product_of_another_business_cannot_be_sold(database: Database) -> None:
    async with running_application() as (client, _application):
        _owner, _tenant, product = await business_with_stock(client)
        outsider = await register(client)
        outsider_tenant = await client.post(
            "/api/v1/tenants", headers=auth(outsider), json={"name": "Somewhere Else"}
        )
        response = await client.post(
            sales_path(outsider_tenant.json()["id"]),
            headers=auth(outsider),
            json=sale_payload(product["id"], payments=[]),
        )

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_salesperson_may_sell_and_may_not_cancel(database: Database) -> None:
    async with running_application() as (client, application):
        _owner, tenant, product = await business_with_stock(client)
        worker = await register(client)
        await add_member(
            application,
            tenant_id=UUID(tenant["id"]),
            user_id=UUID(worker["user"]["id"]),
            role_name="SALES",
        )

        sold = await client.post(
            sales_path(tenant["id"]), headers=auth(worker), json=sale_payload(product["id"])
        )
        refused = await client.post(
            sales_path(tenant["id"], sold.json()["sale"]["id"], "cancel"),
            headers=auth(worker),
            json={"reason": "changed my mind"},
        )

    assert sold.status_code == 201, sold.text
    assert sold.json()["sale"]["seller_id"] == worker["user"]["id"]
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_inventory_worker_may_not_sell(database: Database) -> None:
    async with running_application() as (client, application):
        _owner, tenant, product = await business_with_stock(client)
        worker = await register(client)
        await add_member(
            application,
            tenant_id=UUID(tenant["id"]),
            user_id=UUID(worker["user"]["id"]),
            role_name="INVENTORY",
        )

        refused_sale = await client.post(
            sales_path(tenant["id"]), headers=auth(worker), json=sale_payload(product["id"])
        )
        refused_list = await client.get(sales_path(tenant["id"]), headers=auth(worker))

    assert refused_sale.status_code == 403
    assert refused_list.status_code == 403


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unauthenticated_request_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        _owner, tenant, _product = await business_with_stock(client)
        response = await client.get(sales_path(tenant["id"]))

    assert response.status_code == 401
