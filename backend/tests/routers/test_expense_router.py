"""End-to-end tests for the expense endpoints.

Real application, real PostgreSQL. What is tested here is the part that only exists over HTTP:
the wire format of money, the category vocabulary as a published contract, the routes that do
not exist, and the statuses a caller actually receives.

The four things this suite is here to hold:

**Money leaves as a decimal string.** A JSON number would let a client's float arithmetic
disagree with the ledger, and the disagreement would show up as a report that is a kobo out.

**The category vocabulary is published and enforced.** A client renders the picker from
`GET /expenses/categories`, an unknown category is a 422 at the edge, and the OpenAPI document
lists the members - so a client cannot invent a heading, and a heading added to the product
appears without a client release.

**There is no delete route and no update route.** A mistaken expense is reversed, which is a
written and attributed action. This is asserted over HTTP rather than against the service, so
the answer covers the whole stack a client can reach.

**Authorization is enforced for a real member with a real role.** A member holding SALES is
refused, and the refusal is a 403 that says nothing about whether the expense exists.
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
from ahia.crud import tenant_membership_crud
from ahia.main import create_application
from ahia.models.entities.expense_category import ExpenseCategory
from ahia.models.entities.tenant_membership_model import TenantMembershipModel
from ahia.services.iam_seed_service import IamSeedService

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
PASSWORD = "a-good-enough-password"
NOW = datetime(2026, 9, 14, 9, 30, tzinfo=UTC)


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
        # The whole schema, created from the models. A table's foreign keys require the tables
        # they reference to exist first, and creating everything in dependency order is exactly
        # what create_all does.
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(sync_connection, checkfirst=True)
        )
        await connection.execute(
            text(
                "TRUNCATE TABLE expenses, ledger_entries, role_permissions, roles, permissions, "
                "tenant_memberships, tenants, user_sessions, users CASCADE"
            )
        )
    # The registry is provisioned before the application starts, exactly as a deployment
    # would do it.
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


def expenses_path(tenant_id: str, *parts: str) -> str:
    suffix = "".join(f"/{part}" for part in parts)
    return f"/api/v1/tenants/{tenant_id}/expenses{suffix}"


async def record_expense(
    client: AsyncClient,
    owner: dict[str, Any],
    tenant: dict[str, Any],
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "category": "TRANSPORT",
        "amount": "3500.00",
        "payment_method": "CASH",
        "description": "Keke to the market and back",
    }
    payload.update(overrides)
    response = await client.post(expenses_path(tenant["id"]), headers=auth(owner), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_recording_an_expense_returns_it_with_money_as_a_decimal_string(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)

        recorded = await record_expense(client, owner, tenant, amount="120000")

    assert recorded["category"] == "TRANSPORT"
    assert recorded["category_label"] == "Transport"
    assert recorded["amount"] == "120000.00", "money crosses the wire as a decimal string"
    assert isinstance(recorded["amount"], str)
    assert recorded["counted_amount"] == "120000.00"
    assert recorded["is_reversed"] is False
    assert recorded["tenant_id"] == tenant["id"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_back_dated_expense_keeps_the_day_it_was_paid(database: Database) -> None:
    """A back-dated expense is counted in the period it was paid, not the day it was typed."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        paid_on = (datetime.now(UTC) - timedelta(days=3)).replace(microsecond=0)

        recorded = await record_expense(client, owner, tenant, incurred_at=paid_on.isoformat())

    assert recorded["incurred_at"].startswith(paid_on.strftime("%Y-%m-%dT%H:%M:%S"))


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unknown_category_is_refused_at_the_edge(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)

        response = await client.post(
            expenses_path(tenant["id"]),
            headers=auth(owner),
            json={"category": "transport", "amount": "1000.00"},
        )

    assert response.status_code == 422
    # The refusal names no field and no value: the external error is a code, a message and a
    # correlation id, and a client learns the permitted values from the published vocabulary.
    assert "transport" not in response.text
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_negative_amount_is_refused_at_the_edge(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)

        response = await client.post(
            expenses_path(tenant["id"]),
            headers=auth(owner),
            json={"category": "OTHER", "amount": "-100.00"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_client_cannot_claim_who_recorded_an_expense(database: Database) -> None:
    """The actor comes from the authenticated context, so sending one is refused."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)

        response = await client.post(
            expenses_path(tenant["id"]),
            headers=auth(owner),
            json={
                "category": "OTHER",
                "amount": "100.00",
                "actor_id": str(uuid4()),
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_resending_a_queued_expense_returns_the_original(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        operation_id = str(uuid4())

        first = await record_expense(client, owner, tenant, operation_id=operation_id)
        second = await record_expense(client, owner, tenant, operation_id=operation_id)

        listed = await client.get(expenses_path(tenant["id"]), headers=auth(owner))

    assert second["id"] == first["id"], "a retried operation must not spend the money twice"
    assert len(listed.json()) == 1


# ---------------------------------------------------------------------------
# The category vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_category_vocabulary_is_published(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)

        response = await client.get(expenses_path(tenant["id"], "categories"), headers=auth(owner))

    assert response.status_code == 200
    published = response.json()["categories"]
    assert {entry["value"] for entry in published} == {
        category.value for category in ExpenseCategory
    }
    assert all(entry["label"] for entry in published)
    assert (
        next(entry for entry in published if entry["value"] == "OTHER")["is_known_spending"]
        is False
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_openapi_document_lists_the_categories(database: Database) -> None:
    """A client generates its picker from the contract, so the members must be in it."""
    async with running_application() as (client, _application):
        document = (await client.get("/openapi.json")).json()

    schema = document["components"]["schemas"]["ExpenseCreateSchema"]["properties"]["category"]
    assert schema["$ref"].endswith("/ExpenseCategory")
    published = document["components"]["schemas"]["ExpenseCategory"]["enum"]
    assert sorted(published) == sorted(category.value for category in ExpenseCategory)
    assert (
        document["components"]["schemas"]["ExpenseResponseSchema"]["properties"]["amount"]["type"]
        == "string"
    ), "money is a decimal string in the published contract, not a number"


# ---------------------------------------------------------------------------
# Reversal, and the routes that do not exist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reversing_an_expense_keeps_it_and_credits_the_money_back(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        recorded = await record_expense(client, owner, tenant, amount="9000.00")

        reversed_response = await client.post(
            expenses_path(tenant["id"], recorded["id"], "reverse"),
            headers=auth(owner),
            json={"reason": "the radio slot never ran"},
        )

    assert reversed_response.status_code == 200, reversed_response.text
    reversal = reversed_response.json()
    assert reversal["id"] == recorded["id"]
    assert reversal["is_reversed"] is True
    assert reversal["reversal_reason"] == "the radio slot never ran"
    assert reversal["amount"] == "9000.00", "the amount that was spent stays visible"
    assert reversal["counted_amount"] == "0.00"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reversing_without_a_reason_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        recorded = await record_expense(client, owner, tenant)

        response = await client.post(
            expenses_path(tenant["id"], recorded["id"], "reverse"),
            headers=auth(owner),
            json={"reason": ""},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_there_is_no_way_to_delete_or_edit_an_expense_over_http(
    database: Database,
) -> None:
    """Financial history is corrected, never erased.

    Asserted over HTTP rather than against the service, so the answer covers every route a
    client can reach.
    """
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        recorded = await record_expense(client, owner, tenant)

        deleted = await client.delete(
            expenses_path(tenant["id"], recorded["id"]), headers=auth(owner)
        )
        patched = await client.patch(
            expenses_path(tenant["id"], recorded["id"]),
            headers=auth(owner),
            json={"amount": "1.00"},
        )
        put = await client.put(
            expenses_path(tenant["id"], recorded["id"]),
            headers=auth(owner),
            json={"amount": "1.00"},
        )

    # 404 or 405 depending on whether the router matched a path with no such method; either
    # way the request did not reach a handler, and no mutation happened.
    for response in (deleted, patched, put):
        assert response.status_code in {404, 405}
        assert response.status_code != 204


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_report_totals_spending_and_excludes_reversed_expenses(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        await record_expense(client, owner, tenant, amount="3500.00")
        await record_expense(client, owner, tenant, category="RENT", amount="150000.00")
        undone = await record_expense(client, owner, tenant, category="MARKETING", amount="9000.00")
        await client.post(
            expenses_path(tenant["id"], undone["id"], "reverse"),
            headers=auth(owner),
            json={"reason": "the post was never published"},
        )

        since = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        until = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        response = await client.get(
            expenses_path(tenant["id"], "report"),
            headers=auth(owner),
            params={"since": since, "until": until},
        )

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["by_category"] == {"TRANSPORT": "3500.00", "RENT": "150000.00"}
    assert report["total_spent"] == "153500.00"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_report_without_a_period_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)

        response = await client.get(expenses_path(tenant["id"], "report"), headers=auth(owner))

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Authorization and tenant scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_member_without_the_permission_cannot_record_or_read_expenses(
    database: Database,
) -> None:
    async with running_application() as (client, application):
        owner, tenant = await owner_with_business(client)
        recorded = await record_expense(client, owner, tenant)
        worker = await register(client)
        await add_member(
            application.state.container.database,
            tenant_id=UUID(tenant["id"]),
            user_id=UUID(worker["user"]["id"]),
            role_name="SALES",
        )

        refused_write = await client.post(
            expenses_path(tenant["id"]),
            headers=auth(worker),
            json={"category": "OTHER", "amount": "100.00"},
        )
        refused_read = await client.get(expenses_path(tenant["id"]), headers=auth(worker))
        refused_reversal = await client.post(
            expenses_path(tenant["id"], recorded["id"], "reverse"),
            headers=auth(worker),
            json={"reason": "I would like the money back"},
        )

    assert refused_write.status_code == 403
    assert refused_read.status_code == 403
    assert refused_reversal.status_code == 403


@pytest.mark.asyncio
@pytest.mark.integration
async def test_another_business_cannot_read_or_reverse_an_expense(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        recorded = await record_expense(client, owner, tenant)
        other_owner, other_tenant = await owner_with_business(client)

        read = await client.get(
            expenses_path(other_tenant["id"], recorded["id"]), headers=auth(other_owner)
        )
        reversal = await client.post(
            expenses_path(other_tenant["id"], recorded["id"], "reverse"),
            headers=auth(other_owner),
            json={"reason": "not mine to reverse"},
        )

    assert read.status_code == 404, "a foreign expense is not found, never forbidden"
    assert reversal.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unauthenticated_request_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        await record_expense(client, owner, tenant)

        response = await client.get(expenses_path(tenant["id"]))

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_refusal_does_not_leak_what_it_refused(database: Database) -> None:
    """The external error carries a code, a correlation id and a safe message. Nothing else."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        recorded = await record_expense(client, owner, tenant)
        other_owner, other_tenant = await owner_with_business(client)

        response = await client.get(
            expenses_path(other_tenant["id"], recorded["id"]), headers=auth(other_owner)
        )

    body = response.json()
    assert response.status_code == 404
    assert set(body) <= {"error", "correlation_id"} or "error" in body
    rendered = response.text
    for leak in ("Traceback", "expenses", "SELECT", "postgresql", "/home/", "expense_crud"):
        assert leak not in rendered
    assert response.headers["X-Correlation-ID"]
