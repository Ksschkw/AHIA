"""Tests for the offline synchronisation persistence.

Four properties are tested here, and three of them only the database can prove.

The sequence is the server's
    An insert that tries to choose its own `change_sequence` is refused by the identity column.
    That is what makes the order total: no writer can place its change in another device's feed.
    The test uses raw SQL, because the application never tries.

A device has one cursor
    `UNIQUE(tenant_id, device_id)` makes two positions in the feed for one phone impossible. The
    two writers would be two concurrent requests from that phone, which is exactly the race a
    service-level check cannot close.

An operation is recorded once, by the client's identifier
    The second arrival of the same operation gets the first one's answer instead of a second row,
    and two businesses may use the same identifier because their phones have never met.

The feed reads forward
    "Everything after this sequence, oldest first" is the only read the protocol makes, and a page
    in the wrong order would make a client's cursor meaningless.
"""

from __future__ import annotations

import ast
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.errors import EntityInvariantError
from ahia.crud import (
    device_crud,
    sync_change_crud,
    sync_cursor_crud,
    sync_operation_crud,
    tenant_crud,
    user_crud,
)
from ahia.models.entities.device_model import DeviceModel
from ahia.models.entities.sync_change_model import ChangeType, SyncChangeModel
from ahia.models.entities.sync_cursor_model import SyncCursorModel
from ahia.models.entities.sync_operation_model import (
    SyncOperationModel,
    SyncOperationStatus,
)
from ahia.models.entities.tenant_model import TenantModel
from ahia.models.entities.user_model import UserModel

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 14, 16, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)

