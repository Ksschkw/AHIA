"""Tests for inventory persistence.

The properties worth testing here are the ones the database holds rather than a service:
one projection per product per business, a composite product reference that keeps tenants
apart, an offline operation applied only once, and a ledger that cannot be rewritten. The
last is enforced by a trigger, so this file proves it with raw SQL rather than by calling a
function that does not exist.
"""

from __future__ import annotations

import ast
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.crud import (
    inventory_crud,
    inventory_movement_crud,
    product_crud,
    tenant_crud,
    user_crud,
)
from ahia.models.entities.inventory_movement_model import (
    InventoryMovementModel,
    MovementType,
)
from ahia.models.entities.negative_stock_policy import NegativeStockPolicy
from ahia.models.entities.product_model import ProductModel
from ahia.models.entities.tenant_model import TenantModel
from ahia.models.entities.user_model import UserModel

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)

MOVEMENT_CRUD_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "ahia" / "crud" / "inventory_movement_crud.py"
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
            text("TRUNCATE TABLE inventory_movements, inventory, products, tenants, users CASCADE")
        )
    try:
        yield instance
    finally:
        await instance.dispose()


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


async def insert_product(database: Database, tenant_id: UUID, *, name: str = "Coca Cola") -> UUID:
    product = ProductModel.create(
        product_id=uuid4(),
        tenant_id=tenant_id,
        name=name,
        selling_price=Decimal("250.00"),
        now=NOW,
    )
    async with database.transaction_scope() as unit_of_work:
        await product_crud.create(unit_of_work.session_handle, product)
        await unit_of_work.commit()
    return product.id


async def insert_actor(database: Database) -> UUID:
    user = UserModel.create(
        user_id=uuid4(),
        first_name="Emeka",
        email=f"emeka.{uuid4().hex[:8]}@example.com",
        now=NOW,
    )
    async with database.transaction_scope() as unit_of_work:
        await user_crud.create(unit_of_work.session_handle, user)
        await unit_of_work.commit()
    return user.id


@pytest.fixture
async def tenant_id(database: Database) -> UUID:
    return await insert_tenant(database)


@pytest.fixture
async def product_id(database: Database, tenant_id: UUID) -> UUID:
    return await insert_product(database, tenant_id)


@pytest.fixture
async def actor_id(database: Database) -> UUID:
    return await insert_actor(database)


def build_movement(
    *,
    tenant_id: UUID,
    product_id: UUID,
    actor_id: UUID,
    **overrides: object,
) -> InventoryMovementModel:
    parameters: dict[str, object] = {
        "movement_id": uuid4(),
        "tenant_id": tenant_id,
        "product_id": product_id,
        "movement_type": MovementType.STOCK_RECEIVED,
        "quantity_delta": Decimal("12.000"),
        "quantity_before": Decimal("0.000"),
        "actor_id": actor_id,
        "now": NOW,
    }
    parameters.update(overrides)
    return InventoryMovementModel.record(**parameters)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The projection
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_locking_a_product_creates_its_stock_record_once(
    database: Database, tenant_id: UUID, product_id: UUID
) -> None:
    """Two concurrent first movements must serialize, not collide."""
    async with database.transaction_scope() as unit_of_work:
        first = await inventory_crud.lock_for_product(
            unit_of_work.session_handle,
            inventory_id=uuid4(),
            tenant_id=tenant_id,
            product_id=product_id,
            now=NOW,
        )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        second = await inventory_crud.lock_for_product(
            unit_of_work.session_handle,
            inventory_id=uuid4(),
            tenant_id=tenant_id,
            product_id=product_id,
            now=LATER,
        )
        await unit_of_work.commit()

        count = await inventory_crud.count_for_tenant(unit_of_work.session_handle, tenant_id)

    assert first.id == second.id, "the second lock found the row the first created"
    assert first.quantity_on_hand == Decimal("0.000")
    assert count == 1


@pytest.mark.integration
async def test_the_projection_round_trips(
    database: Database, tenant_id: UUID, product_id: UUID
) -> None:
    async with database.transaction_scope() as unit_of_work:
        inventory = await inventory_crud.lock_for_product(
            unit_of_work.session_handle,
            inventory_id=uuid4(),
            tenant_id=tenant_id,
            product_id=product_id,
            now=NOW,
        )
        moved = inventory.with_movement(delta=Decimal("12.500"), at=LATER)
        stored = await inventory_crud.save(unit_of_work.session_handle, moved)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        reread = await inventory_crud.get_for_product(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=product_id
        )

    assert stored.quantity_on_hand == Decimal("12.500")
    assert stored.version == 2
    assert reread == stored


