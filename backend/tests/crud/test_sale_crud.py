"""Tests for sales persistence.

Three properties are tested here that only the database can prove: that a receipt number is
unique per business and issued once even when two sales are made at the same moment, that an
offline operation can only be recorded once, and that the ledger cannot be rewritten. The
last is enforced by a trigger, so it is tested with raw SQL rather than by calling a function
that does not exist.
"""

from __future__ import annotations

import ast
import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.errors import ConflictError, NotFoundError
from ahia.crud import (
    customer_crud,
    ledger_entry_crud,
    payment_crud,
    product_crud,
    receipt_counter_crud,
    sale_crud,
    sale_item_crud,
    tenant_crud,
    user_crud,
)
from ahia.models.entities.customer_model import CustomerModel
from ahia.models.entities.ledger_entry_model import (
    LedgerDirection,
    LedgerEntryModel,
    LedgerEntryType,
)
from ahia.models.entities.payment_model import PaymentMethod, PaymentModel
from ahia.models.entities.product_model import ProductModel
from ahia.models.entities.receipt_counter_model import (
    ReceiptCounterModel,
    clean_receipt_prefix,
    render_receipt_number,
)
from ahia.models.entities.sale_item_model import SaleItemModel
from ahia.models.entities.sale_model import SaleModel
from ahia.models.entities.tenant_model import TenantModel
from ahia.models.entities.user_model import UserModel

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 14, 9, 30, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)

LEDGER_CRUD_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "ahia" / "crud" / "ledger_entry_crud.py"
)


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


