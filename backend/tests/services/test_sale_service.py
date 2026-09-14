"""Tests for the sale use cases.

The transactional property is the subject, and it is tested by breaking it on purpose: a
failure injected after the stock has moved must leave no sale, no line, no payment, no
movement, no ledger entry and no consumed receipt number. A sale that survived while its
stock movement rolled back is the failure this milestone exists to prevent.

The rest is what a sale means: the money adds up, the stock leaves, the ledger records the
revenue, a replayed operation produces one sale, and cancelling reverses both the goods and
the money without deleting the record of either.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.errors import (
    AuthorizationError,
    DomainError,
    InvalidInputError,
    NotFoundError,
)
from ahia.core.permissions.permissions_registry import permission_codes_for_role
from ahia.core.tenant_context import TenantContext, build_tenant_context
from ahia.crud import (
    audit_event_crud,
    customer_crud,
    inventory_crud,
    inventory_movement_crud,
    ledger_entry_crud,
    payment_crud,
    product_crud,
    receipt_counter_crud,
    sale_crud,
    tenant_crud,
    user_crud,
)
from ahia.models.entities.customer_model import CustomerModel
from ahia.models.entities.inventory_model import InventoryModel
from ahia.models.entities.ledger_entry_model import LedgerDirection, LedgerEntryType
from ahia.models.entities.negative_stock_policy import NegativeStockPolicy
from ahia.models.entities.payment_model import PaymentMethod
from ahia.models.entities.product_model import ProductModel
from ahia.models.entities.sale_model import SaleStatus
from ahia.models.entities.tenant_model import TenantModel
from ahia.models.entities.user_model import UserModel
from ahia.services.audit_event_service import AuditEventService
from ahia.services.inventory_service import InventoryService
from ahia.services.sale_service import PaymentRequest, SaleLineRequest, SalesService

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)


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
                "tenants, users CASCADE"
            )
        )
    try:
        yield instance
    finally:
        await instance.dispose()


@pytest.fixture
def inventory_service(database: Database) -> InventoryService:
    return InventoryService(
        unit_of_work_factory=database.unit_of_work_factory(),
        audit_event_service=AuditEventService(unit_of_work_factory=database.unit_of_work_factory()),
    )


@pytest.fixture
def service(database: Database, inventory_service: InventoryService) -> SalesService:
    return SalesService(
        unit_of_work_factory=database.unit_of_work_factory(),
        inventory_service=inventory_service,
        audit_event_service=AuditEventService(unit_of_work_factory=database.unit_of_work_factory()),
    )


async def insert_tenant(
    database: Database,
    *,
    slug: str | None = None,
    policy: NegativeStockPolicy | None = None,
) -> UUID:
    """Create a business, with a unique slug unless one is named.

    A slug is globally unique, so a test that creates a second business has to give it a
    different one. The receipt prefix is taken from the slug, which is why the primary
    business in these tests is named `OBI` and its receipts read `OBI-000001`.
    """
    identifier = uuid4()
    resolved_slug = slug or f"T{identifier.hex[:8].upper()}"
    async with database.transaction_scope() as unit_of_work:
        await tenant_crud.create(
            unit_of_work.session_handle,
            TenantModel.create(
                tenant_id=identifier,
                name="Obi Electronics",
                slug=resolved_slug,
                now=NOW,
                **({"negative_stock_policy": policy} if policy is not None else {}),
            ),
        )
        await unit_of_work.commit()
    return identifier


async def insert_user(database: Database) -> UUID:
    identifier = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await user_crud.create(
            unit_of_work.session_handle,
            UserModel.create(
                user_id=identifier,
                first_name="Emeka",
                email=f"emeka.{identifier.hex[:8]}@example.com",
                now=NOW,
            ),
        )
        await unit_of_work.commit()
    return identifier


async def insert_product(
    database: Database,
    tenant_id: UUID,
    *,
    name: str = "Rice 50kg",
    price: Decimal = Decimal("45000.00"),
    active: bool = True,
) -> UUID:
    identifier = uuid4()
    product = ProductModel.create(
        product_id=identifier,
        tenant_id=tenant_id,
        name=name,
        selling_price=price,
        now=NOW,
    )
    if not active:
        product = product.deactivate(at=NOW)
    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(unit_of_work.session_handle, product)
        await unit_of_work.commit()
    return identifier


async def insert_customer(database: Database, tenant_id: UUID) -> UUID:
    identifier = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await customer_crud.create(
            unit_of_work.session_handle,
            CustomerModel.create(
                customer_id=identifier, tenant_id=tenant_id, name="Ada Obi", now=NOW
            ),
        )
        await unit_of_work.commit()
    return identifier


@pytest.fixture
async def tenant_id(database: Database) -> UUID:
    return await insert_tenant(database, slug="OBI")


@pytest.fixture
async def seller_id(database: Database) -> UUID:
    return await insert_user(database)


@pytest.fixture
async def product_id(database: Database, tenant_id: UUID) -> UUID:
    return await insert_product(database, tenant_id)


def owner_context(tenant_id: UUID, *, seller_id: UUID) -> TenantContext:
    return build_tenant_context(
        user_id=seller_id,
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=permission_codes_for_role("OWNER"),
        role_name="OWNER",
    )


def context_for(tenant_id: UUID, role_name: str, *, seller_id: UUID) -> TenantContext:
    return build_tenant_context(
        user_id=seller_id,
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=permission_codes_for_role(role_name),
        role_name=role_name,
    )


async def stock_up(
    database: Database,
    inventory_service: InventoryService,
    *,
    tenant_context: TenantContext,
    product_id: UUID,
    quantity: Decimal,
) -> None:
    """Put stock on the shelf through the ordinary receipt path."""
    await inventory_service.receive_stock(
        tenant_context, product_id=product_id, quantity=quantity, note="opening stock"
    )


async def stock_level(database: Database, tenant_id: UUID, product_id: UUID) -> Decimal:
    async with database.transaction_scope() as unit_of_work:
        inventory = await inventory_crud.get_for_product(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=product_id
        )
    return (
        InventoryModel.empty(
            inventory_id=uuid4(), tenant_id=tenant_id, product_id=product_id, now=NOW
        ).quantity_on_hand
        if inventory is None
        else inventory.quantity_on_hand
    )


async def count_everything(database: Database, tenant_id: UUID) -> dict[str, int]:
    """Return how many rows of each kind this business has."""
    async with database.transaction_scope() as unit_of_work:
        session = unit_of_work.session_handle
        return {
            "sales": await sale_crud.count_for_tenant(session, tenant_id),
            "ledger": await ledger_entry_crud.count_for_tenant(session, tenant_id),
            "receipts": await receipt_counter_crud.current_number(session, tenant_id),
            "movements": len(
                await inventory_movement_crud.list_for_tenant(session, tenant_id, limit=500)
            ),
        }


# ---------------------------------------------------------------------------
# Completing a sale
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_sale_records_everything_it_touches(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    owner = owner_context(tenant_id, seller_id=seller_id)
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=product_id,
        quantity=Decimal("10.000"),
    )

    result = await service.complete_sale(
        owner,
        lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("2.000"))],
        payments=[PaymentRequest(amount=Decimal("90000.00"), method=PaymentMethod.CASH)],
    )

    sale = result.sale
    assert sale.receipt_number == "OBI-000001"
    assert sale.subtotal == Decimal("90000.00")
    assert sale.total_amount == Decimal("90000.00")
    assert sale.payment_status.value == "PAID"
    assert sale.status is SaleStatus.COMPLETED
    assert len(result.items) == 1
    assert result.items[0].product_name_snapshot == "Rice 50kg"
    assert result.items[0].unit_price == Decimal("45000.00")

    assert await stock_level(database, tenant_id, product_id) == Decimal("8.000")

    async with database.transaction_scope() as unit_of_work:
        entries = await ledger_entry_crud.list_for_reference(
            unit_of_work.session_handle,
            tenant_id=tenant_id,
            reference_type="sale",
            reference_id=sale.id,
        )
        movements = await inventory_movement_crud.list_for_product(
            unit_of_work.session_handle,
            tenant_id=tenant_id,
            product_id=product_id,
        )

    assert [entry.entry_type for entry in entries] == [LedgerEntryType.SALE_REVENUE]
    assert entries[0].direction is LedgerDirection.CREDIT
    assert [movement.quantity_delta for movement in movements] == [
        Decimal("-2.000"),
        Decimal("10.000"),
    ]
    assert movements[0].reference_type == "sale"
    assert movements[0].reference_id == sale.id


@pytest.mark.integration
async def test_a_sale_with_a_discount_records_revenue_and_the_discount(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    owner = owner_context(tenant_id, seller_id=seller_id)
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=product_id,
        quantity=Decimal("5.000"),
    )

    result = await service.complete_sale(
        owner,
        lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("2.000"))],
        payments=[PaymentRequest(amount=Decimal("85000.00"))],
        discount_amount=Decimal("5000.00"),
    )

    async with database.transaction_scope() as unit_of_work:
        entries = await ledger_entry_crud.list_for_reference(
            unit_of_work.session_handle,
            tenant_id=tenant_id,
            reference_type="sale",
            reference_id=result.sale.id,
        )
        net = await ledger_entry_crud.total_signed_amount(unit_of_work.session_handle, tenant_id)

    assert result.sale.total_amount == Decimal("85000.00")
    assert {entry.entry_type for entry in entries} == {
        LedgerEntryType.SALE_REVENUE,
        LedgerEntryType.SALE_DISCOUNT,
    }, "a set: both entries were written in the same instant, so neither precedes the other"
    assert net == Decimal("85000.00"), "revenue less the discount is what the business kept"


@pytest.mark.integration
async def test_a_partly_paid_sale_says_so(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    owner = owner_context(tenant_id, seller_id=seller_id)
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=product_id,
        quantity=Decimal("5.000"),
    )

    result = await service.complete_sale(
        owner,
        lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("2.000"))],
        payments=[PaymentRequest(amount=Decimal("40000.00"))],
    )

    assert result.sale.payment_status.value == "PARTIALLY_PAID"
    assert result.sale.is_settled() is False


@pytest.mark.integration
async def test_a_sale_can_be_recorded_with_nothing_paid_yet(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    """A shopkeeper who writes down what a customer took on credit has not been paid."""
    owner = owner_context(tenant_id, seller_id=seller_id)
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=product_id,
        quantity=Decimal("5.000"),
    )

    result = await service.complete_sale(
        owner,
        lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("1.000"))],
        payments=[],
    )

    assert result.sale.payment_status.value == "UNPAID"
    assert await stock_level(database, tenant_id, product_id) == Decimal("4.000")


@pytest.mark.integration
async def test_a_sale_can_name_a_customer_and_a_negotiated_price(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    owner = owner_context(tenant_id, seller_id=seller_id)
    customer_id = await insert_customer(database, tenant_id)
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=product_id,
        quantity=Decimal("3.000"),
    )

    result = await service.complete_sale(
        owner,
        lines=[
            SaleLineRequest(
                product_id=product_id,
                quantity=Decimal("1.000"),
                unit_price=Decimal("40000.00"),
                discount_amount=Decimal("2000.00"),
            )
        ],
        payments=[PaymentRequest(amount=Decimal("38000.00"))],
        customer_id=customer_id,
    )

    assert result.sale.customer_id == customer_id
    assert result.sale.total_amount == Decimal("38000.00")
    assert result.items[0].unit_price == Decimal("40000.00")
    assert result.items[0].line_total == Decimal("38000.00")


@pytest.mark.integration
async def test_a_sale_needs_at_least_one_line(
    service: SalesService, tenant_id: UUID, seller_id: UUID
) -> None:
    with pytest.raises(InvalidInputError, match="at least one line"):
        await service.complete_sale(
            owner_context(tenant_id, seller_id=seller_id), lines=[], payments=[]
        )


@pytest.mark.integration
async def test_a_withdrawn_product_cannot_be_sold(
    database: Database, service: SalesService, tenant_id: UUID, seller_id: UUID
) -> None:
    """Selling something the business has withdrawn is a mistake at the till."""
    withdrawn = await insert_product(database, tenant_id, name="Old rice", active=False)

    with pytest.raises(DomainError, match="not active"):
        await service.complete_sale(
            owner_context(tenant_id, seller_id=seller_id),
            lines=[SaleLineRequest(product_id=withdrawn, quantity=Decimal("1.000"))],
            payments=[],
        )


@pytest.mark.integration
async def test_a_product_from_another_business_cannot_be_sold(
    database: Database, service: SalesService, tenant_id: UUID, seller_id: UUID
) -> None:
    other_tenant = await insert_tenant(database)
    foreign_product = await insert_product(database, other_tenant, name="Theirs")

    with pytest.raises(NotFoundError):
        await service.complete_sale(
            owner_context(tenant_id, seller_id=seller_id),
            lines=[SaleLineRequest(product_id=foreign_product, quantity=Decimal("1.000"))],
            payments=[],
        )


@pytest.mark.integration
async def test_change_given_is_not_a_payment(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    """Recording 1000 against a 900 sale would make every cash report wrong by the change."""
    owner = owner_context(tenant_id, seller_id=seller_id)
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=product_id,
        quantity=Decimal("3.000"),
    )

    with pytest.raises(InvalidInputError, match="exceed the sale total"):
        await service.complete_sale(
            owner,
            lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("1.000"))],
            payments=[PaymentRequest(amount=Decimal("50000.00"))],
        )


@pytest.mark.integration
async def test_selling_more_than_is_in_stock_is_refused_by_the_policy(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    owner = owner_context(tenant_id, seller_id=seller_id)
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=product_id,
        quantity=Decimal("1.000"),
    )

    with pytest.raises(DomainError, match="negative"):
        await service.complete_sale(
            owner,
            lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("2.000"))],
            payments=[PaymentRequest(amount=Decimal("90000.00"))],
        )


@pytest.mark.integration
async def test_a_business_that_allows_an_overdraw_can_sell_ahead_of_stock(
    database: Database,
    service: SalesService,
    tenant_id: UUID,
    seller_id: UUID,
) -> None:
    """The policy is the business's, so the same service sells ahead of stock here."""
    allowing = await insert_tenant(database, policy=NegativeStockPolicy.ALLOW_NEGATIVE_STOCK)
    product = await insert_product(database, allowing, name="Rice 50kg")
    seller = await insert_user(database)
    owner = owner_context(allowing, seller_id=seller)

    result = await service.complete_sale(
        owner,
        lines=[SaleLineRequest(product_id=product, quantity=Decimal("2.000"))],
        payments=[PaymentRequest(amount=Decimal("90000.00"))],
    )

    assert result.sale.total_amount == Decimal("90000.00")
    assert await stock_level(database, allowing, product) == Decimal("-2.000")
    assert tenant_id != allowing and seller_id != seller


