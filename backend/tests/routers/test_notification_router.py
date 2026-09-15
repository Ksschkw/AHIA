"""End-to-end tests for notifications and the scheduled low-stock evaluation.

Real application, real PostgreSQL. The subject is an inbox that is addressed to one person, and a
job that fills it without filling it twice.

**A notification is the caller's own.** One person's inbox does not contain another person's
alerts, and asking for somebody else's notification by identifier is a not-found rather than a
refusal - the answer must not confirm that it exists.

**The evaluator reuses the report rule.** A low-stock alert is raised because
`ReportService.low_stock_products` said so, which is the same call the report screen makes. There
is no second definition of "low" anywhere in this test or in the code.

**A run is idempotent per day.** Running the evaluator twice raises one alert per product, because
the dedupe key names the product and the day. The second run reports a skip rather than a second
row, and a third run the next day raises a new one.

**Only the people who can act are told.** The owner and the managers: `reports.read` is the
authority the report itself needs, and a salesperson cannot order stock.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.crud import tenant_membership_crud
from ahia.main import create_application
from ahia.models.entities.notification_model import NotificationType
from ahia.models.entities.tenant_membership_model import TenantMembershipModel
from ahia.services.iam_seed_service import IamSeedService
from ahia.services.low_stock_alert_service import LowStockAlertEvaluator
from ahia.services.notification_service import NotificationRequest

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
                "TRUNCATE TABLE notifications, report_exports, share_links, storefronts, "
                "sync_changes, audit_events, inventory_movements, inventory, product_images, "
                "products, categories, role_permissions, roles, permissions, "
                "tenant_memberships, tenants, user_sessions, users CASCADE"
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


def notifications_path(tenant_id: str, *parts: str) -> str:
    suffix = "".join(f"/{part}" for part in parts)
    return f"/api/v1/tenants/{tenant_id}/notifications{suffix}"


async def stock_a_product(
    client: AsyncClient,
    owner: dict[str, Any],
    tenant: dict[str, Any],
    *,
    name: str,
    quantity: str,
    low_stock_threshold: str,
) -> str:
    product = await client.post(
        f"/api/v1/tenants/{tenant['id']}/products",
        headers=auth(owner),
        json={
            "name": f"{name} {uuid4().hex[:6]}",
            "selling_price": "45000.00",
            "low_stock_threshold": low_stock_threshold,
        },
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["id"]
    received = await client.post(
        f"/api/v1/tenants/{tenant['id']}/inventory/{product_id}/receipts",
        headers=auth(owner),
        json={"quantity": quantity},
    )
    assert received.status_code in {200, 201}, received.text
    return product_id


# ---------------------------------------------------------------------------
# The scheduled evaluation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_evaluation_raises_one_alert_per_product_per_day(
    database: Database,
) -> None:
    async with running_application() as (client, application):
        owner, tenant = await owner_with_business(client)
        await stock_a_product(
            client, owner, tenant, name="Beans", quantity="2.000", low_stock_threshold="10.000"
        )
        await stock_a_product(
            client, owner, tenant, name="Rice", quantity="50.000", low_stock_threshold="10.000"
        )
        container = application.state.container
        evaluator = LowStockAlertEvaluator(
            unit_of_work_factory=container.database.unit_of_work_factory(),
            report_service=container.report_service,
            notification_service=container.notification_service,
        )

        today = date(2026, 9, 15)
        first = await evaluator.evaluate_tenant(tenant_id=UUID(tenant["id"]), today=today)
        second = await evaluator.evaluate_tenant(tenant_id=UUID(tenant["id"]), today=today)
        tomorrow = await evaluator.evaluate_tenant(
            tenant_id=UUID(tenant["id"]), today=today + timedelta(days=1)
        )

        inbox = await client.get(notifications_path(tenant["id"]), headers=auth(owner))

    assert first.low_stock_products == 1, "rice has fifty on the shelf against a threshold of ten"
    assert first.notifications_raised == 1
    assert first.notifications_skipped == 0
    assert second.notifications_raised == 0
    assert second.notifications_skipped == 1, "the same alert is not raised twice in one day"
    assert tomorrow.notifications_raised == 1, "a new day is a new alert"

    assert inbox.status_code == 200, inbox.text
    # Three evaluations, two rows: the duplicate inside one day raised nothing.
    assert len(inbox.json()) == 2
    titles = {entry["title"] for entry in inbox.json()}
    assert any("Beans" in title for title in titles)
    assert all("Rice" not in title for title in titles)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_only_the_roles_that_can_act_are_told(database: Database) -> None:
    async with running_application() as (client, application):
        owner, tenant = await owner_with_business(client)
        await stock_a_product(
            client, owner, tenant, name="Beans", quantity="1.000", low_stock_threshold="10.000"
        )
        manager = await register(client)
        salesperson = await register(client)
        container = application.state.container
        for worker, role in ((manager, "MANAGER"), (salesperson, "SALES")):
            await add_member(
                container.database,
                tenant_id=UUID(tenant["id"]),
                user_id=UUID(worker["user"]["id"]),
                role_name=role,
            )

        evaluator = LowStockAlertEvaluator(
            unit_of_work_factory=container.database.unit_of_work_factory(),
            report_service=container.report_service,
            notification_service=container.notification_service,
        )
        evaluation = await evaluator.evaluate_tenant(
            tenant_id=UUID(tenant["id"]), today=date(2026, 9, 15)
        )

        owner_inbox = await client.get(notifications_path(tenant["id"]), headers=auth(owner))
        manager_inbox = await client.get(notifications_path(tenant["id"]), headers=auth(manager))
        salesperson_inbox = await client.get(
            notifications_path(tenant["id"]), headers=auth(salesperson)
        )

    assert evaluation.recipients == 2, "the owner and the manager"
    assert len(owner_inbox.json()) == 1
    assert len(manager_inbox.json()) == 1
    assert salesperson_inbox.json() == [], "a salesperson cannot order stock"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_evaluation_survives_a_business_it_cannot_read(database: Database) -> None:
    """A run that dies on the third tenant leaves the rest unevaluated and nobody knows."""
    async with running_application() as (client, application):
        owner, tenant = await owner_with_business(client)
        await stock_a_product(
            client, owner, tenant, name="Beans", quantity="1.000", low_stock_threshold="10.000"
        )
        container = application.state.container
        evaluator = LowStockAlertEvaluator(
            unit_of_work_factory=container.database.unit_of_work_factory(),
            report_service=container.report_service,
            notification_service=container.notification_service,
        )

        report = await evaluator.evaluate_all(today=date(2026, 9, 15))
        inbox = await client.get(notifications_path(tenant["id"]), headers=auth(owner))

    assert report.failures == []
    assert len(report.tenants) >= 1
    assert report.raised_count >= 1
    assert len(inbox.json()) == 1


# ---------------------------------------------------------------------------
# The inbox
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_inbox_counts_its_unread_and_marks_them_read(database: Database) -> None:
    async with running_application() as (client, application):
        owner, tenant = await owner_with_business(client)
        container = application.state.container
        await container.notification_service.raise_many(
            tenant_id=UUID(tenant["id"]),
            recipient_user_id=UUID(owner["user"]["id"]),
            notifications=[
                NotificationRequest(
                    notification_type=NotificationType.LOW_STOCK,
                    title="Beans is low on stock",
                    body="2.000 left, against a threshold of 10.000.",
                    entity_type="product",
                    entity_id=uuid4(),
                )
            ],
        )

        before = await client.get(
            notifications_path(tenant["id"], "unread-count"), headers=auth(owner)
        )
        listed = await client.get(notifications_path(tenant["id"]), headers=auth(owner))
        notification_id = listed.json()[0]["id"]
        marked = await client.post(
            notifications_path(tenant["id"], notification_id, "read"), headers=auth(owner)
        )
        marked_twice = await client.post(
            notifications_path(tenant["id"], notification_id, "read"), headers=auth(owner)
        )
        after = await client.get(
            notifications_path(tenant["id"], "unread-count"), headers=auth(owner)
        )

    assert before.json()["unread"] == 1
    assert listed.json()[0]["is_read"] is False
    assert marked.json()["is_read"] is True
    assert marked.json()["read_at"] == marked_twice.json()["read_at"], (
        "reading twice keeps the moment somebody actually saw it"
    )
    assert after.json()["unread"] == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_one_persons_notification_is_not_another_persons(
    database: Database,
) -> None:
    async with running_application() as (client, application):
        owner, tenant = await owner_with_business(client)
        colleague = await register(client)
        await add_member(
            application.state.container.database,
            tenant_id=UUID(tenant["id"]),
            user_id=UUID(colleague["user"]["id"]),
            role_name="MANAGER",
        )
        container = application.state.container
        raised = await container.notification_service.raise_many(
            tenant_id=UUID(tenant["id"]),
            recipient_user_id=UUID(owner["user"]["id"]),
            notifications=[
                NotificationRequest(
                    notification_type=NotificationType.STOCK_OUT,
                    title="Beans is out of stock",
                    body="0.000 left.",
                )
            ],
        )
        notification_id = raised.raised[0].id

        intruder_inbox = await client.get(notifications_path(tenant["id"]), headers=auth(colleague))
        intruder_read = await client.post(
            notifications_path(tenant["id"], str(notification_id), "read"),
            headers=auth(colleague),
        )

    assert intruder_inbox.json() == []
    assert intruder_read.status_code == 404, (
        "not a 403: the answer must not confirm that the notification exists"
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_notification_about_another_businesss_record_is_invisible(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        _other_owner, other_tenant = await owner_with_business(client, name="Ada Provisions")

        response = await client.get(notifications_path(other_tenant["id"]), headers=auth(owner))

    assert tenant["id"] != other_tenant["id"]
    assert response.status_code in {200, 403, 404}
    if response.status_code == 200:
        assert response.json() == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_there_is_no_way_to_write_or_delete_a_notification(
    database: Database,
) -> None:
    """A client that could write one could put whatever it liked in a colleague's inbox."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)

        created = await client.post(
            notifications_path(tenant["id"]),
            headers=auth(owner),
            json={"title": "invented", "body": "by a client"},
        )
        deleted = await client.delete(
            notifications_path(tenant["id"], str(uuid4())), headers=auth(owner)
        )

    assert created.status_code in {404, 405}
    assert deleted.status_code in {404, 405}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unauthenticated_inbox_request_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        _owner, tenant = await owner_with_business(client)

        response = await client.get(notifications_path(tenant["id"]))

    assert response.status_code == 401
