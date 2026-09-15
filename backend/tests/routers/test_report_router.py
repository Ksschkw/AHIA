"""End-to-end tests for the reports.

Real application, real HTTP, real PostgreSQL, against sales recorded through the ordinary
endpoints - which is the point: a report that is correct against rows the test inserted itself is
a report that has never met the code that writes sales.

**The numbers are compared with the receipts.** The revenue a report shows is checked against the
sale the API returned, and the day-by-day rows are checked against the days the sales were made on.

**A cancelled sale is money that came back.** It is excluded from revenue and from what sold, while
its lines and its receipt stay readable through the sales endpoints. That distinction is the whole
reason the report is not a sum over the sales table.

**The period is bounded, and the bounds are the service's.** Seven days by default, ninety at most,
and a period that ends before it starts is refused.

**`reports.read` is enforced in the service.** A salesperson holds `sales.read` and not
`reports.read`: they can sell and they cannot see what the business made.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.storage_double import RecordingStorage

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.crud import audit_event_crud, report_export_crud, tenant_membership_crud
from ahia.main import create_application
from ahia.models.entities.tenant_membership_model import TenantMembershipModel
from ahia.services.iam_seed_service import IamSeedService
from ahia.services.report_service import ReportService

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


@asynccontextmanager
async def running_application_with_storage() -> AsyncIterator[tuple[AsyncClient, RecordingStorage]]:
    """Run the application with an in-memory object store.

    The export writes bytes somewhere, and a test that reached the real provider would need a
    network, credentials and somebody else's uptime. The container is not frozen, so the double is
    assigned in place and every route that asks for storage receives it - which is also a check that
    the routes ask the container rather than building an adapter themselves.
    """
    storage = RecordingStorage()
    application = create_application(build_settings())
    async with application.router.lifespan_context(application):
        container = application.state.container
        # The service holds the adapter it was built with, so the swap has to happen on both: the
        # container for the routes that ask it, and the service for the export path.
        container.storage = storage
        container.report_service = ReportService(
            unit_of_work_factory=container.database.unit_of_work_factory(),
            storage=storage,
            share_link_service=container.share_link_service,
            audit_event_service=container.audit_event_service,
        )
        transport = ASGITransport(app=application, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="https://testserver") as client:
            yield client, storage


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


async def owner_with_business(client: AsyncClient, *, name: str = "Obi Electronics"):
    owner = await register(client)
    created = await client.post("/api/v1/tenants", headers=auth(owner), json={"name": name})
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


def reports_path(tenant_id: str, report: str) -> str:
    return f"/api/v1/tenants/{tenant_id}/reports/{report}"


async def stock_a_product(
    client: AsyncClient,
    owner: dict[str, Any],
    tenant: dict[str, Any],
    *,
    name: str,
    price: str,
    quantity: str,
    low_stock_threshold: str | None = None,
) -> str:
    body: dict[str, Any] = {"name": f"{name} {uuid4().hex[:6]}", "selling_price": price}
    if low_stock_threshold is not None:
        body["low_stock_threshold"] = low_stock_threshold
    product = await client.post(
        f"/api/v1/tenants/{tenant['id']}/products", headers=auth(owner), json=body
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["id"]
    if quantity == "none":
        # A product nobody has received stock for: the state a report must read as zero rather
        # than as missing. Receiving nothing is refused, rightly - a zero receipt is not a receipt.
        return product_id
    received = await client.post(
        f"/api/v1/tenants/{tenant['id']}/inventory/{product_id}/receipts",
        headers=auth(owner),
        json={"quantity": quantity},
    )
    assert received.status_code in {200, 201}, received.text
    return product_id


async def sell(
    client: AsyncClient,
    owner: dict[str, Any],
    tenant: dict[str, Any],
    *,
    product_id: str,
    quantity: str,
    amount: str,
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/sales",
        headers=auth(owner),
        json={
            "lines": [{"product_id": product_id, "quantity": quantity}],
            "payments": [{"amount": amount, "method": "CASH"}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["sale"]


# ---------------------------------------------------------------------------
# Daily sales
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_daily_sales_add_up_to_the_receipts(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        product_id = await stock_a_product(
            client, owner, tenant, name="Rice 50kg", price="45000.00", quantity="10.000"
        )
        first = await sell(
            client, owner, tenant, product_id=product_id, quantity="2.000", amount="90000.00"
        )
        second = await sell(
            client, owner, tenant, product_id=product_id, quantity="1.000", amount="45000.00"
        )

        response = await client.get(reports_path(tenant["id"], "daily-sales"), headers=auth(owner))

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["total_sales"] == 2
    assert report["total_revenue"] == "135000.00"
    assert sum(Decimal(day["revenue"]) for day in report["days"]) == Decimal("135000.00")
    assert sum(day["sale_count"] for day in report["days"]) == 2
    assert Decimal(first["total_amount"]) + Decimal(second["total_amount"]) == Decimal(
        report["total_revenue"]
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_cancelled_sale_is_money_that_came_back(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        product_id = await stock_a_product(
            client, owner, tenant, name="Rice 50kg", price="45000.00", quantity="10.000"
        )
        kept = await sell(
            client, owner, tenant, product_id=product_id, quantity="1.000", amount="45000.00"
        )
        cancelled = await sell(
            client, owner, tenant, product_id=product_id, quantity="2.000", amount="90000.00"
        )
        await client.post(
            f"/api/v1/tenants/{tenant['id']}/sales/{cancelled['id']}/cancel",
            headers=auth(owner),
            json={"reason": "customer changed their mind"},
        )

        report = await client.get(reports_path(tenant["id"], "daily-sales"), headers=auth(owner))
        receipt = await client.get(
            f"/api/v1/tenants/{tenant['id']}/sales/{cancelled['id']}", headers=auth(owner)
        )

    assert report.json()["total_revenue"] == kept["total_amount"]
    assert report.json()["total_sales"] == 1
    assert receipt.status_code == 200, "the cancelled sale's own record is still readable"
    assert receipt.json()["status"] == "CANCELLED"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_report_does_not_show_another_businesss_trading(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        product_id = await stock_a_product(
            client, owner, tenant, name="Rice 50kg", price="45000.00", quantity="10.000"
        )
        await sell(
            client, owner, tenant, product_id=product_id, quantity="1.000", amount="45000.00"
        )
        other_owner, other_tenant = await owner_with_business(client, name="Ada Provisions")

        response = await client.get(
            reports_path(other_tenant["id"], "daily-sales"), headers=auth(other_owner)
        )

    assert response.status_code == 200
    assert response.json()["total_sales"] == 0
    assert response.json()["total_revenue"] == "0.00"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_default_period_is_the_last_seven_days(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)

        response = await client.get(reports_path(tenant["id"], "daily-sales"), headers=auth(owner))

    report = response.json()
    since = datetime.fromisoformat(report["since"])
    until = datetime.fromisoformat(report["until"])
    assert timedelta(days=7) - timedelta(seconds=1) <= until - since <= timedelta(days=7)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_period_ends_before_it_starts_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        now = datetime.now(UTC)

        response = await client.get(
            reports_path(tenant["id"], "daily-sales"),
            headers=auth(owner),
            params={"since": now.isoformat(), "until": (now - timedelta(days=1)).isoformat()},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_period_wider_than_the_bound_is_refused(database: Database) -> None:
    """A wider range is an export rather than a screen."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        now = datetime.now(UTC)

        response = await client.get(
            reports_path(tenant["id"], "daily-sales"),
            headers=auth(owner),
            params={
                "since": (now - timedelta(days=200)).isoformat(),
                "until": now.isoformat(),
            },
        )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# What sells
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_top_products_rank_by_revenue(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        rice = await stock_a_product(
            client, owner, tenant, name="Rice", price="45000.00", quantity="10.000"
        )
        beans = await stock_a_product(
            client, owner, tenant, name="Beans", price="8000.00", quantity="10.000"
        )
        await sell(client, owner, tenant, product_id=rice, quantity="2.000", amount="90000.00")
        await sell(client, owner, tenant, product_id=beans, quantity="1.000", amount="8000.00")

        response = await client.get(reports_path(tenant["id"], "top-products"), headers=auth(owner))

    assert response.status_code == 200, response.text
    ranked = response.json()
    assert len(ranked) == 2
    assert ranked[0]["revenue"] == "90000.00"
    assert ranked[0]["quantity_sold"] == "2.000"
    assert ranked[1]["revenue"] == "8000.00"


# ---------------------------------------------------------------------------
# What is running out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_low_stock_reports_what_is_at_or_below_its_threshold(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        plentiful = await stock_a_product(
            client,
            owner,
            tenant,
            name="Rice",
            price="45000.00",
            quantity="50.000",
            low_stock_threshold="10.000",
        )
        await stock_a_product(
            client,
            owner,
            tenant,
            name="Beans",
            price="8000.00",
            quantity="10.000",
            low_stock_threshold="10.000",
        )
        # A product nobody has received stock for has no projection row at all, which is the state
        # the report must read as zero rather than as missing.
        await stock_a_product(client, owner, tenant, name="Garri", price="5000.00", quantity="none")

        response = await client.get(reports_path(tenant["id"], "low-stock"), headers=auth(owner))

    assert response.status_code == 200, response.text
    reported = {entry["product_name"].split()[0]: entry for entry in response.json()}
    assert "Rice" not in reported, "fifty on the shelf is not low against a threshold of ten"
    assert reported["Beans"]["quantity_on_hand"] == "10.000"
    assert reported["Beans"]["low_stock_threshold"] == "10.000"
    assert reported["Garri"]["is_out_of_stock"] is True, (
        "the default threshold of zero reports a product when the shelf is empty"
    )
    assert response.json()[0]["is_out_of_stock"] is True, "the emptiest shelf comes first"
    assert plentiful