# ---------------------------------------------------------------------------
# One transaction, or none of it
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_failure_after_the_stock_moved_leaves_nothing_behind(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    """The property the milestone exists for: no half-created sale, ever.

    The failure is injected after the sale, its lines, its payments and its stock movement
    have all been written inside the transaction, so everything below is rolled back by the
    database rather than by a compensating delete.
    """
    owner = owner_context(tenant_id, seller_id=seller_id)
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=product_id,
        quantity=Decimal("10.000"),
    )
    before = await count_everything(database, tenant_id)

    with (
        patch.object(service, "_write_ledger", side_effect=RuntimeError("the ledger write failed")),
        pytest.raises(RuntimeError, match="ledger write failed"),
    ):
        await service.complete_sale(
            owner,
            lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("2.000"))],
            payments=[PaymentRequest(amount=Decimal("90000.00"))],
        )

    after = await count_everything(database, tenant_id)

    assert after == before, "a failed sale left something behind"
    assert after["receipts"] == before["receipts"], (
        "the receipt counter moved even though nothing was written"
    )
    assert await stock_level(database, tenant_id, product_id) == Decimal("10.000"), (
        "the stock movement survived the rollback"
    )

    async with database.transaction_scope() as unit_of_work:
        assert await sale_crud.count_for_tenant(unit_of_work.session_handle, tenant_id) == 0
        assert (
            await payment_crud.list_for_sale(
                unit_of_work.session_handle, tenant_id=tenant_id, sale_id=uuid4()
            )
            == []
        )


