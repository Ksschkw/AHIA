"""Tests for the inventory use cases.

Three things are being proved here, and they are the three the milestone names.

**A quantity cannot change without a movement.** Every operation goes through one path,
and this file checks the ledger after each one: one movement per change, and the movement
agrees with the projection.

**Two workers selling at once do not lose a sale.** The concurrency test runs real
concurrent transactions against real PostgreSQL. A fake would prove nothing: the property
depends on a row lock that only the database provides.

**The business's policy decides what a negative result means.** All three policies are
exercised, including the one that refuses - and the refusal has to leave the ledger
untouched, which is what separates a refused movement from a recorded one.
"""

from __future__ import annotations

import asyncio
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
from ahia.core.errors import (
    AuthorizationError,
    DomainError,
    InvalidInputError,
    NotFoundError,
)
from ahia.core.permissions.permissions_registry import permission_codes_for_role
from ahia.core.tenant_context import TenantContext, build_tenant_context
from ahia.crud import (
    inventory_crud,
    inventory_movement_crud,
    product_crud,
    tenant_crud,
    user_crud,
)
from ahia.models.entities.inventory_movement_model import MovementType
from ahia.models.entities.negative_stock_policy import NegativeStockPolicy
from ahia.models.entities.product_model import ProductModel
from ahia.models.entities.tenant_model import TenantModel
from ahia.models.entities.user_model import UserModel
from ahia.services.inventory_service import InventoryService

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)


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
            text("TRUNCATE TABLE inventory_movements, inventory, products, tenants, users CASCADE")
        )
    try:
        yield instance
    finally:
        await instance.dispose()


@pytest.fixture
def service(database: Database) -> InventoryService:
    return InventoryService(unit_of_work_factory=database.unit_of_work_factory())


async def insert_tenant(database: Database, *, policy: NegativeStockPolicy | None = None) -> UUID:
    tenant = TenantModel.create(
        tenant_id=uuid4(),
        name="Obi Electronics",
        slug=f"obi-{uuid4().hex[:8]}",
        now=NOW,
        **({"negative_stock_policy": policy} if policy is not None else {}),
    )
    async with database.transaction_scope() as unit_of_work:
        await tenant_crud.create(unit_of_work.session_handle, tenant)
        await unit_of_work.commit()
    return tenant.id


async def insert_product(database: Database, tenant_id: UUID, *, name: str = "Rice 50kg") -> UUID:
    product = ProductModel.create(
        product_id=uuid4(),
        tenant_id=tenant_id,
        name=name,
        selling_price=Decimal("45000.00"),
        now=NOW,
    )
    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(unit_of_work.session_handle, product)
        await unit_of_work.commit()
    return product.id


@pytest.fixture
async def tenant_id(database: Database) -> UUID:
    return await insert_tenant(database)


@pytest.fixture
async def product_id(database: Database, tenant_id: UUID) -> UUID:
    return await insert_product(database, tenant_id)


async def context_for(database: Database, tenant_id: UUID, role_name: str) -> TenantContext:
    """Build a context whose actor exists.

    Every movement names the person who caused it, and the ledger has a foreign key to
    `users`, so a context built with an invented identifier writes nothing - which is the
    schema refusing to hold an anonymous stock change.
    """
    actor_id = uuid4()
    user = UserModel.create(
        user_id=actor_id,
        first_name="Emeka",
        email=f"emeka.{actor_id.hex[:8]}@example.com",
        now=NOW,
    )
    async with database.transaction_scope() as unit_of_work:
        await user_crud.create(unit_of_work.session_handle, user)
        await unit_of_work.commit()
    return build_tenant_context(
        user_id=actor_id,
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=permission_codes_for_role(role_name),
        role_name=role_name,
    )


async def owner_context(database: Database, tenant_id: UUID) -> TenantContext:
    """An OWNER context: every tenant permission, and an actor the ledger can reference."""
    return await context_for(database, tenant_id, "OWNER")