async def insert_tenant(database: Database) -> UUID:
    identifier = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await tenant_crud.create(
            unit_of_work.session_handle,
            TenantModel.create(
                tenant_id=identifier,
                name="Obi Electronics",
                slug=f"obi-{identifier.hex[:8]}",
                now=NOW,
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


async def insert_product(database: Database, tenant_id: UUID, *, name: str = "Rice 50kg") -> UUID:
    identifier = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(
            unit_of_work.session_handle,
            ProductModel.create(
                product_id=identifier,
                tenant_id=tenant_id,
                name=name,
                selling_price=Decimal("45000.00"),
                now=NOW,
            ),
        )
        await unit_of_work.commit()
    return identifier


async def insert_customer(database: Database, tenant_id: UUID, *, name: str = "Ada Obi") -> UUID:
    identifier = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await customer_crud.create(
            unit_of_work.session_handle,
            CustomerModel.create(
                customer_id=identifier,
                tenant_id=tenant_id,
                name=name,
                now=NOW,
            ),
        )
        await unit_of_work.commit()
    return identifier


@pytest.fixture
async def tenant_id(database: Database) -> UUID:
    return await insert_tenant(database)


@pytest.fixture
async def seller_id(database: Database) -> UUID:
    return await insert_user(database)


@pytest.fixture
async def product_id(database: Database, tenant_id: UUID) -> UUID:
    return await insert_product(database, tenant_id)


def build_sale(
    *,
    tenant_id: UUID,
    seller_id: UUID,
    receipt_number: str = "OBI-000001",
    **overrides: object,
) -> SaleModel:
    parameters: dict[str, object] = {
        "sale_id": uuid4(),
        "tenant_id": tenant_id,
        "receipt_number": receipt_number,
        "seller_id": seller_id,
        "subtotal": Decimal("90000.00"),
        "now": NOW,
        "discount_amount": Decimal("0.00"),
    }
    parameters.update(overrides)
    return SaleModel.issue(**parameters)  # type: ignore[arg-type]


async def persist_sale(database: Database, sale: SaleModel) -> SaleModel:
    async with database.transaction_scope() as unit_of_work:
        stored = await sale_crud.create(unit_of_work.session_handle, sale)
        await unit_of_work.commit()
    return stored


# ---------------------------------------------------------------------------
# Receipt numbering
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_receipt_numbers_start_at_one_and_increment(
    database: Database, tenant_id: UUID
) -> None:
    async with database.transaction_scope() as unit_of_work:
        first = await receipt_counter_crud.allocate_receipt_number(
            unit_of_work.session_handle, tenant_id=tenant_id, prefix="obi", now=NOW
        )
        second = await receipt_counter_crud.allocate_receipt_number(
            unit_of_work.session_handle, tenant_id=tenant_id, prefix="obi", now=NOW
        )
        await unit_of_work.commit()

    assert first == "OBI-000001"
    assert second == "OBI-000002"


@pytest.mark.integration
async def test_each_business_counts_its_own_receipts(database: Database, tenant_id: UUID) -> None:
    """A shared counter would make a customer's receipts jump by other businesses' sales."""
    other_tenant = await insert_tenant(database)

    async with database.transaction_scope() as unit_of_work:
        ours = await receipt_counter_crud.allocate_receipt_number(
            unit_of_work.session_handle, tenant_id=tenant_id, prefix="OBI", now=NOW
        )
        theirs = await receipt_counter_crud.allocate_receipt_number(
            unit_of_work.session_handle, tenant_id=other_tenant, prefix="ADA", now=NOW
        )
        await unit_of_work.commit()

    assert ours == "OBI-000001"
    assert theirs == "ADA-000001"


@pytest.mark.integration
async def test_two_simultaneous_sales_get_different_receipt_numbers(
    database: Database, tenant_id: UUID
) -> None:
    """The property the row lock exists for: two tills, one counter, no collision."""

    async def allocate() -> str:
        async with database.transaction_scope() as unit_of_work:
            number = await receipt_counter_crud.allocate_receipt_number(
                unit_of_work.session_handle, tenant_id=tenant_id, prefix="OBI", now=NOW
            )
            await unit_of_work.commit()
        return number

    numbers = await asyncio.gather(*[allocate() for _ in range(5)])

    assert len(set(numbers)) == 5
    assert sorted(numbers) == [f"OBI-{index:06d}" for index in range(1, 6)]


@pytest.mark.integration
async def test_a_rolled_back_sale_does_not_consume_a_number(
    database: Database, tenant_id: UUID
) -> None:
    """A number that was never printed is not a number anybody holds."""
    async with database.transaction_scope() as unit_of_work:
        await receipt_counter_crud.allocate_receipt_number(
            unit_of_work.session_handle, tenant_id=tenant_id, prefix="OBI", now=NOW
        )
        await unit_of_work.commit()

    with pytest.raises(RuntimeError):
        async with database.transaction_scope() as unit_of_work:
            await receipt_counter_crud.allocate_receipt_number(
                unit_of_work.session_handle, tenant_id=tenant_id, prefix="OBI", now=NOW
            )
            raise RuntimeError("the sale failed after the number was claimed")

    async with database.transaction_scope() as unit_of_work:
        number = await receipt_counter_crud.allocate_receipt_number(
            unit_of_work.session_handle, tenant_id=tenant_id, prefix="OBI", now=NOW
        )
        await unit_of_work.commit()

    assert number == "OBI-000002", "the rolled-back claim was released"


@pytest.mark.unit
def test_a_receipt_number_is_readable_and_the_prefix_is_sanitised() -> None:
    """A receipt number is read aloud, so punctuation is stripped and length is bounded."""
    assert render_receipt_number(prefix="OBI", number=7) == "OBI-000007"
    assert render_receipt_number(prefix="OBI", number=1234567) == "OBI-1234567", (
        "a number past the padded width widens rather than truncating"
    )

    assert clean_receipt_prefix("obi-electronics") == "OBI", "the first word, not a fragment"
    assert clean_receipt_prefix("  ada's fabrics  ") == "ADAS"
    assert clean_receipt_prefix("a-very-long-prefix") == "A"
    assert clean_receipt_prefix("  --  ") == "R", "a prefix with nothing in it falls back"

    counter = ReceiptCounterModel.for_new_business(tenant_id=uuid4(), prefix="obi", now=NOW)
    assert counter.last_receipt_number == 0
    assert counter.next_number() == 1
    assert counter.with_next_number(at=NOW).render() == "OBI-000001"


@pytest.mark.integration
async def test_a_receipt_number_cannot_be_used_twice(
    database: Database, tenant_id: UUID, seller_id: UUID
) -> None:
    await persist_sale(database, build_sale(tenant_id=tenant_id, seller_id=seller_id))

    with pytest.raises(ConflictError) as captured:
        await persist_sale(
            database,
            build_sale(tenant_id=tenant_id, seller_id=seller_id, receipt_number="OBI-000001"),
        )

    assert "already used" in (captured.value.context.detail or "")


@pytest.mark.integration
async def test_the_same_receipt_number_is_free_in_another_business(database: Database) -> None:
    first_tenant = await insert_tenant(database)
    second_tenant = await insert_tenant(database)
    first_seller = await insert_user(database)
    second_seller = await insert_user(database)

    await persist_sale(database, build_sale(tenant_id=first_tenant, seller_id=first_seller))
    await persist_sale(database, build_sale(tenant_id=second_tenant, seller_id=second_seller))


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_an_operation_identifier_is_recorded_once(
    database: Database, tenant_id: UUID, seller_id: UUID
) -> None:
    operation_id = uuid4()
    await persist_sale(
        database,
        build_sale(tenant_id=tenant_id, seller_id=seller_id, operation_id=operation_id),
    )

    async with database.transaction_scope() as unit_of_work:
        found = await sale_crud.get_by_operation_id(
            unit_of_work.session_handle, tenant_id=tenant_id, operation_id=operation_id
        )

    assert found is not None
    assert found.receipt_number == "OBI-000001"

    with pytest.raises(ConflictError) as captured:
        async with database.transaction_scope() as unit_of_work:
            await sale_crud.create(
                unit_of_work.session_handle,
                build_sale(
                    tenant_id=tenant_id,
                    seller_id=seller_id,
                    receipt_number="OBI-000002",
                    operation_id=operation_id,
                ),
            )
            await unit_of_work.commit()

    assert "already been recorded" in (captured.value.context.detail or "")


@pytest.mark.integration
async def test_many_sales_may_have_no_operation_identifier(
    database: Database, tenant_id: UUID, seller_id: UUID
) -> None:
    """The partial index means the nulls do not collide."""
    for index in range(3):
        await persist_sale(
            database,
            build_sale(
                tenant_id=tenant_id,
                seller_id=seller_id,
                receipt_number=f"OBI-{index + 1:06d}",
            ),
        )

    async with database.transaction_scope() as unit_of_work:
        assert await sale_crud.count_for_tenant(unit_of_work.session_handle, tenant_id) == 3


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_sale_is_invisible_to_another_business(
    database: Database, tenant_id: UUID, seller_id: UUID
) -> None:
    other_tenant = await insert_tenant(database)
    sale = await persist_sale(database, build_sale(tenant_id=tenant_id, seller_id=seller_id))

    async with database.transaction_scope() as unit_of_work:
        elsewhere = await sale_crud.get_by_id(
            unit_of_work.session_handle, tenant_id=other_tenant, sale_id=sale.id
        )
        by_receipt = await sale_crud.get_by_receipt_number(
            unit_of_work.session_handle, tenant_id=other_tenant, receipt_number="OBI-000001"
        )
        listed = await sale_crud.list_for_tenant(unit_of_work.session_handle, other_tenant)

    assert elsewhere is None
    assert by_receipt is None
    assert listed == []


@pytest.mark.integration
async def test_a_sale_cannot_be_made_to_another_businesss_customer(
    database: Database, tenant_id: UUID, seller_id: UUID
) -> None:
    """The composite customer reference refuses it, not only a service."""
    other_tenant = await insert_tenant(database)
    foreign_customer = await insert_customer(database, other_tenant, name="Theirs")

    with pytest.raises(Exception) as captured:
        await persist_sale(
            database,
            build_sale(tenant_id=tenant_id, seller_id=seller_id, customer_id=foreign_customer),
        )

    assert "fk_sales_customer_id_tenant_id_customers" in str(captured.value)


# ---------------------------------------------------------------------------
# Sale lines
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_sale_line_round_trips(
    database: Database, tenant_id: UUID, seller_id: UUID, product_id: UUID
) -> None:
    sale = await persist_sale(database, build_sale(tenant_id=tenant_id, seller_id=seller_id))
    item = SaleItemModel.for_product(
        item_id=uuid4(),
        tenant_id=tenant_id,
        sale_id=sale.id,
        product_id=product_id,
        product_name="Rice 50kg",
        unit_price=Decimal("45000.00"),
        quantity=Decimal("2.000"),
        now=NOW,
        discount_amount=Decimal("5000.00"),
    )

    async with database.transaction_scope() as unit_of_work:
        await sale_item_crud.create(unit_of_work.session_handle, item)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        lines = await sale_item_crud.list_for_sale(
            unit_of_work.session_handle, tenant_id=tenant_id, sale_id=sale.id
        )
        count = await sale_item_crud.count_for_sale(
            unit_of_work.session_handle, tenant_id=tenant_id, sale_id=sale.id
        )

    assert lines == [item]
    assert lines[0].line_total == Decimal("85000.00")
    assert count == 1


@pytest.mark.integration
async def test_a_line_cannot_belong_to_another_businesss_sale(
    database: Database, tenant_id: UUID, seller_id: UUID, product_id: UUID
) -> None:
    other_tenant = await insert_tenant(database)
    other_seller = await insert_user(database)
    foreign_sale = await persist_sale(
        database, build_sale(tenant_id=other_tenant, seller_id=other_seller)
    )

    with pytest.raises(Exception) as captured:
        async with database.transaction_scope() as unit_of_work:
            await sale_item_crud.create(
                unit_of_work.session_handle,
                SaleItemModel.for_product(
                    item_id=uuid4(),
                    tenant_id=tenant_id,
                    sale_id=foreign_sale.id,
                    product_id=product_id,
                    product_name="Rice 50kg",
                    unit_price=Decimal("45000.00"),
                    quantity=Decimal("1.000"),
                    now=NOW,
                ),
            )
            await unit_of_work.commit()

    assert "fk_sale_items_sale_id_tenant_id_sales" in str(captured.value)


@pytest.mark.integration
async def test_a_line_cannot_reference_another_businesss_product(
    database: Database, tenant_id: UUID, seller_id: UUID
) -> None:
    other_tenant = await insert_tenant(database)
    foreign_product = await insert_product(database, other_tenant, name="Theirs")
    sale = await persist_sale(database, build_sale(tenant_id=tenant_id, seller_id=seller_id))

    with pytest.raises(Exception) as captured:
        async with database.transaction_scope() as unit_of_work:
            await sale_item_crud.create(
                unit_of_work.session_handle,
                SaleItemModel.for_product(
                    item_id=uuid4(),
                    tenant_id=tenant_id,
                    sale_id=sale.id,
                    product_id=foreign_product,
                    product_name="Rice 50kg",
                    unit_price=Decimal("45000.00"),
                    quantity=Decimal("1.000"),
                    now=NOW,
                ),
            )
            await unit_of_work.commit()

    assert "fk_sale_items_product_id_tenant_id_products" in str(captured.value)


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_payment_round_trips_and_can_be_refunded(
    database: Database, tenant_id: UUID, seller_id: UUID
) -> None:
    sale = await persist_sale(database, build_sale(tenant_id=tenant_id, seller_id=seller_id))
    payment = PaymentModel.received(
        payment_id=uuid4(),
        tenant_id=tenant_id,
        sale_id=sale.id,
        amount=Decimal("90000.00"),
        method=PaymentMethod.CASH,
        now=NOW,
    )

    async with database.transaction_scope() as unit_of_work:
        await payment_crud.create(unit_of_work.session_handle, payment)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        stored = await payment_crud.list_for_sale(
            unit_of_work.session_handle, tenant_id=tenant_id, sale_id=sale.id
        )
        await payment_crud.update(unit_of_work.session_handle, stored[0].refunded(at=LATER))
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        refunded = await payment_crud.get_by_id(
            unit_of_work.session_handle, tenant_id=tenant_id, payment_id=payment.id
        )

    assert refunded is not None
    assert refunded.is_refunded() is True
    assert refunded.refunded_at == LATER
    assert refunded.amount == payment.amount, "the amount that was taken does not change"


@pytest.mark.integration
async def test_a_payment_cannot_belong_to_another_businesss_sale(
    database: Database, tenant_id: UUID, seller_id: UUID
) -> None:
    other_tenant = await insert_tenant(database)
    other_seller = await insert_user(database)
    foreign_sale = await persist_sale(
        database, build_sale(tenant_id=other_tenant, seller_id=other_seller)
    )

    with pytest.raises(Exception) as captured:
        async with database.transaction_scope() as unit_of_work:
            await payment_crud.create(
                unit_of_work.session_handle,
                PaymentModel.received(
                    payment_id=uuid4(),
                    tenant_id=tenant_id,
                    sale_id=foreign_sale.id,
                    amount=Decimal("100.00"),
                    method=PaymentMethod.CASH,
                    now=NOW,
                ),
            )
            await unit_of_work.commit()

    assert "fk_payments_sale_id_tenant_id_sales" in str(captured.value)


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_ledger_entry_round_trips(
    database: Database, tenant_id: UUID, seller_id: UUID
) -> None:
    sale = await persist_sale(database, build_sale(tenant_id=tenant_id, seller_id=seller_id))
    entry = LedgerEntryModel.record(
        entry_id=uuid4(),
        tenant_id=tenant_id,
        entry_type=LedgerEntryType.SALE_REVENUE,
        amount=Decimal("90000.00"),
        reference_type="sale",
        reference_id=sale.id,
        now=NOW,
    )

    async with database.transaction_scope() as unit_of_work:
        await ledger_entry_crud.record(unit_of_work.session_handle, entry)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        entries = await ledger_entry_crud.list_for_reference(
            unit_of_work.session_handle,
            tenant_id=tenant_id,
            reference_type="sale",
            reference_id=sale.id,
        )

    assert entries == [entry]
    assert entries[0].direction is LedgerDirection.CREDIT


@pytest.mark.integration
async def test_the_ledger_total_nets_credits_against_debits(
    database: Database, tenant_id: UUID, seller_id: UUID
) -> None:
    sale = await persist_sale(database, build_sale(tenant_id=tenant_id, seller_id=seller_id))

    async with database.transaction_scope() as unit_of_work:
        await ledger_entry_crud.record(
            unit_of_work.session_handle,
            LedgerEntryModel.record(
                entry_id=uuid4(),
                tenant_id=tenant_id,
                entry_type=LedgerEntryType.SALE_REVENUE,
                amount=Decimal("90000.00"),
                reference_type="sale",
                reference_id=sale.id,
                now=NOW,
            ),
        )
        await ledger_entry_crud.record(
            unit_of_work.session_handle,
            LedgerEntryModel.record(
                entry_id=uuid4(),
                tenant_id=tenant_id,
                entry_type=LedgerEntryType.REFUND,
                amount=Decimal("90000.00"),
                reference_type="sale",
                reference_id=sale.id,
                now=LATER,
            ),
        )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        total = await ledger_entry_crud.total_signed_amount(unit_of_work.session_handle, tenant_id)
        since = await ledger_entry_crud.total_signed_amount(
            unit_of_work.session_handle, tenant_id, since=LATER
        )

    assert total == Decimal("0.00")
    assert since == Decimal("-90000.00")


@pytest.mark.integration
async def test_a_ledger_total_is_zero_for_a_business_that_has_done_nothing(
    database: Database, tenant_id: UUID
) -> None:
    async with database.transaction_scope() as unit_of_work:
        total = await ledger_entry_crud.total_signed_amount(unit_of_work.session_handle, tenant_id)

    assert total == Decimal("0.00")


@pytest.mark.integration
async def test_a_ledger_total_is_scoped_to_the_business(
    database: Database, tenant_id: UUID, seller_id: UUID
) -> None:
    other_tenant = await insert_tenant(database)
    async with database.transaction_scope() as unit_of_work:
        await ledger_entry_crud.record(
            unit_of_work.session_handle,
            LedgerEntryModel.record(
                entry_id=uuid4(),
                tenant_id=other_tenant,
                entry_type=LedgerEntryType.EXPENSE,
                amount=Decimal("5000.00"),
                reference_type="expense",
                reference_id=uuid4(),
                now=NOW,
            ),
        )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        ours = await ledger_entry_crud.total_signed_amount(unit_of_work.session_handle, tenant_id)

    assert ours == Decimal("0.00")


@pytest.mark.integration
async def test_the_ledger_cannot_be_updated(
    database: Database, tenant_id: UUID, seller_id: UUID
) -> None:
    sale = await persist_sale(database, build_sale(tenant_id=tenant_id, seller_id=seller_id))
    async with database.transaction_scope() as unit_of_work:
        entry = await ledger_entry_crud.record(
            unit_of_work.session_handle,
            LedgerEntryModel.record(
                entry_id=uuid4(),
                tenant_id=tenant_id,
                entry_type=LedgerEntryType.SALE_REVENUE,
                amount=Decimal("100.00"),
                reference_type="sale",
                reference_id=sale.id,
                now=NOW,
            ),
        )
        await unit_of_work.commit()

    with pytest.raises(DBAPIError) as captured:
        async with database.engine.begin() as connection:
            await connection.execute(
                text("UPDATE ledger_entries SET amount = 1 WHERE id = :id"),
                {"id": str(entry.id)},
            )

    assert "append-only" in str(captured.value)


@pytest.mark.integration
async def test_the_ledger_cannot_be_deleted_from(
    database: Database, tenant_id: UUID, seller_id: UUID
) -> None:
    """The trigger fires per row, so there has to be a row for it to refuse."""
    sale = await persist_sale(database, build_sale(tenant_id=tenant_id, seller_id=seller_id))
    async with database.transaction_scope() as unit_of_work:
        await ledger_entry_crud.record(
            unit_of_work.session_handle,
            LedgerEntryModel.record(
                entry_id=uuid4(),
                tenant_id=tenant_id,
                entry_type=LedgerEntryType.SALE_REVENUE,
                amount=Decimal("100.00"),
                reference_type="sale",
                reference_id=sale.id,
                now=NOW,
            ),
        )
        await unit_of_work.commit()

    with pytest.raises(DBAPIError) as captured:
        async with database.engine.begin() as connection:
            await connection.execute(text("DELETE FROM ledger_entries"))

    assert "append-only" in str(captured.value)


@pytest.mark.unit
def test_the_ledger_persistence_offers_no_way_to_change_an_entry() -> None:
    tree = ast.parse(LEDGER_CRUD_PATH.read_text(encoding="utf-8"))
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    forbidden = {
        name
        for name in defined
        if name in {"update", "delete", "remove", "edit", "amend"} or name.startswith("update_")
    }
    assert not forbidden, f"the ledger gained a mutating function: {sorted(forbidden)}"


# ---------------------------------------------------------------------------
# Updating a sale
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_sale_can_be_cancelled_in_storage(
    database: Database, tenant_id: UUID, seller_id: UUID
) -> None:
    sale = await persist_sale(database, build_sale(tenant_id=tenant_id, seller_id=seller_id))

    async with database.transaction_scope() as unit_of_work:
        cancelled = await sale_crud.update(
            unit_of_work.session_handle,
            sale.cancelled(at=LATER, reason="customer changed their mind"),
        )
        await unit_of_work.commit()

    assert cancelled.is_cancelled() is True
    assert cancelled.cancellation_reason == "customer changed their mind"

    async with database.transaction_scope() as unit_of_work:
        reread = await sale_crud.require_by_id(
            unit_of_work.session_handle, tenant_id=tenant_id, sale_id=sale.id
        )

    assert reread == cancelled
    assert reread.total_amount == sale.total_amount, "the money that moved is still recorded"


@pytest.mark.integration
async def test_a_sale_update_cannot_reach_another_business(
    database: Database, tenant_id: UUID, seller_id: UUID
) -> None:
    other_tenant = await insert_tenant(database)
    sale = await persist_sale(database, build_sale(tenant_id=tenant_id, seller_id=seller_id))
    stranger = SaleModel(
        id=sale.id,
        tenant_id=other_tenant,
        receipt_number=sale.receipt_number,
        seller_id=seller_id,
        subtotal=sale.subtotal,
        discount_amount=sale.discount_amount,
        total_amount=sale.total_amount,
        occurred_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )

    with pytest.raises(NotFoundError):
        async with database.transaction_scope() as unit_of_work:
            await sale_crud.update(unit_of_work.session_handle, stranger)


@pytest.mark.integration
async def test_an_unknown_receipt_number_finds_nothing(database: Database, tenant_id: UUID) -> None:
    async with database.transaction_scope() as unit_of_work:
        found = await sale_crud.get_by_receipt_number(
            unit_of_work.session_handle, tenant_id=tenant_id, receipt_number="NOPE-000001"
        )

    assert found is None