@pytest.mark.integration
async def test_the_receipt_number_a_failed_sale_claimed_is_reused(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    """A number that was never printed is not a gap in the book."""
    owner = owner_context(tenant_id, seller_id=seller_id)
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=product_id,
        quantity=Decimal("10.000"),
    )

    with (
        patch.object(service, "_write_ledger", side_effect=RuntimeError("the ledger write failed")),
        pytest.raises(RuntimeError),
    ):
        await service.complete_sale(
            owner,
            lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("1.000"))],
            payments=[],
        )

    result = await service.complete_sale(
        owner,
        lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("1.000"))],
        payments=[],
    )

    assert result.sale.receipt_number == "OBI-000001"


@pytest.mark.integration
async def test_a_line_that_cannot_be_fulfilled_rolls_back_the_earlier_lines(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    """The third line failing must not leave the first two sold."""
    owner = owner_context(tenant_id, seller_id=seller_id)
    second_product = await insert_product(
        database, tenant_id, name="Beans 50kg", price=Decimal("55000.00")
    )
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=product_id,
        quantity=Decimal("10.000"),
    )
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=second_product,
        quantity=Decimal("1.000"),
    )

    with pytest.raises(DomainError):
        await service.complete_sale(
            owner,
            lines=[
                SaleLineRequest(product_id=product_id, quantity=Decimal("2.000")),
                SaleLineRequest(product_id=second_product, quantity=Decimal("5.000")),
            ],
            payments=[],
        )

    assert await stock_level(database, tenant_id, product_id) == Decimal("10.000")
    assert await stock_level(database, tenant_id, second_product) == Decimal("1.000")
    async with database.transaction_scope() as unit_of_work:
        assert await sale_crud.count_for_tenant(unit_of_work.session_handle, tenant_id) == 0


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_replaying_an_operation_returns_the_original_sale(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    """An offline client that sends the same basket twice must not sell it twice."""
    owner = owner_context(tenant_id, seller_id=seller_id)
    operation_id = uuid4()
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=product_id,
        quantity=Decimal("10.000"),
    )
    before = await count_everything(database, tenant_id)

    first = await service.complete_sale(
        owner,
        lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("2.000"))],
        payments=[PaymentRequest(amount=Decimal("90000.00"))],
        operation_id=operation_id,
    )
    second = await service.complete_sale(
        owner,
        lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("2.000"))],
        payments=[PaymentRequest(amount=Decimal("90000.00"))],
        operation_id=operation_id,
    )

    assert first.was_replayed is False
    assert second.was_replayed is True
    assert second.sale.id == first.sale.id
    assert second.sale.receipt_number == first.sale.receipt_number
    assert len(second.items) == 1
    assert len(second.payments) == 1

    after = await count_everything(database, tenant_id)
    assert after["sales"] == before["sales"] + 1, "only one sale was written"
    assert after["movements"] == before["movements"] + 1, "only one movement was written"
    assert await stock_level(database, tenant_id, product_id) == Decimal("8.000")