SYNC_OPERATION_CRUD_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "ahia" / "crud" / "sync_operation_crud.py"
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
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(sync_connection, checkfirst=True)
        )
        await connection.execute(
            text(
                "TRUNCATE TABLE sync_changes, sync_cursors, sync_operations, devices, "
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


@pytest.fixture
async def tenant_id(database: Database) -> UUID:
    return await insert_tenant(database)


async def register_device(database: Database, *, tenant_id: UUID) -> UUID:
    """Register a real device: a cursor is a position belonging to a device that exists."""
    identifier = uuid4()
    owner_id = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await user_crud.create(
            unit_of_work.session_handle,
            UserModel.create(
                user_id=owner_id,
                first_name="Emeka",
                email=f"emeka.{owner_id.hex[:8]}@example.com",
                now=NOW,
            ),
        )
        await device_crud.create(
            unit_of_work.session_handle,
            DeviceModel.register(
                device_id=identifier,
                tenant_id=tenant_id,
                user_id=owner_id,
                device_identifier=f"device-{identifier.hex[:8]}",
                platform="android",
                now=NOW,
            ),
        )
        await unit_of_work.commit()
    return identifier


async def record_change(
    database: Database,
    *,
    tenant_id: UUID,
    entity_type: str = "product",
    entity_id: UUID | None = None,
    change_type: ChangeType = ChangeType.CREATED,
) -> SyncChangeModel:
    async with database.transaction_scope() as unit_of_work:
        stored = await sync_change_crud.record(
            unit_of_work.session_handle,
            SyncChangeModel.for_record(
                change_id=uuid4(),
                tenant_id=tenant_id,
                # The sequence is the database's; the entity validates what comes back, so the
                # caller passes a placeholder that the identity column overrides.
                change_sequence=1,
                entity_type=entity_type,
                entity_id=entity_id or uuid4(),
                change_type=change_type,
                now=NOW,
            ),
        )
        await unit_of_work.commit()
    return stored


# ---------------------------------------------------------------------------
# The change feed
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_database_assigns_the_sequence(database: Database, tenant_id: UUID) -> None:
    first = await record_change(database, tenant_id=tenant_id)
    second = await record_change(database, tenant_id=tenant_id)

    # The caller passes a placeholder of 1; what is stored is whatever the identity column
    # assigned. On a fresh database that is 1 as well, which is why the assertion is about the
    # two rows agreeing on an order rather than about a particular number.
    assert first.change_sequence >= 1
    assert second.change_sequence == first.change_sequence + 1


@pytest.mark.integration
async def test_an_insert_cannot_choose_its_own_sequence(
    database: Database, tenant_id: UUID
) -> None:
    """A device must not be able to place its change in another device's feed."""
    with pytest.raises(DBAPIError):
        async with database.transaction_scope() as unit_of_work:
            await unit_of_work.session_handle.execute(
                text(
                    "INSERT INTO sync_changes (id, tenant_id, change_sequence, entity_type, "
                    "entity_id, change_type, occurred_at) VALUES (:id, :tenant_id, 999, "
                    "'product', :entity_id, 'CREATED', :now)"
                ),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "entity_id": uuid4(),
                    "now": NOW,
                },
            )
            await unit_of_work.commit()


@pytest.mark.integration
async def test_the_feed_reads_forward_oldest_first(database: Database, tenant_id: UUID) -> None:
    for entity_type in ("product", "customer", "sale"):
        await record_change(database, tenant_id=tenant_id, entity_type=entity_type)

    async with database.transaction_scope() as unit_of_work:
        everything = await sync_change_crud.changes_after(
            unit_of_work.session_handle, tenant_id, after_sequence=0
        )
        after_first = await sync_change_crud.changes_after(
            unit_of_work.session_handle,
            tenant_id,
            after_sequence=everything[0].change_sequence,
        )
        highest = await sync_change_crud.latest_sequence(unit_of_work.session_handle, tenant_id)

    # The sequence is global, not per business, so the test asks from the first change it wrote
    # rather than assuming a business's numbering starts at one.
    assert [change.entity_type for change in everything] == ["product", "customer", "sale"]
    assert [change.entity_type for change in after_first] == ["customer", "sale"]
    assert highest == everything[-1].change_sequence


@pytest.mark.integration
async def test_a_business_with_no_changes_reports_zero(database: Database, tenant_id: UUID) -> None:
    async with database.transaction_scope() as unit_of_work:
        highest = await sync_change_crud.latest_sequence(unit_of_work.session_handle, tenant_id)

    assert highest == 0, "a new business and a new device agree without a special case"


@pytest.mark.integration
async def test_a_feed_is_scoped_to_its_business(database: Database, tenant_id: UUID) -> None:
    other_tenant = await insert_tenant(database)
    await record_change(database, tenant_id=tenant_id)

    async with database.transaction_scope() as unit_of_work:
        theirs = await sync_change_crud.changes_after(
            unit_of_work.session_handle, other_tenant, after_sequence=0
        )
        count = await sync_change_crud.count_for_tenant(unit_of_work.session_handle, other_tenant)

    assert theirs == []
    assert count == 0


@pytest.mark.integration
async def test_a_change_does_not_survive_a_transaction_that_fails(
    database: Database, tenant_id: UUID
) -> None:
    with pytest.raises(RuntimeError):
        async with database.transaction_scope() as unit_of_work:
            await sync_change_crud.record(
                unit_of_work.session_handle,
                SyncChangeModel.for_record(
                    change_id=uuid4(),
                    tenant_id=tenant_id,
                    change_sequence=1,
                    entity_type="product",
                    entity_id=uuid4(),
                    change_type=ChangeType.CREATED,
                    now=NOW,
                ),
            )
            raise RuntimeError("the write this change describes failed")

    async with database.transaction_scope() as unit_of_work:
        changes = await sync_change_crud.changes_after(
            unit_of_work.session_handle, tenant_id, after_sequence=0
        )

    assert changes == [], "a device must not be told to fetch a record that does not exist"


# ---------------------------------------------------------------------------
# Cursors
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_cursor_is_created_once_and_then_advanced(
    database: Database, tenant_id: UUID
) -> None:
    device_id = await register_device(database, tenant_id=tenant_id)

    async with database.transaction_scope() as unit_of_work:
        created = await sync_cursor_crud.save(
            unit_of_work.session_handle,
            SyncCursorModel.starting_at(
                cursor_id=uuid4(), tenant_id=tenant_id, device_id=device_id, now=NOW
            ),
        )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        await sync_cursor_crud.save(
            unit_of_work.session_handle,
            created.advanced_to(sequence=42, at=LATER),
        )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        reread = await sync_cursor_crud.get_for_device(
            unit_of_work.session_handle, tenant_id=tenant_id, device_id=device_id
        )
        listed = await sync_cursor_crud.list_for_tenant(unit_of_work.session_handle, tenant_id)

    assert reread is not None
    assert reread.last_server_sequence == 42
    assert reread.updated_at == LATER
    assert len(listed) == 1, "one row per device, advanced rather than duplicated"


@pytest.mark.integration
async def test_a_device_that_has_never_synchronized_has_no_cursor(
    database: Database, tenant_id: UUID
) -> None:
    async with database.transaction_scope() as unit_of_work:
        cursor = await sync_cursor_crud.get_for_device(
            unit_of_work.session_handle, tenant_id=tenant_id, device_id=uuid4()
        )

    assert cursor is None


@pytest.mark.integration
async def test_two_businesses_may_track_the_same_device_identifier(
    database: Database, tenant_id: UUID
) -> None:
    other_tenant = await insert_tenant(database)
    device_id = await register_device(database, tenant_id=tenant_id)

    for current_tenant in (tenant_id, other_tenant):
        async with database.transaction_scope() as unit_of_work:
            await sync_cursor_crud.save(
                unit_of_work.session_handle,
                SyncCursorModel.starting_at(
                    cursor_id=uuid4(),
                    tenant_id=current_tenant,
                    device_id=device_id,
                    now=NOW,
                ),
            )
            await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        theirs = await sync_cursor_crud.get_for_device(
            unit_of_work.session_handle, tenant_id=other_tenant, device_id=device_id
        )

    assert theirs is not None
    assert theirs.tenant_id == other_tenant


@pytest.mark.integration
async def test_a_cursor_cannot_be_moved_backwards_in_storage(
    database: Database, tenant_id: UUID
) -> None:
    device_id = await register_device(database, tenant_id=tenant_id)
    async with database.transaction_scope() as unit_of_work:
        cursor = await sync_cursor_crud.save(
            unit_of_work.session_handle,
            SyncCursorModel.starting_at(
                cursor_id=uuid4(),
                tenant_id=tenant_id,
                device_id=device_id,
                now=NOW,
                last_server_sequence=42,
            ),
        )
        await unit_of_work.commit()

    with pytest.raises(EntityInvariantError, match="cannot move backwards"):
        cursor.advanced_to(sequence=10, at=LATER)


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_an_operation_is_recorded_once_and_answered_from_there(
    database: Database, tenant_id: UUID
) -> None:
    device_id = uuid4()
    operation = SyncOperationModel.record(
        operation_id=uuid4(),
        tenant_id=tenant_id,
        operation_type="complete_sale",
        status=SyncOperationStatus.APPLIED,
        now=NOW,
        device_id=device_id,
        entity_type="sale",
        entity_id=uuid4(),
    )

    async with database.transaction_scope() as unit_of_work:
        stored, created = await sync_operation_crud.record_or_get(
            unit_of_work.session_handle, operation
        )
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        again, created_again = await sync_operation_crud.record_or_get(
            unit_of_work.session_handle, operation
        )
        await unit_of_work.commit()

    assert created is True
    assert created_again is False, "a retry is answered from the first attempt"
    assert again.id == stored.id
    assert again.entity_id == operation.entity_id


@pytest.mark.integration
async def test_two_businesses_may_use_the_same_operation_identifier(
    database: Database, tenant_id: UUID
) -> None:
    other_tenant = await insert_tenant(database)
    operation_id = uuid4()

    for current_tenant in (tenant_id, other_tenant):
        operation = SyncOperationModel.record(
            operation_id=operation_id,
            tenant_id=current_tenant,
            operation_type="record_expense",
            status=SyncOperationStatus.APPLIED,
            now=NOW,
            entity_type="expense",
            entity_id=uuid4(),
        )
        async with database.transaction_scope() as unit_of_work:
            _, created = await sync_operation_crud.record_or_get(
                unit_of_work.session_handle, operation
            )
            await unit_of_work.commit()
        assert created is True, "phones that have never met generate the same identifier"


@pytest.mark.integration
async def test_operations_can_be_read_by_device_and_by_outcome(
    database: Database, tenant_id: UUID
) -> None:
    device_id = uuid4()
    other_device = uuid4()
    for current_device, status in (
        (device_id, SyncOperationStatus.APPLIED),
        (device_id, SyncOperationStatus.REJECTED),
        (other_device, SyncOperationStatus.APPLIED),
    ):
        operation = SyncOperationModel.record(
            operation_id=uuid4(),
            tenant_id=tenant_id,
            operation_type="record_expense",
            status=status,
            now=NOW,
            device_id=current_device,
            entity_type="expense",
            entity_id=uuid4(),
        )
        async with database.transaction_scope() as unit_of_work:
            await sync_operation_crud.record_or_get(unit_of_work.session_handle, operation)
            await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        for_device = await sync_operation_crud.list_for_device(
            unit_of_work.session_handle, tenant_id=tenant_id, device_id=device_id
        )
        rejected = await sync_operation_crud.list_for_tenant(
            unit_of_work.session_handle, tenant_id, status=SyncOperationStatus.REJECTED
        )
        count = await sync_operation_crud.count_for_device(
            unit_of_work.session_handle, tenant_id=tenant_id, device_id=other_device
        )

    assert len(for_device) == 2
    assert [operation.status for operation in rejected] == [SyncOperationStatus.REJECTED]
    assert count == 1


@pytest.mark.unit
def test_operations_offer_no_way_to_change_an_answer() -> None:
    """An answer that can change is not an answer a retrying device can rely on."""
    tree = ast.parse(SYNC_OPERATION_CRUD_PATH.read_text(encoding="utf-8"))
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    forbidden = {
        name
        for name in defined
        if name in {"update", "delete", "remove", "edit", "amend", "purge"}
        or name.startswith(("update_", "delete_"))
    }
    assert not forbidden, f"the operation log gained a mutating function: {sorted(forbidden)}"