async def stock_level(database: Database, tenant_id: UUID, product_id: UUID) -> Decimal:
    async with database.transaction_scope() as unit_of_work:
        inventory = await inventory_crud.get_for_product(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=product_id
        )
    return Decimal("0.000") if inventory is None else inventory.quantity_on_hand


async def movement_count(database: Database, tenant_id: UUID, product_id: UUID) -> int:
    async with database.transaction_scope() as unit_of_work:
        return await inventory_movement_crud.count_for_product(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=product_id
        )


# ---------------------------------------------------------------------------
# Receiving
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_receiving_stock_records_a_movement_and_moves_the_projection(
    database: Database, service: InventoryService, tenant_id: UUID, product_id: UUID
) -> None:
    owner = await owner_context(database, tenant_id)

    change = await service.receive_stock(owner, product_id=product_id, quantity=Decimal("50.000"))

    assert change.movement.movement_type is MovementType.STOCK_RECEIVED
    assert change.movement.quantity_before == Decimal("0.000")
    assert change.movement.quantity_after == Decimal("50.000")
    assert change.inventory.quantity_on_hand == Decimal("50.000")
    assert change.inventory.version == 2
    assert await movement_count(database, tenant_id, product_id) == 1


@pytest.mark.integration
async def test_receiving_twice_accumulates(
    database: Database, service: InventoryService, tenant_id: UUID, product_id: UUID
) -> None:
    owner = await owner_context(database, tenant_id)

    await service.receive_stock(owner, product_id=product_id, quantity=Decimal("50.000"))
    second = await service.receive_stock(owner, product_id=product_id, quantity=Decimal("25.500"))

    assert second.movement.quantity_before == Decimal("50.000")
    assert second.inventory.quantity_on_hand == Decimal("75.500")
    assert await movement_count(database, tenant_id, product_id) == 2


@pytest.mark.integration
@pytest.mark.parametrize("quantity", [Decimal("0.000"), Decimal("-5.000")])
async def test_a_receipt_must_be_for_a_positive_quantity(
    database: Database,
    service: InventoryService,
    tenant_id: UUID,
    product_id: UUID,
    quantity: Decimal,
) -> None:
    """A receipt that takes stock away is a different operation with a different name."""
    owner = await owner_context(database, tenant_id)

    with pytest.raises(InvalidInputError):
        await service.receive_stock(owner, product_id=product_id, quantity=quantity)

    assert await movement_count(database, tenant_id, product_id) == 0


@pytest.mark.integration
async def test_a_receipt_for_another_businesss_product_is_refused(
    database: Database, service: InventoryService, tenant_id: UUID
) -> None:
    other_tenant = await insert_tenant(database)
    foreign_product = await insert_product(database, other_tenant, name="Theirs")
    owner = await owner_context(database, tenant_id)

    with pytest.raises(NotFoundError):
        await service.receive_stock(owner, product_id=foreign_product, quantity=Decimal("5.000"))

    assert await movement_count(database, other_tenant, foreign_product) == 0


# ---------------------------------------------------------------------------
# Adjusting and damage
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_an_adjustment_can_go_either_way(
    database: Database, service: InventoryService, tenant_id: UUID, product_id: UUID
) -> None:
    owner = await owner_context(database, tenant_id)
    await service.receive_stock(owner, product_id=product_id, quantity=Decimal("50.000"))

    down = await service.adjust_stock(
        owner, product_id=product_id, delta=Decimal("-2.500"), reason="count came out lower"
    )
    up = await service.adjust_stock(
        owner, product_id=product_id, delta=Decimal("1.000"), reason="found a bag behind the shelf"
    )

    assert down.movement.movement_type is MovementType.ADJUSTMENT
    assert down.inventory.quantity_on_hand == Decimal("47.500")
    assert up.inventory.quantity_on_hand == Decimal("48.500")