@pytest.mark.integration
async def test_two_different_operations_are_two_sales(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    owner = owner_context(tenant_id, seller_id=seller_id)
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=product_id,
        quantity=Decimal("10.000"),
    )

    first = await service.complete_sale(
        owner,
        lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("1.000"))],
        payments=[],
        operation_id=uuid4(),
    )
    second = await service.complete_sale(
        owner,
        lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("1.000"))],
        payments=[],
        operation_id=uuid4(),
    )

    assert first.sale.id != second.sale.id
    assert first.sale.receipt_number == "OBI-000001"
    assert second.sale.receipt_number == "OBI-000002"


@pytest.mark.integration
async def test_a_sale_without_an_operation_identifier_is_never_a_replay(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    owner = owner_context(tenant_id, seller_id=seller_id)
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=product_id,
        quantity=Decimal("10.000"),
    )

    for _ in range(2):
        result = await service.complete_sale(
            owner,
            lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("1.000"))],
            payments=[],
        )
        assert result.was_replayed is False


# ---------------------------------------------------------------------------
# Cancelling
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_cancelling_returns_the_stock_the_money_and_the_ledger(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    owner = owner_context(tenant_id, seller_id=seller_id)
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=product_id,
        quantity=Decimal("10.000"),
    )
    sale = (
        await service.complete_sale(
            owner,
            lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("2.000"))],
            payments=[PaymentRequest(amount=Decimal("90000.00"))],
        )
    ).sale

    cancelled = await service.cancel_sale(
        owner, sale_id=sale.id, reason="the customer brought it back"
    )

    assert cancelled.sale.status is SaleStatus.CANCELLED
    assert cancelled.sale.cancellation_reason == "the customer brought it back"
    assert cancelled.sale.receipt_number == sale.receipt_number, "the number is not reused"
    assert [payment.is_refunded() for payment in cancelled.payments] == [True]
    assert await stock_level(database, tenant_id, product_id) == Decimal("10.000")

    async with database.transaction_scope() as unit_of_work:
        entries = await ledger_entry_crud.list_for_reference(
            unit_of_work.session_handle,
            tenant_id=tenant_id,
            reference_type="sale",
            reference_id=sale.id,
        )
        net = await ledger_entry_crud.total_signed_amount(unit_of_work.session_handle, tenant_id)
        movements = await inventory_movement_crud.list_for_product(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=product_id
        )

    assert [entry.entry_type for entry in entries] == [
        LedgerEntryType.SALE_REVENUE,
        LedgerEntryType.REFUND,
    ]
    assert net == Decimal("0.00"), "a cancelled sale leaves the books where they started"
    assert [movement.movement_type.value for movement in movements] == [
        "RETURN",
        "SALE",
        "STOCK_RECEIVED",
    ]