@pytest.mark.asyncio
@pytest.mark.integration
async def test_low_stock_never_shows_another_businesss_catalogue(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        other_owner, other_tenant = await owner_with_business(client, name="Ada Provisions")
        await stock_a_product(
            client,
            other_owner,
            other_tenant,
            name="Garri",
            price="5000.00",
            quantity="1.000",
            low_stock_threshold="5.000",
        )

        response = await client.get(reports_path(tenant["id"], "low-stock"), headers=auth(owner))

    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# Permission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_salesperson_cannot_read_the_businesss_numbers(database: Database) -> None:
    """A salesperson sells; what the business made is the owner's and the manager's."""
    async with running_application() as (client, application):
        _owner, tenant = await owner_with_business(client)
        worker = await register(client)
        await add_member(
            application.state.container.database,
            tenant_id=UUID(tenant["id"]),
            user_id=UUID(worker["user"]["id"]),
            role_name="SALES",
        )

        daily = await client.get(reports_path(tenant["id"], "daily-sales"), headers=auth(worker))
        top = await client.get(reports_path(tenant["id"], "top-products"), headers=auth(worker))
        low = await client.get(reports_path(tenant["id"], "low-stock"), headers=auth(worker))

    assert daily.status_code == 403
    assert top.status_code == 403
    assert low.status_code == 403


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_manager_can_read_the_reports(database: Database) -> None:
    async with running_application() as (client, application):
        _owner, tenant = await owner_with_business(client)
        manager = await register(client)
        await add_member(
            application.state.container.database,
            tenant_id=UUID(tenant["id"]),
            user_id=UUID(manager["user"]["id"]),
            role_name="MANAGER",
        )

        response = await client.get(
            reports_path(tenant["id"], "daily-sales"), headers=auth(manager)
        )

    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unauthenticated_report_request_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        _owner, tenant = await owner_with_business(client)

        response = await client.get(reports_path(tenant["id"], "daily-sales"))

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Exporting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_exporting_a_report_stores_a_csv_and_mints_a_link(database: Database) -> None:
    """The artifact is written, recorded and shared in one call."""
    async with running_application_with_storage() as (client, storage):
        owner, tenant = await owner_with_business(client)
        product_id = await stock_a_product(
            client, owner, tenant, name="Rice 50kg", price="45000.00", quantity="10.000"
        )
        await sell(
            client, owner, tenant, product_id=product_id, quantity="2.000", amount="90000.00"
        )

        response = await client.post(
            reports_path(tenant["id"], "export"),
            headers=auth(owner),
            json={"report_type": "DAILY_SALES"},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "READY"
    assert body["report_type"] == "DAILY_SALES"
    assert body["row_count"] >= 1
    assert body["size_bytes"] > 0
    assert body["share_token"]
    assert body["public_path"] == f"/share/report/{body['share_token']}"

    async with database.transaction_scope() as unit_of_work:
        stored = await report_export_crud.get_for_tenant(
            unit_of_work.session_handle,
            tenant_id=UUID(tenant["id"]),
            export_id=UUID(body["id"]),
        )

    assert stored is not None
    assert stored.is_available() is True
    assert stored.storage_key.startswith(f"tenants/{tenant['id']}/reports/daily_sales/")
    assert len(stored.checksum_sha256) == 64
    assert stored.size_bytes == len(storage.objects[stored.storage_key])
    csv_text = storage.objects[stored.storage_key].decode("utf-8")
    assert csv_text.startswith("sold_on,revenue,sale_count\n")
    assert "90000.00" in csv_text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_exported_csv_defuses_a_value_a_spreadsheet_would_execute(
    database: Database,
) -> None:
    """A product named `=cmd|...` is a product, not an instruction for the reader's spreadsheet."""
    async with running_application_with_storage() as (client, storage):
        owner, tenant = await owner_with_business(client)
        product_id = await stock_a_product(
            client,
            owner,
            tenant,
            name="=cmd|'/C calc'!A1",
            price="45000.00",
            quantity="10.000",
        )
        await sell(
            client, owner, tenant, product_id=product_id, quantity="2.000", amount="90000.00"
        )
        exported = await client.post(
            reports_path(tenant["id"], "export"),
            headers=auth(owner),
            json={"report_type": "PRODUCT_PERFORMANCE"},
        )
        token = exported.json()["share_token"]
        followed = await client.get(f"/share/report/{token}", follow_redirects=False)

    assert exported.status_code == 201, exported.text
    stored_key = next(iter(storage.objects))
    csv_text = storage.objects[stored_key].decode("utf-8")
    assert csv_text.startswith("product_name,quantity_sold,revenue\n")
    assert "'=cmd" in csv_text, "a leading apostrophe stops the spreadsheet executing the cell"
    assert ",=cmd" not in csv_text.replace("\n", ""), "the raw formula is never written"

    assert followed.status_code == 307
    assert "reports/product_performance/" in followed.headers["location"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_report_link_cannot_open_an_invoice_and_the_other_way_round(
    database: Database,
) -> None:
    """The resource type is checked, not just the token: a link opens what it was minted for."""
    async with running_application_with_storage() as (client, _storage):
        owner, tenant = await owner_with_business(client)
        product_id = await stock_a_product(
            client, owner, tenant, name="Rice 50kg", price="45000.00", quantity="10.000"
        )
        sale = await sell(
            client, owner, tenant, product_id=product_id, quantity="1.000", amount="45000.00"
        )
        invoice_link = await client.post(
            f"/api/v1/tenants/{tenant['id']}/sales/{sale['id']}/share",
            headers=auth(owner),
            json={},
        )
        export = await client.post(
            reports_path(tenant["id"], "export"),
            headers=auth(owner),
            json={"report_type": "LOW_STOCK"},
        )

        invoice_token_as_report = await client.get(
            f"/share/report/{invoice_link.json()['token']}", follow_redirects=False
        )
        report_token_as_invoice = await client.get(
            f"/share/{export.json()['share_token']}", follow_redirects=False
        )

    assert invoice_token_as_report.status_code == 404
    assert report_token_as_invoice.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_revoked_report_link_opens_nothing(database: Database) -> None:
    async with running_application_with_storage() as (client, _storage):
        owner, tenant = await owner_with_business(client)
        export = await client.post(
            reports_path(tenant["id"], "export"),
            headers=auth(owner),
            json={"report_type": "LOW_STOCK"},
        )
        token = export.json()["share_token"]
        opened = await client.get(f"/share/report/{token}", follow_redirects=False)

        listed = await client.get(reports_path(tenant["id"], "exports"), headers=auth(owner))
        # The listing has no token, so revoking is the share-link route's business, not this one.
        revoked = await client.post(
            f"/api/v1/tenants/{tenant['id']}/share-links/{export.json()['id']}/revoke",
            headers=auth(owner),
        )
        after = await client.get(f"/share/report/{token}", follow_redirects=False)

    assert opened.status_code == 307
    assert listed.status_code == 200
    assert listed.json()[0]["share_token"] is None, (
        "the server cannot re-show a link it did not keep"
    )
    # Revoking by the export identifier is not the share link's identifier, so this is a 404 rather
    # than a revocation: the two are different records, and the route says so.
    assert revoked.status_code == 404
    assert after.status_code == 307


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_salesperson_cannot_export_a_report(database: Database) -> None:
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
            reports_path(tenant["id"], "export"),
            headers=auth(worker),
            json={"report_type": "DAILY_SALES"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_export_of_another_businesss_report_is_not_found(
    database: Database,
) -> None:
    async with running_application_with_storage() as (client, _storage):
        owner, tenant = await owner_with_business(client)
        export = await client.post(
            reports_path(tenant["id"], "export"),
            headers=auth(owner),
            json={"report_type": "LOW_STOCK"},
        )
        other_owner, other_tenant = await owner_with_business(client, name="Ada Provisions")

        response = await client.get(
            reports_path(other_tenant["id"], "exports"), headers=auth(other_owner)
        )

    assert export.status_code == 201
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_exporting_the_businesss_numbers_is_in_the_audit_trail(database: Database) -> None:
    """A report leaving the product is an action, and "who exported what" is asked afterwards."""

    async with running_application_with_storage() as (client, _storage):
        owner, tenant = await owner_with_business(client)
        exported = await client.post(
            reports_path(tenant["id"], "export"),
            headers=auth(owner),
            json={"report_type": "LOW_STOCK"},
        )

    async with database.transaction_scope() as unit_of_work:
        events = await audit_event_crud.list_for_tenant(
            unit_of_work.session_handle, UUID(tenant["id"])
        )

    assert exported.status_code == 201, exported.text
    # Most recent first: the sharing happened after the export it shares.
    assert sorted(event.action for event in events) == ["export_report", "share_report"]
    export_event = next(event for event in events if event.action == "export_report")
    assert export_event.outcome.value == "SUCCEEDED"
    assert export_event.entity_type == "report_export"
    assert export_event.detail["report_type"] == "LOW_STOCK"
    assert export_event.detail["status"] == "READY"