@pytest.mark.integration
async def test_an_adjustment_requires_a_reason(
    database: Database, service: InventoryService, tenant_id: UUID, product_id: UUID
) -> None:
    owner = await owner_context(database, tenant_id)

    with pytest.raises(InvalidInputError, match="reason is required"):
        await service.adjust_stock(
            owner, product_id=product_id, delta=Decimal("-1.000"), reason="   "
        )

    assert await movement_count(database, tenant_id, product_id) == 0


@pytest.mark.integration
async def test_an_adjustment_of_nothing_is_refused(
    database: Database, service: InventoryService, tenant_id: UUID, product_id: UUID
) -> None:
    owner = await owner_context(database, tenant_id)

    with pytest.raises(InvalidInputError, match="must not be zero"):
        await service.adjust_stock(
            owner, product_id=product_id, delta=Decimal("0.000"), reason="no change"
        )


@pytest.mark.integration
async def test_damage_is_recorded_as_a_loss_with_its_reason(
    database: Database, service: InventoryService, tenant_id: UUID, product_id: UUID
) -> None:
    owner = await owner_context(database, tenant_id)
    await service.receive_stock(owner, product_id=product_id, quantity=Decimal("50.000"))

    change = await service.record_damage(
        owner,
        product_id=product_id,
        quantity=Decimal("3.000"),
        reason="torn bag",
        note="water leak in the store room",
    )

    assert change.movement.movement_type is MovementType.DAMAGE
    assert change.movement.quantity_delta == Decimal("-3.000")
    assert change.movement.note == "torn bag: water leak in the store room"
    assert change.inventory.quantity_on_hand == Decimal("47.000")


# ---------------------------------------------------------------------------
# Transfers
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_transfer_writes_two_movements_and_conserves_the_total(
    database: Database, service: InventoryService, tenant_id: UUID
) -> None:
    """Repackaging: a carton becomes units, and the total does not change."""
    carton = await insert_product(database, tenant_id, name="Rice carton")
    unit = await insert_product(database, tenant_id, name="Rice 5kg")
    owner = await owner_context(database, tenant_id)
    await service.receive_stock(owner, product_id=carton, quantity=Decimal("10.000"))

    source, destination = await service.transfer_stock(
        owner,
        source_product_id=carton,
        destination_product_id=unit,
        quantity=Decimal("4.000"),
        reason="opened cartons for retail",
    )

    assert source.quantity_on_hand == Decimal("6.000")
    assert destination.quantity_on_hand == Decimal("4.000")
    assert await movement_count(database, tenant_id, carton) == 2
    assert await movement_count(database, tenant_id, unit) == 1

    async with database.transaction_scope() as unit_of_work:
        movements = await inventory_movement_crud.list_for_product(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=carton
        )
    transfer = movements[0]
    assert transfer.movement_type is MovementType.TRANSFER
    assert transfer.reference_type == "product_transfer"
    assert transfer.reference_id == unit

    total = await stock_level(database, tenant_id, carton) + await stock_level(
        database, tenant_id, unit
    )
    assert total == Decimal("10.000"), "a transfer moves stock, it does not create it"


@pytest.mark.integration
async def test_a_transfer_to_the_same_product_is_refused(
    database: Database, service: InventoryService, tenant_id: UUID, product_id: UUID
) -> None:
    owner = await owner_context(database, tenant_id)

    with pytest.raises(InvalidInputError, match="two different products"):
        await service.transfer_stock(
            owner,
            source_product_id=product_id,
            destination_product_id=product_id,
            quantity=Decimal("1.000"),
            reason="pointless",
        )