@pytest.mark.integration
async def test_cancelling_twice_returns_the_stock_once(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    """The first cancellation moved the goods; a second must not move them again."""
    owner = owner_context(tenant_id, seller_id=seller_id)
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=product_id,
        quantity=Decimal("10.000"),
    )
    sale = (
        await service.complete_sale(
            owner,
            lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("2.000"))],
            payments=[PaymentRequest(amount=Decimal("90000.00"))],
        )
    ).sale

    first = await service.cancel_sale(owner, sale_id=sale.id, reason="wrong item")
    second = await service.cancel_sale(owner, sale_id=sale.id, reason="something else")

    assert first.sale.cancellation_reason == "wrong item"
    assert second.sale.cancellation_reason == "wrong item"
    assert await stock_level(database, tenant_id, product_id) == Decimal("10.000")

    async with database.transaction_scope() as unit_of_work:
        movements = await inventory_movement_crud.list_for_product(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=product_id
        )
        net = await ledger_entry_crud.total_signed_amount(unit_of_work.session_handle, tenant_id)

    assert [movement.movement_type.value for movement in movements].count("RETURN") == 1
    assert net == Decimal("0.00")


@pytest.mark.integration
async def test_cancelling_needs_a_reason(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    owner = owner_context(tenant_id, seller_id=seller_id)
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=product_id,
        quantity=Decimal("3.000"),
    )
    sale = (
        await service.complete_sale(
            owner,
            lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("1.000"))],
            payments=[],
        )
    ).sale

    with pytest.raises(InvalidInputError, match="reason is required"):
        await service.cancel_sale(owner, sale_id=sale.id, reason="   ")


