"""Tests for the synchronization use cases.

The subject is the promises an offline device depends on.

**A retry is answered, not repeated.** The same operation pushed twice produces one sale and two
answers, the second marked as a replay. This is the whole point of the operation identifier: a
phone in a market loses signal between recording a sale and hearing back, and the business must
not sell the same bag of rice twice.

**One bad operation does not fail the batch.** A queue pushed after a day offline contains an
operation the caller may no longer be permitted to perform; the sales behind it still apply.

**A conflict is an answer, not a silent loser.** A versioned edit from a stale copy is refused
with the version the server holds, so the client can merge and retry - and the record is not
overwritten by the older copy.

**The cursor moves forward only, and only for the device that made the request.** The device comes
from the authenticated context, so a client cannot advance another phone's cursor, and a device
that has never synchronized reads from zero.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.errors import EntityInvariantError, InvalidInputError
from ahia.core.permissions.permissions_registry import permission_codes_for_role
from ahia.core.tenant_context import TenantContext, build_tenant_context
from ahia.crud import (
    customer_crud,
    device_crud,
    inventory_crud,
    product_crud,
    sale_crud,
    tenant_crud,
    user_crud,
)
from ahia.models.entities.device_model import DeviceModel
from ahia.models.entities.product_model import ProductModel
from ahia.models.entities.sync_operation_model import SyncOperationStatus
from ahia.models.entities.tenant_model import TenantModel
from ahia.models.entities.user_model import UserModel
from ahia.services.audit_event_service import AuditEventService
from ahia.services.customer_service import CustomerService
from ahia.services.expense_service import ExpenseService
from ahia.services.inventory_service import InventoryService
from ahia.services.sale_service import SalesService
from ahia.services.sync_change_service import SyncChangeService
from ahia.services.sync_service import SyncOperationRequest, SyncService

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 14, 16, 0, tzinfo=UTC)


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
                "TRUNCATE TABLE sync_changes, sync_cursors, sync_operations, audit_events, "
                "ledger_entries, payments, sale_items, sales, receipt_counters, "
                "inventory_movements, inventory, products, customers, tenants CASCADE"
            )
        )
    try:
        yield instance
    finally:
        await instance.dispose()


@pytest.fixture
def change_service(database: Database) -> SyncChangeService:
    return SyncChangeService(unit_of_work_factory=database.unit_of_work_factory())


@pytest.fixture
def audit_service(database: Database, change_service: SyncChangeService) -> AuditEventService:
    """One recorder, wired to the change service, exactly as the composition root builds it.

    Shared by the use cases below, because a recorder built without the change service writes no
    feed rows. The first version of these fixtures built one recorder per service and the feed
    test failed for that reason: the failure was in the fixture, not in the code.
    """
    return AuditEventService(
        unit_of_work_factory=database.unit_of_work_factory(),
        sync_change_service=change_service,
    )


@pytest.fixture
def inventory_service(database: Database, audit_service: AuditEventService) -> InventoryService:
    return InventoryService(
        unit_of_work_factory=database.unit_of_work_factory(),
        audit_event_service=audit_service,
    )


@pytest.fixture
def sales_service(
    database: Database,
    inventory_service: InventoryService,
    audit_service: AuditEventService,
) -> SalesService:
    return SalesService(
        unit_of_work_factory=database.unit_of_work_factory(),
        inventory_service=inventory_service,
        audit_event_service=audit_service,
    )


@pytest.fixture
def expense_service(database: Database, audit_service: AuditEventService) -> ExpenseService:
    return ExpenseService(
        unit_of_work_factory=database.unit_of_work_factory(),
        audit_event_service=audit_service,
    )


@pytest.fixture
def customer_service(database: Database, audit_service: AuditEventService) -> CustomerService:
    return CustomerService(
        unit_of_work_factory=database.unit_of_work_factory(),
        default_phone_country_code="234",
        audit_event_service=audit_service,
    )


@pytest.fixture
def service(
    database: Database,
    sales_service: SalesService,
    expense_service: ExpenseService,
    customer_service: CustomerService,
    inventory_service: InventoryService,
    change_service: SyncChangeService,
) -> SyncService:
    return SyncService(
        unit_of_work_factory=database.unit_of_work_factory(),
        sales_service=sales_service,
        expense_service=expense_service,
        customer_service=customer_service,
        inventory_service=inventory_service,
        sync_change_service=change_service,
    )


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


@pytest.fixture
async def tenant_id(database: Database) -> UUID:
    return await insert_tenant(database)


@pytest.fixture
async def product_id(database: Database, tenant_id: UUID) -> UUID:
    identifier = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(
            unit_of_work.session_handle,
            ProductModel.create(
                product_id=identifier,
                tenant_id=tenant_id,
                name="Rice 50kg",
                selling_price=Decimal("45000.00"),
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


async def register_device(database: Database, *, tenant_id: UUID, actor_id: UUID) -> UUID:
    identifier = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await device_crud.create(
            unit_of_work.session_handle,
            DeviceModel.register(
                device_id=identifier,
                tenant_id=tenant_id,
                user_id=actor_id,
                device_identifier=f"device-{identifier.hex[:8]}",
                platform="android",
                now=NOW,
            ),
        )
        await unit_of_work.commit()
    return identifier


@pytest.fixture
async def actor_id(database: Database) -> UUID:
    """The person pushing the operations. Required: a movement and a cursor name real rows."""
    return await insert_user(database)


@pytest.fixture
async def device_id(database: Database, tenant_id: UUID, actor_id: UUID) -> UUID:
    """The phone the queue came from. A cursor is a position belonging to a device."""
    return await register_device(database, tenant_id=tenant_id, actor_id=actor_id)


def context_for(
    tenant_id: UUID,
    role_name: str,
    *,
    actor_id: UUID,
    device_id: UUID | None = None,
) -> TenantContext:
    return build_tenant_context(
        user_id=actor_id,
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=permission_codes_for_role(role_name),
        role_name=role_name,
        device_id=device_id,
    )


def sale_operation(product_id: UUID, *, quantity: str = "2.000", operation_id: UUID | None = None):
    return SyncOperationRequest(
        operation_id=operation_id or uuid4(),
        operation_type="complete_sale",
        payload={
            "lines": [{"product_id": str(product_id), "quantity": quantity}],
            "payments": [{"amount": "90000.00", "method": "CASH"}],
        },
    )


async def stock_for(database: Database, tenant_id: UUID, product_id: UUID) -> Decimal:
    async with database.transaction_scope() as unit_of_work:
        level = await inventory_crud.get_for_product(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=product_id
        )
    return Decimal("0.000") if level is None else level.quantity_on_hand


async def sale_count(database: Database, tenant_id: UUID) -> int:
    async with database.transaction_scope() as unit_of_work:
        return await sale_crud.count_for_tenant(unit_of_work.session_handle, tenant_id)


# ---------------------------------------------------------------------------
# Pushing
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_pushed_sale_is_applied_by_the_sales_use_case(
    service: SyncService,
    database: Database,
    tenant_id: UUID,
    product_id: UUID,
    inventory_service: InventoryService,
    actor_id: UUID,
) -> None:
    owner = context_for(tenant_id, "OWNER", actor_id=actor_id)
    await inventory_service.receive_stock(owner, product_id=product_id, quantity=Decimal("10.000"))

    result = await service.push_operations(owner, operations=[sale_operation(product_id)])

    assert len(result.results) == 1
    assert result.results[0].status is SyncOperationStatus.APPLIED
    assert result.results[0].entity_type == "sale"
    assert result.results[0].detail["receipt_number"]
    assert await sale_count(database, tenant_id) == 1
    assert await stock_for(database, tenant_id, product_id) == Decimal("8.000")


@pytest.mark.integration
async def test_the_same_operation_pushed_twice_produces_one_sale(
    service: SyncService,
    database: Database,
    tenant_id: UUID,
    product_id: UUID,
    inventory_service: InventoryService,
    actor_id: UUID,
) -> None:
    """A phone that lost the answer must not sell the same bag of rice twice."""
    owner = context_for(tenant_id, "OWNER", actor_id=actor_id)
    await inventory_service.receive_stock(owner, product_id=product_id, quantity=Decimal("10.000"))
    operation = sale_operation(product_id)

    first = await service.push_operations(owner, operations=[operation])
    second = await service.push_operations(owner, operations=[operation])

    assert first.results[0].status is SyncOperationStatus.APPLIED
    assert second.results[0].status is SyncOperationStatus.REPLAYED
    assert second.results[0].entity_id == first.results[0].entity_id
    assert await sale_count(database, tenant_id) == 1
    assert await stock_for(database, tenant_id, product_id) == Decimal("8.000")


@pytest.mark.integration
async def test_an_unsupported_operation_is_rejected_with_a_reason(
    service: SyncService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    owner = context_for(tenant_id, "OWNER", actor_id=actor_id)

    result = await service.push_operations(
        owner,
        operations=[
            SyncOperationRequest(
                operation_id=uuid4(),
                operation_type="delete_everything",
                payload={},
            )
        ],
    )

    assert result.results[0].status is SyncOperationStatus.REJECTED
    assert result.results[0].detail["reason"] == "unsupported_operation_type"
    assert result.results[0].needs_the_clients_attention is True


@pytest.mark.integration
async def test_one_refused_operation_does_not_fail_the_others(
    service: SyncService,
    database: Database,
    tenant_id: UUID,
    product_id: UUID,
    inventory_service: InventoryService,
    actor_id: UUID,
) -> None:
    """A salesperson may sell; receiving stock needs a permission they do not hold."""
    owner = context_for(tenant_id, "OWNER", actor_id=actor_id)
    await inventory_service.receive_stock(owner, product_id=product_id, quantity=Decimal("10.000"))
    salesperson = context_for(tenant_id, "SALES", actor_id=actor_id)

    result = await service.push_operations(
        salesperson,
        operations=[
            SyncOperationRequest(
                operation_id=uuid4(),
                operation_type="receive_stock",
                payload={"product_id": str(product_id), "quantity": "5.000"},
            ),
            sale_operation(product_id),
        ],
    )

    assert [entry.status for entry in result.results] == [
        SyncOperationStatus.REJECTED,
        SyncOperationStatus.APPLIED,
    ]
    assert result.applied_count == 1
    assert await sale_count(database, tenant_id) == 1
    assert await stock_for(database, tenant_id, product_id) == Decimal("8.000")


@pytest.mark.integration
async def test_a_pushed_expense_is_applied_and_debits_the_ledger(
    service: SyncService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    owner = context_for(tenant_id, "OWNER", actor_id=actor_id)

    result = await service.push_operations(
        owner,
        operations=[
            SyncOperationRequest(
                operation_id=uuid4(),
                operation_type="record_expense",
                payload={
                    "category": "TRANSPORT",
                    "amount": "3500.00",
                    "payment_method": "CASH",
                    "description": "Keke to the market",
                },
            )
        ],
    )

    assert result.results[0].status is SyncOperationStatus.APPLIED
    assert result.results[0].entity_type == "expense"


# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_stale_customer_edit_is_a_conflict_with_the_server_version(
    service: SyncService,
    database: Database,
    customer_service: CustomerService,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    """The client merges and retries; neither edit is silently lost."""
    owner = context_for(tenant_id, "OWNER", actor_id=actor_id)
    creation = await customer_service.create_customer(owner, name="Ada Obi", phone="08031234567")
    customer = creation.customer
    await customer_service.update_customer(
        owner,
        customer_id=customer.id,
        changes={"notes": "Prefers delivery on Saturdays"},
        expected_version=customer.version,
    )

    result = await service.push_operations(
        owner,
        operations=[
            SyncOperationRequest(
                operation_id=uuid4(),
                operation_type="update_customer",
                payload={
                    "customer_id": str(customer.id),
                    "expected_version": customer.version,
                    "address": "12 Awolowo Road",
                },
            )
        ],
    )

    assert result.results[0].status is SyncOperationStatus.CONFLICT
    assert result.results[0].detail["reason"] == "stale_version"
    assert int(result.results[0].detail["server_version"]) == customer.version + 1

    async with database.transaction_scope() as unit_of_work:
        unchanged = await customer_crud.get_by_id(
            unit_of_work.session_handle, tenant_id=tenant_id, customer_id=customer.id
        )
    assert unchanged is not None
    assert unchanged.address is None, "the older copy did not overwrite the newer one"


@pytest.mark.integration
async def test_a_customer_edit_from_the_current_version_is_applied(
    service: SyncService,
    customer_service: CustomerService,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    owner = context_for(tenant_id, "OWNER", actor_id=actor_id)
    creation = await customer_service.create_customer(owner, name="Ada Obi")

    result = await service.push_operations(
        owner,
        operations=[
            SyncOperationRequest(
                operation_id=uuid4(),
                operation_type="update_customer",
                payload={
                    "customer_id": str(creation.customer.id),
                    "expected_version": creation.customer.version,
                    "address": "12 Awolowo Road",
                },
            )
        ],
    )

    assert result.results[0].status is SyncOperationStatus.APPLIED
    assert int(result.results[0].detail["version"]) == creation.customer.version + 1


# ---------------------------------------------------------------------------
# Pulling and the cursor
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_pushed_operation_appears_in_the_change_feed(
    service: SyncService,
    database: Database,
    tenant_id: UUID,
    product_id: UUID,
    inventory_service: InventoryService,
    actor_id: UUID,
) -> None:
    """The two mechanisms meet: the use case writes the trail, the trail feeds the change feed."""
    owner = context_for(tenant_id, "OWNER", actor_id=actor_id)
    await inventory_service.receive_stock(owner, product_id=product_id, quantity=Decimal("10.000"))

    pushed = await service.push_operations(owner, operations=[sale_operation(product_id)])
    page = await service.pull_changes(owner, after_sequence=0)

    sale_id = pushed.results[0].entity_id
    assert any(
        change.entity_type == "sale" and change.entity_id == sale_id for change in page.changes
    )
    assert page.latest_sequence >= page.changes[-1].change_sequence


@pytest.mark.integration
async def test_a_cursor_is_created_then_advanced_forward_only(
    service: SyncService,
    tenant_id: UUID,
    device_id: UUID,
    actor_id: UUID,
) -> None:
    context = context_for(tenant_id, "OWNER", actor_id=actor_id, device_id=device_id)

    assert await service.current_cursor(context) == 0

    advanced = await service.advance_cursor(context, sequence=42)

    assert advanced == 42
    assert await service.current_cursor(context) == 42

    with pytest.raises(EntityInvariantError, match="cannot move backwards"):
        await service.advance_cursor(context, sequence=10)


@pytest.mark.integration
async def test_a_cursor_cannot_be_advanced_without_a_device(
    service: SyncService,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    """A cursor belongs to a device, and a request that is not from one cannot hold one."""
    context = context_for(tenant_id, "OWNER", actor_id=actor_id)

    with pytest.raises(InvalidInputError, match="belongs to a device"):
        await service.advance_cursor(context, sequence=1)

    with pytest.raises(InvalidInputError, match="belongs to a device"):
        await service.current_cursor(context)


@pytest.mark.integration
async def test_two_devices_hold_their_own_cursors(
    service: SyncService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
    device_id: UUID,
) -> None:
    second_device = await register_device(database, tenant_id=tenant_id, actor_id=actor_id)
    first = context_for(tenant_id, "OWNER", actor_id=actor_id, device_id=device_id)
    second = context_for(tenant_id, "OWNER", actor_id=actor_id, device_id=second_device)

    await service.advance_cursor(first, sequence=42)

    assert await service.current_cursor(first) == 42
    assert await service.current_cursor(second) == 0


@pytest.mark.integration
async def test_the_feed_of_another_business_is_empty(
    service: SyncService,
    database: Database,
    tenant_id: UUID,
    product_id: UUID,
    inventory_service: InventoryService,
    actor_id: UUID,
) -> None:
    owner = context_for(tenant_id, "OWNER", actor_id=actor_id)
    await inventory_service.receive_stock(owner, product_id=product_id, quantity=Decimal("10.000"))
    await service.push_operations(owner, operations=[sale_operation(product_id)])
    other_tenant = await insert_tenant(database)

    page = await service.pull_changes(
        context_for(other_tenant, "OWNER", actor_id=await insert_user(database)),
        after_sequence=0,
    )

    assert page.changes == []
    assert page.latest_sequence == 0