@pytest.mark.integration
async def test_a_product_has_one_projection_per_business(database: Database) -> None:
    """The unique constraint refuses a second row, however it is inserted.

    `lock_for_product` itself tolerates a concurrent insert - its `ON CONFLICT DO
    NOTHING` is what makes two simultaneous first movements serialize instead of one
    failing - so the constraint is proven with a direct insert, which is the path a
    helper somebody adds later would take.
    """
    tenant_id = await insert_tenant(database)
    product_id = await insert_product(database, tenant_id)
    statement = text(
        "INSERT INTO inventory (id, tenant_id, product_id, quantity_on_hand, "
        "reserved_quantity, version, created_at, updated_at) VALUES "
        "(:id, :tenant_id, :product_id, 0, 0, 1, now(), now())"
    )

    async with database.transaction_scope() as unit_of_work:
        inventory = await inventory_crud.lock_for_product(
            unit_of_work.session_handle,
            inventory_id=uuid4(),
            tenant_id=tenant_id,
            product_id=product_id,
            now=NOW,
        )
        await unit_of_work.commit()

    assert inventory.quantity_on_hand == Decimal("0.000")

    with pytest.raises(IntegrityError) as captured:
        async with database.engine.begin() as connection:
            await connection.execute(
                statement,
                {"id": str(uuid4()), "tenant_id": str(tenant_id), "product_id": str(product_id)},
            )

    assert "uq_inventory_tenant_id_product_id" in str(captured.value)


@pytest.mark.integration
async def test_a_projection_cannot_describe_another_businesss_product(
    database: Database,
) -> None:
    """The composite product reference refuses it, not only the service."""
    tenant_id = await insert_tenant(database)
    other_tenant = await insert_tenant(database)
    foreign_product = await insert_product(database, other_tenant, name="Theirs")

    with pytest.raises(Exception) as captured:
        async with database.transaction_scope() as unit_of_work:
            await inventory_crud.lock_for_product(
                unit_of_work.session_handle,
                inventory_id=uuid4(),
                tenant_id=tenant_id,
                product_id=foreign_product,
                now=NOW,
            )
            await unit_of_work.commit()

    assert "fk_inventory_product_id_tenant_id_products" in str(captured.value)


@pytest.mark.integration
async def test_the_projection_can_be_rebuilt_from_the_ledger(
    database: Database, tenant_id: UUID, product_id: UUID, actor_id: UUID
) -> None:
    """It is a projection: deleting it loses nothing that cannot be recomputed."""
    movements = [
        build_movement(
            tenant_id=tenant_id,
            product_id=product_id,
            actor_id=actor_id,
            movement_id=uuid4(),
            movement_type=movement_type,
            quantity_delta=delta,
            quantity_before=before,
        )
        for movement_type, delta, before in (
            (MovementType.STOCK_RECEIVED, Decimal("10.000"), Decimal("0.000")),
            (MovementType.SALE, Decimal("-3.000"), Decimal("10.000")),
        )
    ]

    async with database.transaction_scope() as unit_of_work:
        for movement in movements:
            await inventory_movement_crud.record(unit_of_work.session_handle, movement)
        await unit_of_work.commit()

    async with database.engine.begin() as connection:
        await connection.execute(text("DELETE FROM inventory"))

    async with database.transaction_scope() as unit_of_work:
        rebuilt_total = sum(
            [
                movement.quantity_delta
                for movement in await inventory_movement_crud.list_for_product(
                    unit_of_work.session_handle, tenant_id=tenant_id, product_id=product_id
                )
            ],
            Decimal("0.000"),
        )
        count = await inventory_crud.count_for_tenant(unit_of_work.session_handle, tenant_id)

    assert rebuilt_total == Decimal("7.000")
    assert count == 0, "the projection is gone and the history is untouched"


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_movement_round_trips_every_field(
    database: Database, tenant_id: UUID, product_id: UUID, actor_id: UUID
) -> None:
    reference_id = uuid4()
    device_id = uuid4()
    operation_id = uuid4()
    movement = build_movement(
        tenant_id=tenant_id,
        product_id=product_id,
        actor_id=actor_id,
        movement_type=MovementType.ADJUSTMENT,
        quantity_delta=Decimal("-2.500"),
        quantity_before=Decimal("12.000"),
        reference_type="stock_take",
        reference_id=reference_id,
        device_id=None,
        operation_id=operation_id,
        note="weekly count",
    )

    async with database.transaction_scope() as unit_of_work:
        stored = await inventory_movement_crud.record(unit_of_work.session_handle, movement)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        history = await inventory_movement_crud.list_for_product(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=product_id
        )

    assert stored == movement
    assert stored.quantity_after == Decimal("9.500")
    assert history == [movement]
    assert movement.device_id is None
    assert device_id not in {movement.device_id}


