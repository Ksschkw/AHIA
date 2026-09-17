"""End-to-end tests for the product endpoints.

Real application, real PostgreSQL, real sessions. What is tested here is the part that
only exists over HTTP: the contract a client sees, the status codes, and the envelope
that must never carry internal detail.

The contract detail worth stating: money arrives as a number or a decimal string and
always leaves as a decimal string, so no client has to pass a price through a binary
float. The assertions below check the rendered JSON rather than a parsed value, because
that is what a client actually receives.
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
            text("TRUNCATE TABLE products, categories, tenant_memberships, tenants, users CASCADE")
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


def products_path(tenant_id: str) -> str:
    return f"/api/v1/tenants/{tenant_id}/products"


def product_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "Coca Cola 50cl",
        "selling_price": "250.00",
        "cost_price": "180.00",
        "sku": f"SKU-{uuid4().hex[:8].upper()}",
    }
    payload.update(overrides)
    return payload


async def create_product(
    client: AsyncClient, owner: dict[str, Any], tenant: dict[str, Any], **kw: Any
):
    response = await client.post(
        products_path(tenant["id"]), headers=auth(owner), json=product_payload(**kw)
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Creating and reading
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_creating_a_product_returns_it_hidden_from_customers(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        response = await client.post(
            products_path(tenant["id"]),
            headers=auth(owner),
            json=product_payload(name="Coca Cola 50cl"),
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Coca Cola 50cl"
    assert body["slug"] == "coca-cola-50cl"
    assert body["is_active"] is True
    assert body["is_published"] is False
    assert body["is_visible_to_customers"] is False
    assert body["public_token"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_money_leaves_as_a_decimal_string(database: Database) -> None:
    """The rendered JSON is the contract: no client receives a binary float for money."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        response = await client.post(
            products_path(tenant["id"]),
            headers=auth(owner),
            json=product_payload(selling_price=250.5, cost_price="180.25"),
        )

    assert response.status_code == 201, response.text
    assert '"selling_price":"250.50"' in response.text
    assert '"cost_price":"180.25"' in response.text
    assert response.json()["selling_price"] == "250.50"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_price_with_too_many_decimal_places_is_rejected(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        response = await client.post(
            products_path(tenant["id"]),
            headers=auth(owner),
            json=product_payload(selling_price="250.005"),
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_slug_and_the_lifecycle_cannot_be_sent(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        with_slug = await client.post(
            products_path(tenant["id"]),
            headers=auth(owner),
            json=product_payload(slug="coke"),
        )
        with_state = await client.post(
            products_path(tenant["id"]),
            headers=auth(owner),
            json=product_payload(is_published=True),
        )

    assert with_slug.status_code == 422
    assert with_state.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_duplicate_name_is_a_conflict_without_leaking_internals(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        await create_product(client, owner, tenant, name="Coca Cola 50cl")
        duplicate = await client.post(
            products_path(tenant["id"]),
            headers=auth(owner),
            json=product_payload(name="coca cola 50cl", sku=None),
        )

    assert duplicate.status_code == 409
    body = duplicate.json()
    assert body["error"]["code"] == "CONFLICT"
    assert body["error"]["correlation_id"]

    rendered = duplicate.text
    for internal in ("uq_products", "products", "INSERT", "sqlalchemy", "tenant_id"):
        assert internal not in rendered, f"the response leaked {internal}"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_listing_returns_the_catalogue_in_reading_order(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        for name in ("Sugar", "Bread", "Apple"):
            await create_product(client, owner, tenant, name=name, sku=None)

        listed = await client.get(products_path(tenant["id"]), headers=auth(owner))

    assert listed.status_code == 200
    assert [product["name"] for product in listed.json()] == ["Apple", "Bread", "Sugar"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unknown_product_is_a_404_in_the_standard_envelope(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        response = await client.get(f"{products_path(tenant['id'])}/{uuid4()}", headers=auth(owner))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_caller_outside_the_business_cannot_read_its_catalogue(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        await create_product(client, owner, tenant, name="Coca Cola 50cl")

        outsider = await register(client)
        response = await client.get(products_path(tenant["id"]), headers=auth(outsider))

    assert response.status_code in {403, 404}
    assert "Coca Cola" not in response.text


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_partial_edit_leaves_the_unsent_fields_alone(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await create_product(client, owner, tenant, name="Coca Cola 50cl")
        updated = await client.patch(
            f"{products_path(tenant['id'])}/{created['id']}",
            headers=auth(owner),
            json={"name": "Coke 50cl", "selling_price": "275.00"},
        )

    body = updated.json()
    assert updated.status_code == 200, updated.text
    assert body["name"] == "Coke 50cl"
    assert body["slug"] == created["slug"], "the public handle does not move"
    assert body["selling_price"] == "275.00"
    assert body["cost_price"] == created["cost_price"]
    assert body["sku"] == created["sku"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_clearing_a_cost_or_a_description_by_sending_null(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await create_product(client, owner, tenant, description="Chilled bottle")
        cleared = await client.patch(
            f"{products_path(tenant['id'])}/{created['id']}",
            headers=auth(owner),
            json={"cost_price": None, "description": None},
        )

    body = cleared.json()
    assert cleared.status_code == 200, cleared.text
    assert body["cost_price"] is None
    assert body["description"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_product_can_be_filed_under_a_category(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        category = await client.post(
            f"/api/v1/tenants/{tenant['id']}/categories",
            headers=auth(owner),
            json={"name": "Drinks"},
        )
        created = await create_product(client, owner, tenant)
        filed = await client.patch(
            f"{products_path(tenant['id'])}/{created['id']}",
            headers=auth(owner),
            json={"category_id": category.json()["id"]},
        )

    assert filed.status_code == 200, filed.text
    assert filed.json()["category_id"] == category.json()["id"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unknown_category_is_a_404(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await create_product(client, owner, tenant)
        response = await client.patch(
            f"{products_path(tenant['id'])}/{created['id']}",
            headers=auth(owner),
            json={"category_id": str(uuid4())},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_update_cannot_change_the_lifecycle_or_the_slug(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await create_product(client, owner, tenant)
        with_published = await client.patch(
            f"{products_path(tenant['id'])}/{created['id']}",
            headers=auth(owner),
            json={"is_published": True},
        )
        with_slug = await client.patch(
            f"{products_path(tenant['id'])}/{created['id']}",
            headers=auth(owner),
            json={"slug": "coke"},
        )

    assert with_published.status_code == 422
    assert with_slug.status_code == 422


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_publishing_makes_the_product_visible(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await create_product(client, owner, tenant)
        published = await client.post(
            f"{products_path(tenant['id'])}/{created['id']}/publish", headers=auth(owner)
        )

    body = published.json()
    assert published.status_code == 200, published.text
    assert body["is_published"] is True
    assert body["is_visible_to_customers"] is True
    assert body["public_token"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_publishing_twice_keeps_the_same_public_address(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await create_product(client, owner, tenant)
        first = await client.post(
            f"{products_path(tenant['id'])}/{created['id']}/publish", headers=auth(owner)
        )
        second = await client.post(
            f"{products_path(tenant['id'])}/{created['id']}/publish", headers=auth(owner)
        )

    assert first.json()["public_token"] == second.json()["public_token"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_withdrawing_and_republishing_keeps_the_link_a_customer_holds(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await create_product(client, owner, tenant)
        published = await client.post(
            f"{products_path(tenant['id'])}/{created['id']}/publish", headers=auth(owner)
        )
        hidden = await client.post(
            f"{products_path(tenant['id'])}/{created['id']}/unpublish", headers=auth(owner)
        )
        republished = await client.post(
            f"{products_path(tenant['id'])}/{created['id']}/publish", headers=auth(owner)
        )

    assert hidden.json()["is_published"] is False
    assert hidden.json()["is_active"] is True
    assert republished.json()["public_token"] == published.json()["public_token"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_deactivating_takes_the_product_off_the_storefront(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await create_product(client, owner, tenant)
        await client.post(
            f"{products_path(tenant['id'])}/{created['id']}/publish", headers=auth(owner)
        )
        retired = await client.delete(
            f"{products_path(tenant['id'])}/{created['id']}", headers=auth(owner)
        )

    body = retired.json()
    assert retired.status_code == 200, retired.text
    assert body["is_active"] is False
    assert body["is_published"] is False
    assert body["is_visible_to_customers"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_withdrawn_product_can_be_brought_back_unpublished(
    database: Database,
) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await create_product(client, owner, tenant)
        await client.delete(f"{products_path(tenant['id'])}/{created['id']}", headers=auth(owner))
        revived = await client.post(
            f"{products_path(tenant['id'])}/{created['id']}/activate", headers=auth(owner)
        )

    assert revived.status_code == 200, revived.text
    assert revived.json()["is_active"] is True
    assert revived.json()["is_published"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_publishing_a_withdrawn_product_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        created = await create_product(client, owner, tenant)
        await client.delete(f"{products_path(tenant['id'])}/{created['id']}", headers=auth(owner))
        response = await client.post(
            f"{products_path(tenant['id'])}/{created['id']}/publish", headers=auth(owner)
        )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Authorization over HTTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_salesperson_reads_the_catalogue_and_cannot_change_it(
    database: Database,
) -> None:
    async with running_application() as (client, application):
        owner, tenant = await owner_with_business(client)
        created = await create_product(client, owner, tenant)

        worker = await register(client)
        await add_member(
            application.state.container.database,
            tenant_id=UUID(tenant["id"]),
            user_id=UUID(worker["user"]["id"]),
            role_name="SALES",
        )

        listed = await client.get(products_path(tenant["id"]), headers=auth(worker))
        create_attempt = await client.post(
            products_path(tenant["id"]), headers=auth(worker), json=product_payload()
        )
        publish_attempt = await client.post(
            f"{products_path(tenant['id'])}/{created['id']}/publish", headers=auth(worker)
        )

    assert listed.status_code == 200
    assert [product["id"] for product in listed.json()] == [created["id"]]
    assert create_attempt.status_code == 403
    assert publish_attempt.status_code == 403
    assert create_attempt.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_manager_cannot_withdraw_a_product(database: Database) -> None:
    """MANAGER holds products.create and products.update, and not products.delete."""
    async with running_application() as (client, application):
        owner, tenant = await owner_with_business(client)
        created = await create_product(client, owner, tenant)

        manager = await register(client)
        await add_member(
            application.state.container.database,
            tenant_id=UUID(tenant["id"]),
            user_id=UUID(manager["user"]["id"]),
            role_name="MANAGER",
        )

        edited = await client.patch(
            f"{products_path(tenant['id'])}/{created['id']}",
            headers=auth(manager),
            json={"name": "Coke 50cl"},
        )
        withdrawn = await client.delete(
            f"{products_path(tenant['id'])}/{created['id']}", headers=auth(manager)
        )

    assert edited.status_code == 200, edited.text
    assert withdrawn.status_code == 403


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unauthenticated_request_is_refused(database: Database) -> None:
    async with running_application() as (client, _application):
        _owner, tenant = await owner_with_business(client)
        # No credentials at all: the setup above signed somebody in, and a browser would send that
        # session cookie. An unauthenticated caller is one with neither a header nor a cookie.
        client.cookies.clear()
        response = await client.get(products_path(tenant["id"]))

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# The price book: an item may follow its group, and the exception is marked
# ---------------------------------------------------------------------------


async def a_group(
    client: AsyncClient,
    owner: dict[str, Any],
    tenant: dict[str, Any],
    **prices: Any,
) -> dict[str, Any]:
    """Create a group - a grade, a heading - with whatever prices a test needs on it."""
    created = await client.post(
        f"/api/v1/tenants/{tenant['id']}/categories",
        headers=auth(owner),
        json={"name": "21D", **prices},
    )
    assert created.status_code == 201, created.text
    return created.json()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_item_under_a_priced_group_needs_no_price_of_its_own(
    database: Database,
) -> None:
    """One number for the grade: the group carries 350 and every model under it follows."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        group = await a_group(
            client,
            owner,
            tenant,
            default_normal_price="500.00",
            default_wholesale_price="350.00",
            default_pieces_per_pack=10,
        )

        created = await client.post(
            products_path(tenant["id"]),
            headers=auth(owner),
            json={"name": "Screenguard Hot 8", "category_id": group["id"]},
        )
        assert created.status_code == 201, created.text
        body = created.json()

    assert body["selling_price"] is None
    assert body["effective_normal_price"] == "500.00"
    assert body["effective_wholesale_price"] == "350.00"
    assert body["effective_pieces_per_pack"] == 10
    assert body["normal_price_from_group"] is True
    assert body["wholesale_price_from_group"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_item_with_its_own_price_is_marked_as_the_exception(
    database: Database,
) -> None:
    """Hot 8 at 370 inside a grade that is otherwise 350 - and the response says which is which."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        group = await a_group(
            client,
            owner,
            tenant,
            default_normal_price="500.00",
            default_wholesale_price="350.00",
        )

        created = await client.post(
            products_path(tenant["id"]),
            headers=auth(owner),
            json={
                "name": "Screenguard Camon 30",
                "category_id": group["id"],
                "selling_price": "520.00",
                "wholesale_price": "400.00",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()

    assert body["selling_price"] == "520.00"
    assert body["effective_wholesale_price"] == "400.00"
    assert body["normal_price_from_group"] is False
    assert body["wholesale_price_from_group"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_item_nobody_priced_is_refused(database: Database) -> None:
    """No price of its own and no priced group: it cannot be sold, shown or listed, so it is refused."""
    async with running_application() as (client, _application):
        owner, tenant = await owner_with_business(client)
        group = await a_group(client, owner, tenant)

        refused = await client.post(
            products_path(tenant["id"]),
            headers=auth(owner),
            json={"name": "Unpriced item", "category_id": group["id"]},
        )

    assert refused.status_code == 422, refused.text
    # The reason is internal: the customer-facing answer says the value was invalid, and the product's
    # name and the missing price stay in the log where the engineer can find them by correlation id.
    message = refused.json()["error"]["message"]
    assert "Unpriced item" not in message
    assert "no price" not in message.lower()
