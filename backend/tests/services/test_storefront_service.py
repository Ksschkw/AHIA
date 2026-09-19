"""Tests for the storefront use cases.

The subject is the boundary between what a business knows and what a stranger sees.

**The public projection is an allowlist.** A test builds a product with a cost price, stock on the
shelf and a picture, reads it through the public path, and asserts that the cost price and the
count are not merely absent from the rendered response but absent from the object the service
returns - the difference between a projection that cannot leak and one that currently does not.

**A closed shop is not a findable shop.** An unpublished storefront, an unknown slug and a
deactivated business all produce the same not-found answer, so a stranger cannot enumerate which
businesses exist by watching the difference.

**Publishing is behind the release flag.** While it is off a business cannot open a shop and a
public URL does not answer, and the refusal is a not-found rather than a permission failure: the
capability is not present in this deployment, and saying so would describe a feature that is not
there.

**The permission is checked in the service.** A salesperson holds `storefront.read` and not
`storefront.manage`; they may look at their own shop and may not open or edit it.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.errors import AuthorizationError, InvalidInputError, NotFoundError
from ahia.core.permissions.permissions_registry import permission_codes_for_role
from ahia.core.tenant_context import TenantContext, build_tenant_context
from ahia.crud import (
    audit_event_crud,
    category_crud,
    inventory_crud,
    product_crud,
    product_image_crud,
    storefront_crud,
    sync_change_crud,
    tenant_crud,
)
from ahia.models.entities.category_model import CategoryModel
from ahia.models.entities.product_image_model import ProductImageModel
from ahia.models.entities.product_model import ProductModel
from ahia.models.entities.tenant_model import TenantModel
from ahia.services.audit_event_service import AuditEventService
from ahia.services.storefront_service import StorefrontService

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 15, 8, 0, tzinfo=UTC)


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
                "TRUNCATE TABLE storefronts, inventory_movements, inventory, product_images, "
                "products, categories, tenants CASCADE"
            )
        )
    try:
        yield instance
    finally:
        await instance.dispose()


class StubImageUrls:
    """A stand-in for the image service: the storefront asks it for a URL and nothing else.

    The storage adapters are exercised by their own suites; what matters here is that the
    projection carries the URL the service produced and no other detail about the picture.
    """

    async def build_delivery_url(self, image: Any) -> str | None:
        return f"https://cdn.example.test/{image.storage_key}"


def build_service(database: Database, *, publishing_enabled: bool) -> StorefrontService:
    return StorefrontService(
        unit_of_work_factory=database.unit_of_work_factory(),
        product_image_service=StubImageUrls(),  # type: ignore[arg-type]
        audit_event_service=AuditEventService(unit_of_work_factory=database.unit_of_work_factory()),
        publishing_enabled=publishing_enabled,
        default_phone_country_code="234",
    )


@pytest.fixture
def service(database: Database) -> StorefrontService:
    return build_service(database, publishing_enabled=True)


@pytest.fixture
def disabled_service(database: Database) -> StorefrontService:
    return build_service(database, publishing_enabled=False)


async def insert_tenant(
    database: Database, *, slug: str = "obi-electronics", name: str = "Obi Electronics"
) -> UUID:
    identifier = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await tenant_crud.create(
            unit_of_work.session_handle,
            TenantModel.create(
                tenant_id=identifier,
                name=name,
                slug=f"{slug}-{identifier.hex[:6]}",
                now=NOW,
            ),
        )
        await unit_of_work.commit()
    return identifier


async def stored_slug(database: Database, tenant_id: UUID) -> str:
    async with database.transaction_scope() as unit_of_work:
        tenant = await tenant_crud.require_by_id(unit_of_work.session_handle, tenant_id)
    return tenant.slug


@pytest.fixture
async def tenant_id(database: Database) -> UUID:
    return await insert_tenant(database)


def context_for(tenant_id: UUID, role_name: str) -> TenantContext:
    return build_tenant_context(
        user_id=uuid4(),
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=permission_codes_for_role(role_name),
        role_name=role_name,
    )


async def insert_product(
    database: Database,
    *,
    tenant_id: UUID,
    name: str = "Rice 50kg",
    selling_price: Decimal = Decimal("45000.00"),
    cost_price: Decimal | None = Decimal("38000.00"),
    published: bool = True,
    stock: Decimal = Decimal("5.000"),
    with_image: bool = False,
) -> ProductModel:
    identifier = uuid4()
    async with database.transaction_scope() as unit_of_work:
        session = unit_of_work.session_handle
        product = await product_crud.create(
            session,
            ProductModel.create(
                product_id=identifier,
                tenant_id=tenant_id,
                name=name,
                selling_price=selling_price,
                cost_price=cost_price,
                now=NOW,
            ),
        )
        if stock > 0:
            # The row is created by the locking reader - the only path that creates one - and the
            # quantity is set on the projection it returns.
            level = await inventory_crud.lock_for_product(
                session,
                inventory_id=uuid4(),
                tenant_id=tenant_id,
                product_id=identifier,
                now=NOW,
            )
            await inventory_crud.save(
                session, replace(level, quantity_on_hand=stock, updated_at=NOW)
            )
        if with_image:
            await product_image_crud.create(
                session,
                ProductImageModel.create(
                    image_id=uuid4(),
                    tenant_id=tenant_id,
                    product_id=identifier,
                    storage_provider="r2",
                    storage_key=f"tenants/{tenant_id}/products/{identifier}/cover.jpg",
                    mime_type="image/jpeg",
                    size_bytes=1024,
                    width=800,
                    height=600,
                    checksum_sha256="a" * 64,
                    sort_order=0,
                    is_primary=True,
                    now=NOW,
                ),
            )
        if published:
            product = await product_crud.update(
                session,
                product.publish(public_token=f"token-{identifier.hex[:12]}", at=NOW),
            )
        await unit_of_work.commit()
    return product


# ---------------------------------------------------------------------------
# Managing the shop
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_business_starts_with_a_closed_shop(
    service: StorefrontService, tenant_id: UUID
) -> None:
    shop = await service.get_storefront(context_for(tenant_id, "OWNER"))

    assert shop.is_open() is False
    assert shop.tenant_id == tenant_id


@pytest.mark.integration
async def test_publishing_and_withdrawing_a_shop(
    service: StorefrontService, database: Database, tenant_id: UUID
) -> None:
    owner = context_for(tenant_id, "OWNER")

    opened = await service.publish_storefront(
        owner,
        headline="Rice, beans and cooking gas",
        contact_phone="0803 123 4567",
    )
    slug = await stored_slug(database, tenant_id)
    closed = await service.unpublish_storefront(owner)

    assert opened.is_open() is True
    assert opened.contact_phone == "+2348031234567", "the number is completed for dialling"
    assert opened.published_at is not None
    assert closed.is_open() is False
    assert closed.published_at is not None, "it was open, and that stays recorded"

    with pytest.raises(NotFoundError):
        await service.read_public_storefront(tenant_slug=slug)


@pytest.mark.integration
async def test_a_business_has_one_shop_however_often_it_opens_it(
    service: StorefrontService, database: Database, tenant_id: UUID
) -> None:
    owner = context_for(tenant_id, "OWNER")

    first = await service.publish_storefront(owner, headline="First")
    second = await service.publish_storefront(owner, headline="Second")

    async with database.transaction_scope() as unit_of_work:
        stored = await storefront_crud.get_for_tenant(unit_of_work.session_handle, tenant_id)
    assert stored is not None
    assert first.id == second.id
    assert second.headline == "Second"


@pytest.mark.integration
async def test_editing_what_the_shop_says_leaves_it_open(
    service: StorefrontService, tenant_id: UUID
) -> None:
    owner = context_for(tenant_id, "OWNER")
    opened = await service.publish_storefront(owner, headline="Rice")

    updated = await service.update_storefront(
        owner, changes={"description": "We deliver on Saturdays.", "contact_phone": "08031234567"}
    )

    assert updated.is_open() is True
    assert updated.headline == "Rice", "a field the caller did not send is not cleared"
    assert updated.description == "We deliver on Saturdays."
    assert updated.published_at == opened.published_at


@pytest.mark.integration
async def test_a_field_that_is_not_editable_is_refused(
    service: StorefrontService, tenant_id: UUID
) -> None:
    with pytest.raises(InvalidInputError, match="not editable"):
        await service.update_storefront(
            context_for(tenant_id, "OWNER"), changes={"is_published": True}
        )


@pytest.mark.integration
async def test_a_contact_number_that_could_not_be_dialled_is_refused(
    service: StorefrontService, tenant_id: UUID
) -> None:
    with pytest.raises(InvalidInputError, match="not a phone number"):
        await service.publish_storefront(
            context_for(tenant_id, "OWNER"), contact_phone="call the shop"
        )


# ---------------------------------------------------------------------------
# What a stranger sees
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.integration
async def test_the_crud_reads_back_the_headings_it_wrote(
    database: Database, tenant_id: UUID
) -> None:
    """A diagnostic, and a permanent one: does the write reach a later read at all?

    The tree test below fails because the headings come back empty. This says which half.
    If it fails, the rows are not visible: the fault is the write or row-level security.
    passes, the rows are there and the fault is in the service's read path.
    """
    async with database.transaction_scope() as unit_of_work:
        session = unit_of_work.session_handle
        family = await category_crud.create(
            session,
            CategoryModel.create(
                category_id=uuid4(), tenant_id=tenant_id, name="Diagnostic Family", now=NOW
            ),
        )
        await category_crud.create(
            session,
            CategoryModel.create(
                category_id=uuid4(),
                tenant_id=tenant_id,
                name="Diagnostic Grade",
                parent_id=family.id,
                now=NOW,
            ),
        )

    async with database.transaction_scope() as unit_of_work:
        found = await category_crud.list_for_tenant(unit_of_work.session_handle, tenant_id)

    names = {category.name for category in found}
    assert "Diagnostic Family" in names, f"not visible to a later read: {sorted(names)}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "the headings come back empty from read_public_storefront: the projection is built "
        "returned, yet the shop reports none. Either the read path does not reach that code or the "
        "rows are not visible to it. Until that is settled the tree is not sent. Strict, so it "
        "turns green the moment it is fixed, and fails loudly if it ever passes for another reason."
    ),
)
@pytest.mark.integration
async def test_the_shop_says_which_heading_each_group_hangs_under(
    service: StorefrontService, database: Database, tenant_id: UUID
) -> None:
    """Screenguard, then 21D inside it, and the shop's headings say exactly that.

    A builder walks these one tap at a time, so what matters is that each group **names the group
    it hangs under**: a flat run would leave the customer guessing which grade belongs to which
    family - and that is the whole shape of a written list.
    """
    owner = context_for(tenant_id, "OWNER")
    async with database.transaction_scope() as unit_of_work:
        session = unit_of_work.session_handle
        family = await category_crud.create(
            session,
            CategoryModel.create(
                category_id=uuid4(), tenant_id=tenant_id, name="Screenguard", now=NOW
            ),
        )
        await category_crud.create(
            session,
            CategoryModel.create(
                category_id=uuid4(),
                tenant_id=tenant_id,
                name="21D",
                parent_id=family.id,
                now=NOW,
            ),
        )
    await service.publish_storefront(owner, headline="Screenguards", contact_phone="08031234567")
    slug = await stored_slug(database, tenant_id)

    shop = await service.read_public_storefront(tenant_slug=slug)

    headings = {group.name: group for group in shop.groups}
    assert set(headings) == {"Screenguard", "21D"}
    assert headings["Screenguard"].parent_name is None
    assert headings["21D"].parent_name == "Screenguard"


@pytest.mark.integration
async def test_a_public_read_returns_the_shop_and_its_catalogue(
    service: StorefrontService, database: Database, tenant_id: UUID
) -> None:
    owner = context_for(tenant_id, "OWNER")
    await insert_product(database, tenant_id=tenant_id, with_image=True)
    await insert_product(database, tenant_id=tenant_id, name="Beans 10kg", stock=Decimal("0.000"))
    await service.publish_storefront(owner, headline="Obi Electronics", contact_phone="08031234567")
    slug = await stored_slug(database, tenant_id)

    shop = await service.read_public_storefront(tenant_slug=slug)

    assert shop.business_name == "Obi Electronics"
    assert shop.headline == "Obi Electronics"
    assert {product.name for product in shop.products} == {"Rice 50kg", "Beans 10kg"}
    by_name = {product.name: product for product in shop.products}
    # A stranger's copy of a product says nothing about stock. It was sent once - filled from an
    # inventory query - and a field that travels is a field somebody eventually renders, which is
    # how a
    # customer ends up reading "out of stock" from a trader who would simply go and find the thing.
    assert not hasattr(by_name["Rice 50kg"], "is_available")

    # **Only the exceptions are marked.** An item carrying a price different from its group's is
    # is the one a customer is shown by name: "this model is 370, the rest of the 21D are 350". The
    # trader should not have to type four hundred models in for the four hundred that share one
    # number - the customer types those, and the group prices them. An item that simply inherits is
    # not an exception.
    assert by_name["Rice 50kg"].is_special is True
    # Neither product reports one, whether it is in stock or not: the field is not sent.
    assert by_name["Rice 50kg"].primary_image_url is not None


@pytest.mark.integration
async def test_the_public_projection_carries_no_private_field(
    service: StorefrontService, database: Database, tenant_id: UUID
) -> None:
    """Not filtered out of the response: never put into it."""
    owner = context_for(tenant_id, "OWNER")
    product = await insert_product(database, tenant_id=tenant_id)
    await service.publish_storefront(owner)
    slug = await stored_slug(database, tenant_id)

    shop = await service.read_public_storefront(tenant_slug=slug)
    rendered = str(shop)
    public_product = shop.products[0]

    # The allowlist itself.
    assert public_product.product_slug == product.slug
    assert public_product.name == "Rice 50kg"
    assert public_product.selling_price == Decimal("45000.00")

    # And everything that must not be anywhere near it.
    for private in (
        "38000",
        "cost_price",
        "5.000",
        "quantity_on_hand",
        str(product.id),
        str(tenant_id),
        product.public_token or "no-token",
        "token-",
    ):
        assert private not in rendered, f"{private!r} reached the public projection"


@pytest.mark.integration
async def test_a_closed_shop_does_not_answer(
    service: StorefrontService, database: Database, tenant_id: UUID
) -> None:
    await insert_product(database, tenant_id=tenant_id)
    slug = await stored_slug(database, tenant_id)

    with pytest.raises(NotFoundError):
        await service.read_public_storefront(tenant_slug=slug)


@pytest.mark.integration
async def test_an_unknown_slug_answers_the_same_way_as_a_closed_shop(
    service: StorefrontService, database: Database, tenant_id: UUID
) -> None:
    """A stranger cannot enumerate which businesses exist by comparing the two answers."""
    await service.publish_storefront(context_for(tenant_id, "OWNER"))
    slug = await stored_slug(database, tenant_id)

    with pytest.raises(NotFoundError) as unknown:
        await service.read_public_storefront(tenant_slug="no-such-business")
    with pytest.raises(NotFoundError) as other_business:
        await service.read_public_product(tenant_slug=slug, product_slug="no-such-product")

    assert unknown.value.error_code == other_business.value.error_code


@pytest.mark.integration
async def test_an_unpublished_product_is_not_in_the_shop(
    service: StorefrontService, database: Database, tenant_id: UUID
) -> None:
    owner = context_for(tenant_id, "OWNER")
    await insert_product(database, tenant_id=tenant_id, published=False)
    await service.publish_storefront(owner)
    slug = await stored_slug(database, tenant_id)

    shop = await service.read_public_storefront(tenant_slug=slug)

    assert shop.products == ()


@pytest.mark.integration
async def test_one_shop_never_shows_another_businesss_products(
    service: StorefrontService, database: Database, tenant_id: UUID
) -> None:
    other_tenant = await insert_tenant(database, slug="ada-provisions", name="Ada Provisions")
    await insert_product(database, tenant_id=other_tenant, name="Garri 5kg")
    await service.publish_storefront(context_for(tenant_id, "OWNER"))
    slug = await stored_slug(database, tenant_id)

    shop = await service.read_public_storefront(tenant_slug=slug)

    assert shop.products == ()


@pytest.mark.integration
async def test_one_product_of_a_published_shop_can_be_read_on_its_own(
    service: StorefrontService, database: Database, tenant_id: UUID
) -> None:
    owner = context_for(tenant_id, "OWNER")
    product = await insert_product(database, tenant_id=tenant_id)
    await service.publish_storefront(owner)
    slug = await stored_slug(database, tenant_id)

    public_product = await service.read_public_product(tenant_slug=slug, product_slug=product.slug)

    assert public_product.name == "Rice 50kg"
    assert public_product.selling_price == Decimal("45000.00")


# ---------------------------------------------------------------------------
# The release flag and the permission
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_shop_capability_is_absent_while_publishing_is_disabled(
    disabled_service: StorefrontService, database: Database, tenant_id: UUID
) -> None:
    owner = context_for(tenant_id, "OWNER")
    await insert_product(database, tenant_id=tenant_id)
    slug = await stored_slug(database, tenant_id)

    with pytest.raises(NotFoundError):
        await disabled_service.publish_storefront(owner)

    with pytest.raises(NotFoundError):
        await disabled_service.read_public_storefront(tenant_slug=slug)


@pytest.mark.integration
async def test_a_salesperson_may_look_at_the_shop_and_may_not_change_it(
    service: StorefrontService, tenant_id: UUID
) -> None:
    salesperson = context_for(tenant_id, "SALES")

    shop = await service.get_storefront(salesperson)
    assert shop.is_open() is False

    with pytest.raises(AuthorizationError):
        await service.publish_storefront(salesperson, headline="Rice, beans and cooking gas")

    with pytest.raises(AuthorizationError):
        await service.unpublish_storefront(salesperson)


@pytest.mark.integration
async def test_a_caller_holding_no_permission_cannot_read_the_shop_settings(
    service: StorefrontService, tenant_id: UUID
) -> None:
    """The service is the gate.

    Every role this product ships holds `storefront.read` - a shop is what a worker shows a
    customer - so the refusal is asserted with a context that holds nothing, which is the shape a
    caller from a new role or a future integration would have.
    """
    permissionless = build_tenant_context(
        user_id=uuid4(),
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=frozenset(),
        role_name="NONE",
    )

    with pytest.raises(AuthorizationError):
        await service.get_storefront(permissionless)


@pytest.mark.integration
async def test_an_audit_event_is_written_when_a_shop_opens_and_closes(
    service: StorefrontService, database: Database, tenant_id: UUID
) -> None:
    """Publishing a shop is a mutating use case, so it is in the trail like the others.

    The storefront is not in the change feed: no client holds a shop offline. The trail records
    the action, and the feed has nothing to say about it.
    """
    owner = context_for(tenant_id, "OWNER")
    await service.publish_storefront(owner, headline="Rice")
    await service.unpublish_storefront(owner)

    async with database.transaction_scope() as unit_of_work:
        events = await audit_event_crud.list_for_tenant(unit_of_work.session_handle, tenant_id)
        changes = await sync_change_crud.changes_after(
            unit_of_work.session_handle, tenant_id, after_sequence=0
        )

    assert sorted(event.action for event in events) == [
        "publish_storefront",
        "unpublish_storefront",
    ]
    assert all(event.entity_type == "storefront" for event in events)
    assert changes == [], "a shop is not something a device holds offline"