@pytest.mark.integration
async def test_a_sale_cannot_be_cancelled_through_another_business(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    owner = owner_context(tenant_id, seller_id=seller_id)
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=product_id,
        quantity=Decimal("3.000"),
    )
    sale = (
        await service.complete_sale(
            owner,
            lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("1.000"))],
            payments=[],
        )
    ).sale

    other_tenant = await insert_tenant(database)
    other_seller = await insert_user(database)

    with pytest.raises(NotFoundError):
        await service.cancel_sale(
            owner_context(other_tenant, seller_id=other_seller),
            sale_id=sale.id,
            reason="not mine",
        )


# ---------------------------------------------------------------------------
# Reading and authorization
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_sale_can_be_read_with_its_lines_and_payments(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    owner = owner_context(tenant_id, seller_id=seller_id)
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=product_id,
        quantity=Decimal("3.000"),
    )
    sale = (
        await service.complete_sale(
            owner,
            lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("1.000"))],
            payments=[PaymentRequest(amount=Decimal("45000.00"))],
        )
    ).sale

    found = await service.get_sale(owner, sale_id=sale.id)

    assert found.sale == sale
    assert len(found.items) == 1
    assert len(found.payments) == 1
    assert [entry.id for entry in await service.list_sales(owner)] == [sale.id]