@pytest.mark.integration
async def test_a_transfer_beyond_the_source_is_refused_when_the_policy_blocks_it(
    database: Database, service: InventoryService, tenant_id: UUID
) -> None:
    """Both movements are refused together: a transfer cannot half happen."""
    carton = await insert_product(database, tenant_id, name="Rice carton")
    unit = await insert_product(database, tenant_id, name="Rice 5kg")
    owner = await owner_context(database, tenant_id)
    await service.receive_stock(owner, product_id=carton, quantity=Decimal("2.000"))

    with pytest.raises(DomainError):
        await service.transfer_stock(
            owner,
            source_product_id=carton,
            destination_product_id=unit,
            quantity=Decimal("5.000"),
            reason="more than there is",
        )

    assert await stock_level(database, tenant_id, carton) == Decimal("2.000")
    assert await stock_level(database, tenant_id, unit) == Decimal("0.000")
    assert await movement_count(database, tenant_id, unit) == 0


# ---------------------------------------------------------------------------
# The tenant's policy
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_default_policy_refuses_a_movement_that_would_overdraw(
    database: Database, service: InventoryService, tenant_id: UUID, product_id: UUID
) -> None:
    owner = await owner_context(database, tenant_id)
    await service.receive_stock(owner, product_id=product_id, quantity=Decimal("2.000"))

    with pytest.raises(DomainError) as captured:
        await service.adjust_stock(
            owner, product_id=product_id, delta=Decimal("-5.000"), reason="sold more than we had"
        )

    assert "does not allow stock to go negative" in (captured.value.context.detail or "")
    assert await stock_level(database, tenant_id, product_id) == Decimal("2.000")
    assert await movement_count(database, tenant_id, product_id) == 1, (
        "a refused movement leaves no trace in the ledger"
    )


@pytest.mark.integration
async def test_a_business_may_allow_an_overdraw_with_a_warning(
    database: Database, service: InventoryService
) -> None:
    tenant_id = await insert_tenant(database, policy=NegativeStockPolicy.ALLOW_WITH_WARNING)
    product_id = await insert_product(database, tenant_id)
    owner = await owner_context(database, tenant_id)
    await service.receive_stock(owner, product_id=product_id, quantity=Decimal("2.000"))

    change = await service.record_damage(
        owner, product_id=product_id, quantity=Decimal("5.000"), reason="flood"
    )

    assert change.is_overdraw is True
    assert change.inventory.quantity_on_hand == Decimal("-3.000")
    assert change.inventory.is_overdrawn() is True
    assert await movement_count(database, tenant_id, product_id) == 2


@pytest.mark.integration
async def test_a_business_may_allow_an_overdraw_silently(
    database: Database, service: InventoryService
) -> None:
    tenant_id = await insert_tenant(database, policy=NegativeStockPolicy.ALLOW_NEGATIVE_STOCK)
    product_id = await insert_product(database, tenant_id)
    owner = await owner_context(database, tenant_id)

    change = await service.adjust_stock(
        owner, product_id=product_id, delta=Decimal("-1.000"), reason="stock take"
    )

    assert change.is_overdraw is True
    assert change.inventory.quantity_on_hand == Decimal("-1.000")


@pytest.mark.integration
async def test_a_policy_change_applies_to_the_next_movement(
    database: Database, service: InventoryService, tenant_id: UUID, product_id: UUID
) -> None:
    """The policy is read per movement, so a business can change its mind."""
    owner = await owner_context(database, tenant_id)
    await service.receive_stock(owner, product_id=product_id, quantity=Decimal("1.000"))

    async with database.transaction_scope() as unit_of_work:
        tenant = await tenant_crud.require_by_id(unit_of_work.session_handle, tenant_id)
        await tenant_crud.update(
            unit_of_work.session_handle,
            tenant.with_negative_stock_policy(
                policy=NegativeStockPolicy.ALLOW_NEGATIVE_STOCK, at=NOW
            ),
        )
        await unit_of_work.commit()

    change = await service.adjust_stock(
        owner, product_id=product_id, delta=Decimal("-4.000"), reason="sold ahead of delivery"
    )

    assert change.inventory.quantity_on_hand == Decimal("-3.000")


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_an_uncounted_product_reads_as_zero_rather_than_missing(
    database: Database, service: InventoryService, tenant_id: UUID, product_id: UUID
) -> None:
    owner = await owner_context(database, tenant_id)

    level = await service.get_inventory_for_product(owner, product_id=product_id)

    assert level.inventory.quantity_on_hand == Decimal("0.000")
    assert level.inventory.is_out_of_stock() is True
    assert level.product.id == product_id


