"""End-to-end tests for the public shop and its management routes.

Real application, real HTTP, real PostgreSQL. What is tested here is the part that only exists over
the wire, and the parts that only matter because the public routes are public.

**The public shop answers without a token.** No authorization header, no cookie: a customer with a
link is the whole use case. The test asserts the 200 and the fields, and separately that the
response contains none of the private ones.

**A closed shop is a 404 with nothing in it.** The body is the standard error envelope, so a
stranger learns that the address does not answer and nothing about whether a business is behind it.

**The public path consumes its own rate limit.** The shop is classified into the public bucket by
the middleware, which is a tighter limit than the global one; the test drives the limiter directly
rather than through the application, because the application's limit is configuration.

**Management requires a token and a permission.** An owner can open and close a shop; a caller with
no token cannot even read their own.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.main import create_application
from ahia.middleware.rate_limit_middleware import (
    RateLimitBucket,
    RateLimitMiddleware,
)
from ahia.services.iam_seed_service import IamSeedService

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
PASSWORD = "a-good-enough-password"


def build_settings(*, publishing: bool, **overrides: Any) -> Settings:
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
        "feature_storetfront_public_publishing": publishing,
    }
    baseline.update(overrides)
    return Settings(**baseline)


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    instance = Database(build_settings(publishing=True))
    async with instance.engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(sync_connection, checkfirst=True)
        )
        await connection.execute(
            text(
                "TRUNCATE TABLE storefronts, sync_changes, audit_events, "
                "inventory_movements, inventory, product_images, products, categories, "
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
async def running_application(*, publishing: bool) -> AsyncIterator[tuple[AsyncClient, Any]]:
    application = create_application(build_settings(publishing=publishing))
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


async def owner_with_business(
    client: AsyncClient, *, name: str = "Obi Electronics"
) -> tuple[dict[str, Any], dict[str, Any]]:
    owner = await register(client)
    created = await client.post("/api/v1/tenants", headers=auth(owner), json={"name": name})
    assert created.status_code == 201, created.text
    return owner, created.json()


def storefront_path(tenant_id: str, *parts: str) -> str:
    suffix = "".join(f"/{part}" for part in parts)
    return f"/api/v1/tenants/{tenant_id}/storefront{suffix}"


async def create_published_product(
    client: AsyncClient, owner: dict[str, Any], tenant: dict[str, Any], *, name: str = "Rice 50kg"
) -> dict[str, Any]:
    created = await client.post(
        f"/api/v1/tenants/{tenant['id']}/products",
        headers=auth(owner),
        json={"name": f"{name} {uuid4().hex[:6]}", "selling_price": "45000.00"},
    )
    assert created.status_code == 201, created.text
    product = created.json()
    published = await client.post(
        f"/api/v1/tenants/{tenant['id']}/products/{product['id']}/publish",
        headers=auth(owner),
    )
    assert published.status_code == 200, published.text
    return published.json()


# ---------------------------------------------------------------------------
# The public shop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_shop_answers_without_a_token(database: Database) -> None:
    async with running_application(publishing=True) as (client, _application):
        owner, tenant = await owner_with_business(client)
        product = await create_published_product(client, owner, tenant)
        await client.post(
            storefront_path(tenant["id"], "publish"),
            headers=auth(owner),
            json={"headline": "Rice, beans and cooking gas", "contact_phone": "08031234567"},
        )

        response = await client.get(f"/shop/{tenant['slug']}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["business_name"] == "Obi Electronics"
    assert body["headline"] == "Rice, beans and cooking gas"
    assert body["contact_phone"] == "+2348031234567"
    assert [entry["name"] for entry in body["products"]] == [product["name"]]
    assert body["products"][0]["selling_price"] == "45000.00"
    assert body["products"][0]["product_slug"] == product["slug"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_one_product_of_a_shop_can_be_shared(database: Database) -> None:
    async with running_application(publishing=True) as (client, _application):
        owner, tenant = await owner_with_business(client)
        product = await create_published_product(client, owner, tenant)
        await client.post(storefront_path(tenant["id"], "publish"), headers=auth(owner), json={})

        response = await client.get(f"/shop/{tenant['slug']}/product/{product['slug']}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["business_name"] == "Obi Electronics"
    assert body["product"]["name"] == product["name"]
    assert body["product"]["selling_price"] == "45000.00"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_public_page_carries_no_private_field(database: Database) -> None:
    """The public surface is the one place the allowlist has to hold, so it is asserted here."""
    async with running_application(publishing=True) as (client, _application):
        owner, tenant = await owner_with_business(client)
        product = await create_published_product(client, owner, tenant)
        await client.post(storefront_path(tenant["id"], "publish"), headers=auth(owner), json={})

        response = await client.get(f"/shop/{tenant['slug']}")

    rendered = response.text
    assert product["public_token"] not in rendered
    for private in ("cost_price", "quantity_on_hand", "tenant_id", product["id"]):
        assert private not in rendered, f"{private!r} reached the public page"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_shop_that_was_never_opened_does_not_answer(database: Database) -> None:
    async with running_application(publishing=True) as (client, _application):
        _owner, tenant = await owner_with_business(client)

        response = await client.get(f"/shop/{tenant['slug']}")

    assert response.status_code == 404
    assert set(response.json()) == {"error"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_withdrawn_shop_stops_answering(database: Database) -> None:
    async with running_application(publishing=True) as (client, _application):
        owner, tenant = await owner_with_business(client)
        await client.post(storefront_path(tenant["id"], "publish"), headers=auth(owner), json={})
        opened = await client.get(f"/shop/{tenant['slug']}")

        await client.post(storefront_path(tenant["id"], "unpublish"), headers=auth(owner))
        withdrawn = await client.get(f"/shop/{tenant['slug']}")
        listed = await client.get(storefront_path(tenant["id"]), headers=auth(owner))

    assert opened.status_code == 200
    assert withdrawn.status_code == 404
    assert listed.json()["is_published"] is False
    assert listed.json()["published_at"] is not None, "it was open, and that stays recorded"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unknown_address_and_a_closed_shop_are_indistinguishable(
    database: Database,
) -> None:
    async with running_application(publishing=True) as (client, _application):
        _owner, tenant = await owner_with_business(client)

        unknown = await client.get("/shop/no-such-business")
        closed = await client.get(f"/shop/{tenant['slug']}")

    assert unknown.status_code == closed.status_code == 404
    assert unknown.json()["error"]["code"] == closed.json()["error"]["code"]
    assert unknown.json()["error"]["message"] == closed.json()["error"]["message"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_shop_is_absent_while_publishing_is_disabled(database: Database) -> None:
    """The feature is off by default: a deployment that has not released it serves nothing."""
    async with running_application(publishing=True) as (client, _application):
        owner, tenant = await owner_with_business(client)
        await client.post(storefront_path(tenant["id"], "publish"), headers=auth(owner), json={})

    async with running_application(publishing=False) as (disabled_client, _application):
        response = await disabled_client.get(f"/shop/{tenant['slug']}")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Managing the shop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_business_starts_with_a_closed_shop_it_can_read(
    database: Database,
) -> None:
    async with running_application(publishing=True) as (client, _application):
        owner, tenant = await owner_with_business(client)

        response = await client.get(storefront_path(tenant["id"]), headers=auth(owner))

    assert response.status_code == 200, response.text
    assert response.json()["is_published"] is False
    assert response.json()["tenant_id"] == tenant["id"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_editing_what_the_shop_says_leaves_it_open(database: Database) -> None:
    async with running_application(publishing=True) as (client, _application):
        owner, tenant = await owner_with_business(client)
        await client.post(
            storefront_path(tenant["id"], "publish"),
            headers=auth(owner),
            json={"headline": "Rice"},
        )

        edited = await client.patch(
            storefront_path(tenant["id"]),
            headers=auth(owner),
            json={"description": "We deliver on Saturdays."},
        )

    assert edited.status_code == 200, edited.text
    assert edited.json()["is_published"] is True
    assert edited.json()["headline"] == "Rice"
    assert edited.json()["description"] == "We deliver on Saturdays."


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_field_that_is_not_editable_is_refused(database: Database) -> None:
    async with running_application(publishing=True) as (client, _application):
        owner, tenant = await owner_with_business(client)

        response = await client.patch(
            storefront_path(tenant["id"]),
            headers=auth(owner),
            json={"is_published": True, "tenant_id": str(uuid4())},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_managing_a_shop_requires_a_token(database: Database) -> None:
    async with running_application(publishing=True) as (client, _application):
        _owner, tenant = await owner_with_business(client)

        read = await client.get(storefront_path(tenant["id"]))
        published = await client.post(storefront_path(tenant["id"], "publish"), json={})

    assert read.status_code == 401
    assert published.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_stranger_cannot_open_somebody_elses_shop(database: Database) -> None:
    async with running_application(publishing=True) as (client, _application):
        _owner, tenant = await owner_with_business(client)
        stranger = await register(client)

        response = await client.post(
            storefront_path(tenant["id"], "publish"), headers=auth(stranger), json={}
        )

    assert response.status_code in {403, 404}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_public_page_does_not_show_another_businesss_products(
    database: Database,
) -> None:
    async with running_application(publishing=True) as (client, _application):
        owner, tenant = await owner_with_business(client)
        other_owner, other_tenant = await owner_with_business(client, name="Ada Provisions")
        await create_published_product(client, other_owner, other_tenant, name="Garri 5kg")
        await client.post(storefront_path(tenant["id"], "publish"), headers=auth(owner), json={})

        response = await client.get(f"/shop/{tenant['slug']}")

    assert response.status_code == 200
    assert response.json()["products"] == []


@pytest.mark.unit
def test_the_public_shop_is_rate_limited_into_its_own_bucket() -> None:
    """A rate limit is a security control, and the public surface is where it matters most.

    Asserted against the classifier rather than through the application: the limit itself is
    configuration, and the middleware's own suite drives the counters.
    """
    assert (
        RateLimitMiddleware._bucket_for(path="/shop/obi-electronics", method="GET")
        is RateLimitBucket.PUBLIC_READ
    )


def _settings_defaults_to_off() -> bool:
    return Settings.model_fields["feature_storetfront_public_publishing"].default is False


@pytest.mark.unit
def test_public_publishing_is_off_by_default() -> None:
    """New behaviour ships dark: the routes exist and the capability is refused until asked for."""
    assert _settings_defaults_to_off() is True