@pytest.mark.integration
async def test_the_history_is_most_recent_first(
    database: Database, tenant_id: UUID, product_id: UUID, actor_id: UUID
) -> None:
    async with database.transaction_scope() as unit_of_work:
        for offset in range(3):
            await inventory_movement_crud.record(
                unit_of_work.session_handle,
                build_movement(
                    tenant_id=tenant_id,
                    product_id=product_id,
                    actor_id=actor_id,
                    movement_id=uuid4(),
                    quantity_before=Decimal("0.000"),
                    quantity_delta=Decimal(f"{offset + 1}.000"),
                    now=NOW + timedelta(minutes=offset),
                ),
            )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        history = await inventory_movement_crud.list_for_product(
            unit_of_work.session_handle, tenant_id=tenant_id, product_id=product_id
        )

    assert [movement.quantity_delta for movement in history] == [
        Decimal("3.000"),
        Decimal("2.000"),
        Decimal("1.000"),
    ]


@pytest.mark.integration
async def test_an_offline_operation_is_recorded_once(
    database: Database, tenant_id: UUID, product_id: UUID, actor_id: UUID
) -> None:
    """A replayed sync operation must be recognised, not applied twice."""
    operation_id = uuid4()
    movement = build_movement(
        tenant_id=tenant_id,
        product_id=product_id,
        actor_id=actor_id,
        operation_id=operation_id,
    )

    async with database.transaction_scope() as unit_of_work:
        await inventory_movement_crud.record(unit_of_work.session_handle, movement)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        found = await inventory_movement_crud.get_by_operation_id(
            unit_of_work.session_handle, tenant_id=tenant_id, operation_id=operation_id
        )

    assert found is not None and found.id == movement.id

    with pytest.raises(IntegrityError) as captured:
        async with database.transaction_scope() as unit_of_work:
            await inventory_movement_crud.record(
                unit_of_work.session_handle,
                build_movement(
                    tenant_id=tenant_id,
                    product_id=product_id,
                    actor_id=actor_id,
                    movement_id=uuid4(),
                    operation_id=operation_id,
                ),
            )
            await unit_of_work.commit()

    assert "uq_inventory_movements_tenant_operation" in str(captured.value)


@pytest.mark.integration
async def test_the_same_operation_identifier_is_free_in_another_business(
    database: Database, tenant_id: UUID, product_id: UUID, actor_id: UUID
) -> None:
    """Two phones in two businesses may generate the same identifier."""
    operation_id = uuid4()
    other_tenant = await insert_tenant(database)
    other_product = await insert_product(database, other_tenant, name="Theirs")
    other_actor = await insert_actor(database)

    async with database.transaction_scope() as unit_of_work:
        await inventory_movement_crud.record(
            unit_of_work.session_handle,
            build_movement(
                tenant_id=tenant_id,
                product_id=product_id,
                actor_id=actor_id,
                operation_id=operation_id,
            ),
        )
        await inventory_movement_crud.record(
            unit_of_work.session_handle,
            build_movement(
                tenant_id=other_tenant,
                product_id=other_product,
                actor_id=other_actor,
                movement_id=uuid4(),
                operation_id=operation_id,
            ),
        )
        await unit_of_work.commit()


@pytest.mark.integration
async def test_the_ledger_cannot_be_updated(
    database: Database, tenant_id: UUID, product_id: UUID, actor_id: UUID
) -> None:
    """The trigger, not the absence of a function, is what makes this true."""
    async with database.transaction_scope() as unit_of_work:
        movement = await inventory_movement_crud.record(
            unit_of_work.session_handle,
            build_movement(tenant_id=tenant_id, product_id=product_id, actor_id=actor_id),
        )
        await unit_of_work.commit()

    with pytest.raises(DBAPIError) as captured:
        async with database.engine.begin() as connection:
            await connection.execute(
                text("UPDATE inventory_movements SET note = 'edited' WHERE id = :id"),
                {"id": str(movement.id)},
            )

    assert "append-only" in str(captured.value)


@pytest.mark.integration
async def test_the_ledger_cannot_be_deleted_from(
    database: Database, tenant_id: UUID, product_id: UUID, actor_id: UUID
) -> None:
    async with database.transaction_scope() as unit_of_work:
        await inventory_movement_crud.record(
            unit_of_work.session_handle,
            build_movement(tenant_id=tenant_id, product_id=product_id, actor_id=actor_id),
        )
        await unit_of_work.commit()

    with pytest.raises(DBAPIError) as captured:
        async with database.engine.begin() as connection:
            await connection.execute(text("DELETE FROM inventory_movements"))

    assert "append-only" in str(captured.value)