@pytest.mark.integration
async def test_the_stock_screen_lists_every_product_once(
    database: Database, service: InventoryService, tenant_id: UUID
) -> None:
    await insert_product(database, tenant_id, name="Rice 50kg")
    counted = await insert_product(database, tenant_id, name="Beans 50kg")
    owner = await owner_context(database, tenant_id)
    await service.receive_stock(owner, product_id=counted, quantity=Decimal("7.000"))

    levels = await service.list_inventory(owner)

    assert [level.product.name for level in levels] == ["Beans 50kg", "Rice 50kg"]
    assert {level.product.name: level.inventory.quantity_on_hand for level in levels} == {
        "Beans 50kg": Decimal("7.000"),
        "Rice 50kg": Decimal("0.000"),
    }


@pytest.mark.integration
async def test_history_can_be_read_for_one_product_or_the_whole_business(
    database: Database, service: InventoryService, tenant_id: UUID
) -> None:
    first = await insert_product(database, tenant_id, name="Rice 50kg")
    second = await insert_product(database, tenant_id, name="Beans 50kg")
    owner = await owner_context(database, tenant_id)
    await service.receive_stock(owner, product_id=first, quantity=Decimal("1.000"))
    await service.receive_stock(owner, product_id=second, quantity=Decimal("2.000"))

    one_product = await service.list_movements(owner, product_id=first)
    everything = await service.list_movements(owner)

    assert len(one_product) == 1
    assert one_product[0].product_id == first
    assert len(everything) == 2


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_two_simultaneous_sales_produce_two_movements_and_the_right_total(
    database: Database, tenant_id: UUID, product_id: UUID
) -> None:
    """The property the row lock exists for.

    Worker A sells three and worker B sells four at the same time. A read-modify-write
    without the lock loses one of them: both read the same quantity, both write, and the
    projection ends up reflecting one sale while the ledger holds both. Real concurrent
    transactions against real PostgreSQL are the only way to show that it does not.
    """
    owner = await owner_context(database, tenant_id)
    service = InventoryService(unit_of_work_factory=database.unit_of_work_factory())
    await service.receive_stock(owner, product_id=product_id, quantity=Decimal("10.000"))

    results = await asyncio.gather(
        service.adjust_stock(
            owner, product_id=product_id, delta=Decimal("-3.000"), reason="offline sale A"
        ),
        service.adjust_stock(
            owner, product_id=product_id, delta=Decimal("-4.000"), reason="offline sale B"
        ),
        return_exceptions=True,
    )

    failures = [result for result in results if isinstance(result, BaseException)]
    assert not failures, f"a concurrent sale failed: {failures}"

    assert await stock_level(database, tenant_id, product_id) == Decimal("3.000")
    assert await movement_count(database, tenant_id, product_id) == 3

    async with database.transaction_scope() as unit_of_work:
        movements = await inventory_movement_crud.list_for_product(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=product_id
        )
    deltas = sorted(
        movement.quantity_delta
        for movement in movements
        if movement.movement_type is MovementType.ADJUSTMENT
    )
    assert deltas == [Decimal("-4.000"), Decimal("-3.000")]

    # The movements form one chain from the empty shelf to the current total. Walked by
    # value rather than by timestamp, because two concurrent writes compute their
    # timestamps before the lock serializes them: the ledger's correctness is that the
    # quantities connect, not that the clock agrees with the lock.
    chain = {movement.quantity_before: movement.quantity_after for movement in movements}
    assert len(chain) == len(movements), "two movements left the same quantity"

    current = Decimal("0.000")
    steps = 0
    while current in chain:
        current = chain[current]
        steps += 1

    assert steps == len(movements), "every movement belongs to the chain"
    assert current == Decimal("3.000"), "the chain ends at what is on the shelf"


