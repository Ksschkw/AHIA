"""End-to-end tests for the product image endpoints.

Real application, real PostgreSQL, real Pillow decoding. What is tested here is the part
that only exists over HTTP: the raw-body upload, the content type a client declares, the
status codes, and the removal response that has to tell the truth about whether the bytes
actually went.

The storage adapter is the real R2 adapter with a stubbed client, so the object key the
service builds is checked against a real adapter's prefix rule rather than against a
double's idea of it.
"""

from __future__ import annotations

import io
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
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
MEBIBYTE = 1024 * 1024


class StubObjectStore:
    """A stand-in for the vendor SDK the R2 adapter drives.

    Only the three methods the adapter calls. It refuses nothing, so a test that sees a
    failure is seeing a failure the application produced rather than one this stub did.
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted_keys: list[str] = []
        self.fail_deletes = False

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.objects[str(kwargs["Key"])] = kwargs["Body"]
        return {}

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail_deletes:
            raise RuntimeError("the provider refused the delete")
        key = str(kwargs["Key"])
        self.objects.pop(key, None)
        self.deleted_keys.append(key)
        return {}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        key = str(kwargs["Key"])
        if key not in self.objects:
            raise RuntimeError("no such key")
        return {"ContentLength": len(self.objects[key])}

    # The keyword names are boto3's (`Params`, `ExpiresIn`) and are taken as keyword
    # arguments rather than named parameters, so this stub does not carry the vendor's
    # naming conventions into our code.
    def generate_presigned_url(self, client_method: str, **kwargs: Any) -> str:
        assert "Params" in kwargs and "ExpiresIn" in kwargs
        return f"https://objects.example.test/{client_method}?key={kwargs['Params'].get('Key')}"

    def close(self) -> None:
        return None


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
        # Settings ignores a key it does not know, so a misspelled override is silently
        # dropped rather than rejected. These are the real field names, and a limit test
        # that used invented ones would pass by never applying a limit at all.
        "max_product_images_per_product": 3,
        "max_product_image_size_mb": 5,
        "max_upload_size_mb": 6,
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
            text("TRUNCATE TABLE product_images, products, tenant_storage_usage, tenants CASCADE")
        )
    try:
        yield instance
    finally:
        await instance.dispose()


@asynccontextmanager
async def running_application(
    settings: Settings | None = None,
    *,
    object_store: StubObjectStore | None = None,
) -> AsyncIterator[Any]:
    """Run the real application with the storage adapter's vendor client stubbed.

    The adapter itself is real, so a request that reaches storage exercises the real key
    validation and the real resilience policy. Only the network call is replaced.
    """
    application = create_application(settings or build_settings())
    async with application.router.lifespan_context(application):
        store = object_store or StubObjectStore()
        container = application.state.container
        container.storage._client = store  # type: ignore[attr-defined]
        transport = ASGITransport(app=application, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="https://testserver") as client:
            yield client, application, store


def make_png(width: int = 300, height: int = 200) -> bytes:
    image = Image.new("RGB", (width, height), (30, 120, 200))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


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


async def owner_with_product(client: AsyncClient) -> tuple[dict[str, Any], dict[str, Any]]:
    owner = await register(client)
    tenant = await client.post(
        "/api/v1/tenants", headers=auth(owner), json={"name": "Obi Electronics"}
    )
    assert tenant.status_code == 201, tenant.text
    product = await client.post(
        f"/api/v1/tenants/{tenant.json()['id']}/products",
        headers=auth(owner),
        json={"name": "Coca Cola 50cl", "selling_price": "250.00"},
    )
    assert product.status_code == 201, product.text
    return owner, {"tenant": tenant.json(), "product": product.json()}


def images_path(tenant_id: str, product_id: str) -> str:
    return f"/api/v1/tenants/{tenant_id}/products/{product_id}/images"


async def upload(
    client: AsyncClient,
    owner: dict[str, Any],
    context: dict[str, Any],
    *,
    content: bytes | None = None,
    content_type: str = "image/png",
    is_primary: bool = False,
) -> Any:
    return await client.post(
        images_path(context["tenant"]["id"], context["product"]["id"]),
        headers={**auth(owner), "Content-Type": content_type},
        params={"is_primary": str(is_primary).lower()},
        content=content if content is not None else make_png(),
    )


# ---------------------------------------------------------------------------
# Uploading
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_uploading_an_image_stores_it_and_returns_neutral_metadata(
    database: Database,
) -> None:
    store = StubObjectStore()
    async with running_application(object_store=store) as (client, _application, _store):
        owner, context = await owner_with_product(client)
        response = await upload(client, owner, context)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["mime_type"] == "image/webp", "the configured target format is stored"
    assert body["size_bytes"] > 0
    assert (body["width"], body["height"]) == (300, 200)
    assert body["is_primary"] is False
    assert len(body["checksum_sha256"]) == 64

    key = body["storage_key"]
    assert key.startswith(f"tenants/{context['tenant']['id']}/products/")
    assert key.endswith(".webp")
    assert store.objects[key], "the bytes reached the object store"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_response_never_names_the_provider_as_a_column_would(
    database: Database,
) -> None:
    """The provider is data, not a field name: a client reads it as a value."""
    async with running_application() as (client, _application, _store):
        owner, context = await owner_with_product(client)
        response = await upload(client, owner, context)

    body = response.json()
    assert body["storage_provider"] == "r2"
    assert set(body) == {
        "id",
        "tenant_id",
        "product_id",
        "storage_provider",
        "storage_key",
        "mime_type",
        "size_bytes",
        "width",
        "height",
        "checksum_sha256",
        "sort_order",
        "is_primary",
        "removed_at",
        "needs_reconciliation",
        "created_at",
        "delivery_url",
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_upload_that_is_not_an_image_is_refused(database: Database) -> None:
    store = StubObjectStore()
    async with running_application(object_store=store) as (client, _application, _store):
        owner, context = await owner_with_product(client)
        response = await upload(
            client, owner, context, content=b"definitely not a picture", content_type="image/png"
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_MEDIA"
    assert store.objects == {}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_declared_type_that_disagrees_with_the_bytes_is_refused(
    database: Database,
) -> None:
    async with running_application() as (client, _application, _store):
        owner, context = await owner_with_product(client)
        response = await upload(client, owner, context, content_type="image/jpeg")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_MEDIA"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_empty_body_is_refused(database: Database) -> None:
    async with running_application() as (client, _application, _store):
        owner, context = await owner_with_product(client)
        response = await upload(client, owner, context, content=b"")

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_upload_larger_than_the_configured_ceiling_is_refused(
    database: Database,
) -> None:
    settings = build_settings(max_upload_size_mb=1, max_product_image_size_mb=1)
    async with running_application(settings) as (client, _application, _store):
        owner, context = await owner_with_product(client)
        response = await upload(client, owner, context, content=b"x" * (2 * MEBIBYTE))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_MEDIA"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_per_product_image_limit_is_reported_with_the_limit_it_hit(
    database: Database,
) -> None:
    settings = build_settings(max_product_images_per_product=2)
    async with running_application(settings) as (client, _application, _store):
        owner, context = await owner_with_product(client)
        for _ in range(2):
            created = await upload(client, owner, context)
            assert created.status_code == 201, created.text
        refused = await upload(client, owner, context)

    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "RESOURCE_LIMIT_EXCEEDED"


# ---------------------------------------------------------------------------
# Reading and arranging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_gallery_is_listed_in_order_with_delivery_urls(
    database: Database,
) -> None:
    async with running_application() as (client, _application, _store):
        owner, context = await owner_with_product(client)
        first = (await upload(client, owner, context, is_primary=True)).json()
        second = (await upload(client, owner, context)).json()

        gallery = await client.get(
            images_path(context["tenant"]["id"], context["product"]["id"]), headers=auth(owner)
        )

    assert gallery.status_code == 200
    body = gallery.json()
    assert [image["id"] for image in body] == [first["id"], second["id"]]
    assert [image["sort_order"] for image in body] == [0, 1]
    assert body[0]["is_primary"] is True
    assert all(image["delivery_url"] for image in body)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_marking_a_cover_demotes_the_previous_one(database: Database) -> None:
    async with running_application() as (client, _application, _store):
        owner, context = await owner_with_product(client)
        first = (await upload(client, owner, context, is_primary=True)).json()
        second = (await upload(client, owner, context)).json()

        promoted = await client.post(
            f"{images_path(context['tenant']['id'], context['product']['id'])}"
            f"/{second['id']}/primary",
            headers=auth(owner),
        )
        gallery = await client.get(
            images_path(context["tenant"]["id"], context["product"]["id"]), headers=auth(owner)
        )

    assert promoted.status_code == 200, promoted.text
    flags = {image["id"]: image["is_primary"] for image in gallery.json()}
    assert flags == {first["id"]: False, second["id"]: True}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_gallery_order_can_be_replaced(database: Database) -> None:
    async with running_application() as (client, _application, _store):
        owner, context = await owner_with_product(client)
        first = (await upload(client, owner, context, is_primary=True)).json()
        second = (await upload(client, owner, context)).json()

        reordered = await client.put(
            f"{images_path(context['tenant']['id'], context['product']['id'])}/order",
            headers=auth(owner),
            json={"image_ids": [second["id"], first["id"]]},
        )

    assert reordered.status_code == 200, reordered.text
    body = reordered.json()
    assert [image["id"] for image in body] == [second["id"], first["id"]]
    assert body[1]["is_primary"] is True, "arranging the gallery does not move the cover"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_order_that_omits_an_image_is_refused(database: Database) -> None:
    async with running_application() as (client, _application, _store):
        owner, context = await owner_with_product(client)
        first = (await upload(client, owner, context)).json()
        await upload(client, owner, context)

        response = await client.put(
            f"{images_path(context['tenant']['id'], context['product']['id'])}/order",
            headers=auth(owner),
            json={"image_ids": [first["id"]]},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_empty_order_is_refused_by_the_contract(database: Database) -> None:
    async with running_application() as (client, _application, _store):
        owner, context = await owner_with_product(client)
        await upload(client, owner, context)
        response = await client.put(
            f"{images_path(context['tenant']['id'], context['product']['id'])}/order",
            headers=auth(owner),
            json={"image_ids": []},
        )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Removal and reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_removing_an_image_reports_that_the_storage_was_released(
    database: Database,
) -> None:
    store = StubObjectStore()
    async with running_application(object_store=store) as (client, _application, _store):
        owner, context = await owner_with_product(client)
        image = (await upload(client, owner, context)).json()

        removal = await client.delete(
            f"{images_path(context['tenant']['id'], context['product']['id'])}/{image['id']}",
            headers=auth(owner),
        )
        gallery = await client.get(
            images_path(context["tenant"]["id"], context["product"]["id"]), headers=auth(owner)
        )

    assert removal.status_code == 200, removal.text
    body = removal.json()
    assert body["storage_released"] is True
    assert body["reconciliation_required"] is False
    assert body["released_bytes"] == image["size_bytes"]
    assert image["storage_key"] in store.deleted_keys
    assert gallery.json() == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_refused_delete_is_reported_rather_than_hidden(database: Database) -> None:
    """The response says the bytes are still stored, so a caller cannot assume otherwise."""
    store = StubObjectStore()
    store.fail_deletes = True
    async with running_application(object_store=store) as (client, _application, _store):
        owner, context = await owner_with_product(client)
        image = (await upload(client, owner, context)).json()

        removal = await client.delete(
            f"{images_path(context['tenant']['id'], context['product']['id'])}/{image['id']}",
            headers=auth(owner),
        )

    assert removal.status_code == 200, removal.text
    body = removal.json()
    assert body["storage_released"] is False
    assert body["reconciliation_required"] is True
    assert body["released_bytes"] == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reconciliation_cleans_up_after_the_provider_recovers(
    database: Database,
) -> None:
    store = StubObjectStore()
    store.fail_deletes = True
    async with running_application(object_store=store) as (client, _application, _store):
        owner, context = await owner_with_product(client)
        image = (await upload(client, owner, context)).json()
        await client.delete(
            f"{images_path(context['tenant']['id'], context['product']['id'])}/{image['id']}",
            headers=auth(owner),
        )

        store.fail_deletes = False
        reconciliation = await client.post(
            f"/api/v1/tenants/{context['tenant']['id']}/product-images/reconcile",
            headers=auth(owner),
        )

    assert reconciliation.status_code == 200, reconciliation.text
    body = reconciliation.json()
    assert body == {"attempted": 1, "released": 1, "still_pending": 0}
    assert image["storage_key"] in store.deleted_keys


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reconciliation_with_nothing_pending_does_nothing(database: Database) -> None:
    async with running_application() as (client, _application, _store):
        owner, context = await owner_with_product(client)
        reconciliation = await client.post(
            f"/api/v1/tenants/{context['tenant']['id']}/product-images/reconcile",
            headers=auth(owner),
        )

    assert reconciliation.status_code == 200
    assert reconciliation.json() == {"attempted": 0, "released": 0, "still_pending": 0}


# ---------------------------------------------------------------------------
# Tenancy and authorization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_image_cannot_be_attached_to_another_businesss_product(
    database: Database,
) -> None:
    async with running_application() as (client, _application, _store):
        _owner, context = await owner_with_product(client)
        outsider = await register(client)
        outsider_tenant = await client.post(
            "/api/v1/tenants", headers=auth(outsider), json={"name": "Somewhere Else"}
        )
        assert outsider_tenant.status_code == 201, outsider_tenant.text

        response = await client.post(
            images_path(outsider_tenant.json()["id"], context["product"]["id"]),
            headers={**auth(outsider), "Content-Type": "image/png"},
            content=make_png(),
        )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_image_cannot_be_read_through_another_business(database: Database) -> None:
    async with running_application() as (client, _application, _store):
        owner, context = await owner_with_product(client)
        await upload(client, owner, context)

        outsider = await register(client)
        outsider_tenant = await client.post(
            "/api/v1/tenants", headers=auth(outsider), json={"name": "Somewhere Else"}
        )
        response = await client.get(
            images_path(outsider_tenant.json()["id"], context["product"]["id"]),
            headers=auth(outsider),
        )

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unauthenticated_upload_is_refused(database: Database) -> None:
    async with running_application() as (client, _application, _store):
        _owner, context = await owner_with_product(client)
        response = await client.post(
            images_path(context["tenant"]["id"], context["product"]["id"]),
            headers={"Content-Type": "image/png"},
            content=make_png(),
        )

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_salesperson_can_read_the_gallery_and_cannot_change_it(
    database: Database,
) -> None:
    async with running_application() as (client, application, _store):
        owner, context = await owner_with_product(client)
        image = (await upload(client, owner, context)).json()

        worker = await register(client)
        membership = TenantMembershipModel.activate_immediately(
            membership_id=uuid4(),
            tenant_id=UUID(context["tenant"]["id"]),
            user_id=UUID(worker["user"]["id"]),
            role_name="SALES",
            now=datetime.now(UTC),
        )
        async with application.state.container.database.transaction_scope() as unit_of_work:
            await tenant_membership_crud.create(unit_of_work.session_handle, membership)
            await unit_of_work.commit()

        readable = await client.get(
            images_path(context["tenant"]["id"], context["product"]["id"]), headers=auth(worker)
        )
        refused = await client.post(
            f"{images_path(context['tenant']['id'], context['product']['id'])}"
            f"/{image['id']}/primary",
            headers=auth(worker),
        )

    assert readable.status_code == 200
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "FORBIDDEN"