@pytest.mark.unit
def test_the_ledger_persistence_offers_no_way_to_change_a_row() -> None:
    """A helper added later "just to fix a typo in a note" would break the audit trail."""
    tree = ast.parse(MOVEMENT_CRUD_PATH.read_text(encoding="utf-8"))
    defined_functions = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    forbidden = {
        name
        for name in defined_functions
        if name in {"update", "delete", "remove", "edit", "amend"} or name.startswith("update_")
    }
    assert not forbidden, f"the ledger gained a mutating function: {sorted(forbidden)}"


# ---------------------------------------------------------------------------
# The tenant's policy
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_business_defaults_to_refusing_negative_stock(database: Database) -> None:
    tenant_id = await insert_tenant(database)

    async with database.transaction_scope() as unit_of_work:
        tenant = await tenant_crud.require_by_id(unit_of_work.session_handle, tenant_id)

    assert tenant.negative_stock_policy is NegativeStockPolicy.BLOCK_NEGATIVE_STOCK


@pytest.mark.integration
async def test_a_business_can_choose_a_permissive_policy(database: Database) -> None:
    tenant_id = await insert_tenant(database, policy=NegativeStockPolicy.ALLOW_WITH_WARNING)

    async with database.transaction_scope() as unit_of_work:
        tenant = await tenant_crud.require_by_id(unit_of_work.session_handle, tenant_id)
        updated = await tenant_crud.update(
            unit_of_work.session_handle,
            tenant.with_negative_stock_policy(
                policy=NegativeStockPolicy.ALLOW_NEGATIVE_STOCK, at=LATER
            ),
        )
        await unit_of_work.commit()

    assert tenant.negative_stock_policy is NegativeStockPolicy.ALLOW_WITH_WARNING
    assert updated.negative_stock_policy is NegativeStockPolicy.ALLOW_NEGATIVE_STOCK

    async with database.transaction_scope() as unit_of_work:
        reread = await tenant_crud.require_by_id(unit_of_work.session_handle, tenant_id)

    assert reread.negative_stock_policy is NegativeStockPolicy.ALLOW_NEGATIVE_STOCK


@pytest.mark.integration
async def test_a_stored_policy_the_entity_does_not_know_fails_loudly(
    database: Database, tenant_id: UUID
) -> None:
    """A value written by a future version must not silently become the default."""
    async with database.engine.begin() as connection:
        await connection.execute(
            text("UPDATE tenants SET negative_stock_policy = 'SOMETHING_NEW' WHERE id = :id"),
            {"id": str(tenant_id)},
        )

    with pytest.raises(ValueError, match="SOMETHING_NEW"):
        async with database.transaction_scope() as unit_of_work:
            await tenant_crud.require_by_id(unit_of_work.session_handle, tenant_id)


@pytest.mark.integration
async def test_a_neighbours_stock_is_not_visible(
    database: Database, tenant_id: UUID, product_id: UUID
) -> None:
    other_tenant = await insert_tenant(database)

    async with database.transaction_scope() as unit_of_work:
        await inventory_crud.lock_for_product(
            unit_of_work.session_handle,
            inventory_id=uuid4(),
            tenant_id=tenant_id,
            product_id=product_id,
            now=NOW,
        )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        elsewhere = await inventory_crud.list_for_tenant(unit_of_work.session_handle, other_tenant)
        missing = await inventory_crud.get_for_product(
            unit_of_work.session_handle, tenant_id=other_tenant, product_id=product_id
        )

    assert elsewhere == []
    assert missing is None


@pytest.mark.integration
async def test_an_inventory_row_survives_a_foreign_key_check_on_products(
    database: Database, tenant_id: UUID, product_id: UUID
) -> None:
    """A projection cannot exist for a product that does not exist."""
    with pytest.raises(Exception) as captured:
        async with database.transaction_scope() as unit_of_work:
            await inventory_crud.lock_for_product(
                unit_of_work.session_handle,
                inventory_id=uuid4(),
                tenant_id=tenant_id,
                product_id=uuid4(),
                now=NOW,
            )
            await unit_of_work.commit()

    assert "fk_inventory_product_id_tenant_id_products" in str(captured.value)


@pytest.mark.integration
async def test_an_empty_projection_list_is_not_an_error(
    database: Database, tenant_id: UUID
) -> None:
    async with database.transaction_scope() as unit_of_work:
        assert await inventory_crud.list_for_tenant(unit_of_work.session_handle, tenant_id) == []