@pytest.mark.integration
async def test_a_salesperson_may_sell(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    seller = context_for(tenant_id, "SALES", seller_id=seller_id)
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner_context(tenant_id, seller_id=seller_id),
        product_id=product_id,
        quantity=Decimal("3.000"),
    )

    result = await service.complete_sale(
        seller,
        lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("1.000"))],
        payments=[PaymentRequest(amount=Decimal("45000.00"))],
    )

    assert result.sale.seller_id == seller_id


@pytest.mark.integration
async def test_an_inventory_worker_may_not_sell(
    database: Database, service: SalesService, tenant_id: UUID, seller_id: UUID, product_id: UUID
) -> None:
    """Counting stock and selling it are different capabilities, on purpose."""
    worker = context_for(tenant_id, "INVENTORY", seller_id=seller_id)

    with pytest.raises(AuthorizationError):
        await service.complete_sale(
            worker,
            lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("1.000"))],
            payments=[],
        )
    with pytest.raises(AuthorizationError):
        await service.list_sales(worker)
    with pytest.raises(AuthorizationError):
        await service.cancel_sale(worker, sale_id=uuid4(), reason="not mine to cancel")


@pytest.mark.integration
async def test_a_salesperson_may_not_cancel(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    """Cancelling reverses money that was taken, which is a supervisor's decision."""
    owner = owner_context(tenant_id, seller_id=seller_id)
    await stock_up(
        database,
        inventory_service,
        tenant_context=owner,
        product_id=product_id,
        quantity=Decimal("3.000"),
    )
    sale = (
        await service.complete_sale(
            owner,
            lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("1.000"))],
            payments=[PaymentRequest(amount=Decimal("45000.00"))],
        )
    ).sale

    seller = context_for(tenant_id, "SALES", seller_id=seller_id)

    with pytest.raises(AuthorizationError):
        await service.cancel_sale(seller, sale_id=sale.id, reason="changed my mind")

    assert await stock_level(database, tenant_id, product_id) == Decimal("2.000")


# ---------------------------------------------------------------------------
# The trail
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_completing_a_sale_is_one_event_in_the_audit_trail(
    database: Database,
    service: SalesService,
    inventory_service: InventoryService,
    tenant_id: UUID,
    seller_id: UUID,
    product_id: UUID,
) -> None:
    """M14.1.3: one event for the use case, not one per table the sale wrote to."""
    context = context_for(tenant_id, "SALES", seller_id=seller_id)
    await inventory_service.receive_stock(
        context_for(tenant_id, "OWNER", seller_id=seller_id),
        product_id=product_id,
        quantity=Decimal("10.000"),
    )

    result = await service.complete_sale(
        context,
        lines=[SaleLineRequest(product_id=product_id, quantity=Decimal("2.000"))],
        payments=[PaymentRequest(amount=Decimal("90000.00"))],
    )

    async with database.transaction_scope() as unit_of_work:
        events = await audit_event_crud.list_for_entity(
            unit_of_work.session_handle,
            tenant_id=tenant_id,
            entity_type="sale",
            entity_id=result.sale.id,
        )

    assert [event.action for event in events] == ["complete_sale"]
    assert events[0].actor_id == seller_id
    assert events[0].detail["receipt_number"] == result.sale.receipt_number