@pytest.mark.integration
async def test_two_simultaneous_overdraws_are_both_refused_when_the_policy_blocks(
    database: Database, tenant_id: UUID, product_id: UUID
) -> None:
    """With one item left, two sales of two must leave the stock untouched, not negative."""
    owner = await owner_context(database, tenant_id)
    service = InventoryService(unit_of_work_factory=database.unit_of_work_factory())
    await service.receive_stock(owner, product_id=product_id, quantity=Decimal("1.000"))

    results = await asyncio.gather(
        service.adjust_stock(
            owner, product_id=product_id, delta=Decimal("-2.000"), reason="sale A"
        ),
        service.adjust_stock(
            owner, product_id=product_id, delta=Decimal("-2.000"), reason="sale B"
        ),
        return_exceptions=True,
    )

    refused = [result for result in results if isinstance(result, DomainError)]
    assert len(refused) == 2, "both sales asked for stock that is not there"
    assert await stock_level(database, tenant_id, product_id) == Decimal("1.000")
    assert await movement_count(database, tenant_id, product_id) == 1


@pytest.mark.integration
async def test_the_ledger_reconstructs_the_projection_after_concurrent_writes(
    database: Database, tenant_id: UUID, product_id: UUID
) -> None:
    """The invariant test: a quantity cannot change without a movement, and the sum agrees."""
    owner = await owner_context(database, tenant_id)
    service = InventoryService(unit_of_work_factory=database.unit_of_work_factory())
    await service.receive_stock(owner, product_id=product_id, quantity=Decimal("100.000"))

    await asyncio.gather(
        *[
            service.adjust_stock(
                owner,
                product_id=product_id,
                delta=Decimal("-1.000"),
                reason=f"concurrent sale {index}",
            )
            for index in range(5)
        ]
    )

    async with database.transaction_scope() as unit_of_work:
        movements = await inventory_movement_crud.list_for_product(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=product_id, limit=100
        )
    total = sum((movement.quantity_delta for movement in movements), Decimal("0.000"))

    assert total == await stock_level(database, tenant_id, product_id)
    assert total == Decimal("95.000")
    assert len(movements) == 6


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_salesperson_may_read_stock_and_may_not_change_it(
    database: Database, service: InventoryService, tenant_id: UUID, product_id: UUID
) -> None:
    owner = await owner_context(database, tenant_id)
    await service.receive_stock(owner, product_id=product_id, quantity=Decimal("5.000"))
    sales = await context_for(database, tenant_id, "SALES")

    readable = await service.get_inventory_for_product(sales, product_id=product_id)

    assert readable.inventory.quantity_on_hand == Decimal("5.000")
    with pytest.raises(AuthorizationError):
        await service.receive_stock(sales, product_id=product_id, quantity=Decimal("1.000"))
    with pytest.raises(AuthorizationError):
        await service.adjust_stock(
            sales, product_id=product_id, delta=Decimal("1.000"), reason="no permission"
        )
    assert await movement_count(database, tenant_id, product_id) == 1


@pytest.mark.integration
async def test_an_inventory_worker_may_count_stock(
    database: Database, service: InventoryService, tenant_id: UUID, product_id: UUID
) -> None:
    """INVENTORY holds stock_in and adjust, which is what counting stock requires.

    The contrast with SALES is the point: the person who counts and the person who sells
    are different people, and the ledger's actor column is what makes that distinction
    useful afterwards.
    """
    worker = await context_for(database, tenant_id, "INVENTORY")

    received = await service.receive_stock(worker, product_id=product_id, quantity=Decimal("5.000"))
    adjusted = await service.adjust_stock(
        worker, product_id=product_id, delta=Decimal("-1.000"), reason="broken bag"
    )

    assert received.movement.actor_id == worker.user_id
    assert adjusted.inventory.quantity_on_hand == Decimal("4.000")
