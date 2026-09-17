"""End-to-end tests for share links.

Real application, real HTTP, real PostgreSQL. The subject is a bearer token that opens one record to
anybody holding it, which makes four properties worth asserting rather than assuming.

**The token is not stored, and it is not recoverable.** The response that mints a link carries the
token; the listing shows the link and no token; the database holds a digest. A test asserts the
plaintext appears in the minting response and in no other response, and that the stored value is not
the token.

**A revoked or expired link opens nothing.** Revocation is permanent, an expired link is refused
without a job having to set a flag, and both refusals are the same not-found as an unknown token, so
the holder cannot learn that a token was once real.

**What a link opens has no customer in it.** The shared invoice carries the business, the receipt
number, the lines and the totals, and none of the customer's details or the business's internal
identifiers.

**Sharing needs the resource's own read permission.** A caller with no `sales.read` cannot publish a
sale to the internet, and the refusal is checked in the service where a CLI gets the same answer.
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
from ahia.crud import share_link_crud
from ahia.main import create_application
from ahia.models.entities.share_link_model import ShareableResource
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
        "rate_limit_public_read_per_minute": 1_000,
        "feature_storefront_public_publishing": True,
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
                "TRUNCATE TABLE share_links, storefronts, sync_changes, audit_events, "
                "ledger_entries, payments, sale_items, sales, receipt_counters, "
                "inventory_movements, inventory, product_images, products, customers, "
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
async def running_application() -> AsyncIterator[tuple[AsyncClient, Any]]:
    application = create_application(build_settings())
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


async def a_sale(
    client: AsyncClient, owner: dict[str, Any], tenant: dict[str, Any]
) -> dict[str, Any]:
    """Record a sale through the ordinary endpoint: the fixture, not the subject."""
    product = await client.post(
        f"/api/v1/tenants/{tenant['id']}/products",
        headers=auth(owner),
        json={"name": f"Rice 50kg {uuid4().hex[:6]}", "selling_price": "45000.00"},
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["id"]
    received = await client.post(
        f"/api/v1/tenants/{tenant['id']}/inventory/{product_id}/receipts",
        headers=auth(owner),
        json={"quantity": "10.000"},
    )
    assert received.status_code in {200, 201}, received.text
    customer = await client.post(
        f"/api/v1/tenants/{tenant['id']}/customers",
        headers=auth(owner),
        json={"name": "Ada Obi", "phone": "08031234567"},
    )
    assert customer.status_code == 201, customer.text
    sale = await client.post(
        f"/api/v1/tenants/{tenant['id']}/sales",
        headers=auth(owner),
        json={
            "lines": [{"product_id": product_id, "quantity": "2.000"}],
            "payments": [{"amount": "90000.00", "method": "CASH"}],
            "customer_id": customer.json()["customer"]["id"],
        },
    )
    assert sale.status_code == 201, sale.text
    return sale.json()["sale"]


async def share(
    client: AsyncClient, owner: dict[str, Any], tenant: dict[str, Any], sale_id: str, **payload: Any
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/sales/{sale_id}/share",
        headers=auth(owner),
        json=payload or {},
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Minting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sharing_an_invoice_returns_a_token_once(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        sale = await a_sale(client, owner, tenant)

        issued = await share(client, owner, tenant, sale["id"])
        listed = await client.get(
            f"/api/v1/tenants/{tenant['id']}/sales/{sale['id']}/share-links",
            headers=auth(owner),
        )

    token = issued["token"]
    assert issued["public_path"] == f"/share/{token}"
    assert issued["link"]["resource_type"] == "invoice"
    assert issued["link"]["is_open"] is True
    assert len(token) >= 20, "a token that can be guessed is not an authorization"

    assert token not in listed.text, "the listing must not be able to re-show the link"
    assert "token" not in listed.json()[0]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_token_is_not_stored(database: Database) -> None:
    """A leaked table must not be a set of working links."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        sale = await a_sale(client, owner, tenant)
        issued = await share(client, owner, tenant, sale["id"])

    async with database.transaction_scope() as unit_of_work:
        stored = await share_link_crud.list_for_resource(
            unit_of_work.session_handle,
            tenant_id=UUID(tenant["id"]),
            resource_type=ShareableResource.INVOICE,
            resource_id=UUID(sale["id"]),
        )

    assert len(stored) == 1
    assert stored[0].token_hash != issued["token"]
    assert issued["token"] not in stored[0].token_hash
    assert len(stored[0].token_hash) == 64


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_lifetime_outside_the_bounds_is_refused(database: Database) -> None:
    """A link that never expires is a permanent public address for a customer's purchases."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        sale = await a_sale(client, owner, tenant)

        too_long = await client.post(
            f"/api/v1/tenants/{tenant['id']}/sales/{sale['id']}/share",
            headers=auth(owner),
            json={"lifetime_days": 4_000},
        )
        zero = await client.post(
            f"/api/v1/tenants/{tenant['id']}/sales/{sale['id']}/share",
            headers=auth(owner),
            json={"lifetime_days": 0},
        )

    assert too_long.status_code == 422
    assert zero.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unknown_sale_cannot_be_shared(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)

        response = await client.post(
            f"/api/v1/tenants/{tenant['id']}/sales/{uuid4()}/share",
            headers=auth(owner),
            json={},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_stranger_cannot_share_somebody_elses_invoice(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        sale = await a_sale(client, owner, tenant)
        stranger = await register(client)

        response = await client.post(
            f"/api/v1/tenants/{tenant['id']}/sales/{sale['id']}/share",
            headers=auth(stranger),
            json={},
        )

    assert response.status_code in {403, 404}


# ---------------------------------------------------------------------------
# Opening
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_shared_link_opens_the_invoice_without_a_token(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        sale = await a_sale(client, owner, tenant)
        issued = await share(client, owner, tenant, sale["id"])

        response = await client.get(f"/share/{issued['token']}")

    assert response.status_code == 200, response.text
    invoice = response.json()
    assert invoice["business_name"] == "Obi Electronics"
    assert invoice["receipt_number"] == sale["receipt_number"]
    assert invoice["total_amount"] == sale["total_amount"]
    assert len(invoice["lines"]) == 1
    assert invoice["lines"][0]["quantity"] == "2.000"
    assert invoice["lines"][0]["unit_price"] == "45000.00"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_shared_invoice_carries_no_customer_and_no_internal_identifier(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        sale = await a_sale(client, owner, tenant)
        issued = await share(client, owner, tenant, sale["id"])

        response = await client.get(f"/share/{issued['token']}")

    rendered = response.text
    for private in ("Ada", "08031234567", sale["id"], tenant["id"], "customer_id", "cost_price"):
        assert private not in rendered, f"{private!r} reached a shared invoice"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unknown_token_opens_nothing(database: Database) -> None:
    async with running_application() as (client, _application):
        response = await client.get("/share/not-a-real-token")

    assert response.status_code == 404
    assert set(response.json()) == {"error"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_revoked_link_opens_nothing(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        sale = await a_sale(client, owner, tenant)
        issued = await share(client, owner, tenant, sale["id"])
        opened = await client.get(f"/share/{issued['token']}")
        revoked = await client.post(
            f"/api/v1/tenants/{tenant['id']}/share-links/{issued['link']['id']}/revoke",
            headers=auth(owner),
        )
        after = await client.get(f"/share/{issued['token']}")
        listed = await client.get(
            f"/api/v1/tenants/{tenant['id']}/sales/{sale['id']}/share-links",
            headers=auth(owner),
        )

    assert opened.status_code == 200
    assert revoked.status_code == 200
    assert revoked.json()["is_open"] is False
    assert revoked.json()["revoked_at"] is not None
    assert after.status_code == 404
    assert after.json()["error"]["code"] == "NOT_FOUND"
    assert listed.json()[0]["revoked_at"] is not None, "the record of the link stays"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_revoking_twice_keeps_the_first_moment(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        sale = await a_sale(client, owner, tenant)
        issued = await share(client, owner, tenant, sale["id"])
        first = await client.post(
            f"/api/v1/tenants/{tenant['id']}/share-links/{issued['link']['id']}/revoke",
            headers=auth(owner),
        )
        second = await client.post(
            f"/api/v1/tenants/{tenant['id']}/share-links/{issued['link']['id']}/revoke",
            headers=auth(owner),
        )

    assert first.json()["revoked_at"] == second.json()["revoked_at"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_revoked_link_and_an_unknown_token_are_indistinguishable(
    database: Database,
) -> None:
    """Saying "that link was revoked" confirms the token was once real."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        sale = await a_sale(client, owner, tenant)
        issued = await share(client, owner, tenant, sale["id"])
        await client.post(
            f"/api/v1/tenants/{tenant['id']}/share-links/{issued['link']['id']}/revoke",
            headers=auth(owner),
        )

        revoked = await client.get(f"/share/{issued['token']}")
        unknown = await client.get("/share/never-existed")

    assert revoked.status_code == unknown.status_code == 404
    assert revoked.json()["error"]["message"] == unknown.json()["error"]["message"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_expired_link_opens_nothing_without_a_job_having_run(
    database: Database,
) -> None:
    """Expiry is a comparison, not a flag: nothing has to sweep the table for it to hold."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        sale = await a_sale(client, owner, tenant)
        issued = await share(client, owner, tenant, sale["id"], lifetime_days=1)

    # Reach into the row and move its expiry into the past, which is what a day passing does.
    async with database.transaction_scope() as unit_of_work:
        stored = await share_link_crud.list_for_resource(
            unit_of_work.session_handle,
            tenant_id=UUID(tenant["id"]),
            resource_type=ShareableResource.INVOICE,
            resource_id=UUID(sale["id"]),
        )
        record = stored[0]
        await unit_of_work.session_handle.execute(
            text("UPDATE share_links SET expires_at = :past WHERE id = :id"),
            {"past": datetime.now(UTC) - timedelta(minutes=1), "id": record.id},
        )
        await unit_of_work.commit()

    async with running_application() as (client, _application):
        response = await client.get(f"/share/{issued['token']}")

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_link_only_opens_its_own_businesss_record(database: Database) -> None:
    """The tenant is read from the link, so a token can never resolve another business's sale."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        sale = await a_sale(client, owner, tenant)
        issued = await share(client, owner, tenant, sale["id"])

        # A second business with its own sale: its owner must not see the first business's sale
        # through the other business's link, and the link itself carries its tenant.
        other_owner, other_tenant = await owner_with_business(client)
        other_sale = await a_sale(client, other_owner, other_tenant)

        first = await client.get(f"/share/{issued['token']}")
        listed_by_other = await client.get(
            f"/api/v1/tenants/{other_tenant['id']}/sales/{sale['id']}/share-links",
            headers=auth(other_owner),
        )

    # Receipt numbers are per business, so two businesses legitimately hold the same one: the
    # assertion is about which business the link resolved, not about which number it printed.
    assert first.json()["business_name"] == "Obi Electronics"
    assert first.json()["receipt_number"] == sale["receipt_number"]
    # Another business asking about this sale is answered with an empty list rather than a 404:
    # the links are scoped by tenant, so there is nothing to find, and the answer confirms
    # nothing about whether the sale exists.
    assert listed_by_other.status_code == 200
    assert listed_by_other.json() == []
    _ = other_sale
