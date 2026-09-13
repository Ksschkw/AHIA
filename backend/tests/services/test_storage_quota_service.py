"""Tests for tenant storage quota accounting.

These are integration tests: the whole point of the design is behaviour under a
real row lock in a real transaction. A mocked database would let every one of
them pass while the accounting over-allocated in production.

The concurrency test is the important one. Two uploads race for the last free
bytes; exactly one may win, and the loser must be told, not silently accepted.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Database
from ahia.core.errors import AuthorizationError, StorageQuotaExceededError
from ahia.core.tenant_context import build_tenant_context
from ahia.crud import tenant_storage_usage_crud
from ahia.crud.tenant_storage_usage_crud import TenantStorageUsageRecord
from ahia.models.entities.tenant_storage_usage_model import TenantStorageUsage
from ahia.services.storage_quota_service import StorageQuotaService

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
MEBIBYTE = 1024 * 1024


def build_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env=AppEnvironment.TEST,
        database_url=os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL),
        jwt_secret="test-signing-secret-value-0000000001",
        refresh_token_pepper="test-refresh-pepper-value-00000000011",
        storage_provider=StorageProviderName.R2,
        r2_endpoint="https://account.r2.cloudflarestorage.com",
        r2_access_key_id="r2-access-key",
        r2_secret_access_key="r2-secret-key",
        r2_bucket="ahia-test",
    )


@pytest.fixture
async def database() -> Any:
    instance = Database(build_settings())
    async with instance.engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: TenantStorageUsageRecord.__table__.create(
                sync_connection, checkfirst=True
            )
        )
    try:
        yield instance
    finally:
        async with instance.engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: TenantStorageUsageRecord.__table__.drop(
                    sync_connection, checkfirst=True
                )
            )
        await instance.dispose()


@pytest.fixture
def tenant_id() -> UUID:
    return uuid4()


@pytest.fixture
def tenant_context(tenant_id: UUID) -> Any:
    return build_tenant_context(
        user_id=uuid4(),
        tenant_id=tenant_id,
        membership_id=uuid4(),
        role_id=uuid4(),
        permission_codes=frozenset({"storefront.manage", "products.update"}),
        role_name="OWNER",
    )


@pytest.fixture
def service(database: Database, tenant_id: UUID) -> StorageQuotaService:
    return StorageQuotaService(
        unit_of_work_factory=database.unit_of_work_factory(),
        quota_bytes=10 * MEBIBYTE,
    )


# ---------------------------------------------------------------------------
# The entity's arithmetic
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_entity_arithmetic_keeps_used_and_reserved_separate() -> None:
    now = datetime.now(UTC)
    usage = TenantStorageUsage.empty(uuid4(), now=now)

    reserved = usage.with_reservation(1_000, at=now)
    committed = reserved.with_commit(1_000, at=now)
    released = reserved.with_release(1_000, at=now)

    assert reserved.reserved_bytes == 1_000
    assert reserved.committed_bytes == 0
    assert committed.reserved_bytes == 0
    assert committed.committed_bytes == 1_000
    assert released.reserved_bytes == 0
    assert released.committed_bytes == 0


@pytest.mark.unit
def test_entity_refuses_a_commit_without_a_reservation() -> None:
    now = datetime.now(UTC)
    usage = TenantStorageUsage.empty(uuid4(), now=now)

    with pytest.raises(Exception, match="exceeds the reserved"):
        usage.with_commit(1_000, at=now)


@pytest.mark.unit
def test_remaining_never_goes_negative_when_a_quota_is_lowered() -> None:
    now = datetime.now(UTC)
    usage = TenantStorageUsage(
        tenant_id=uuid4(),
        used_bytes=5_000,
        reserved_bytes=0,
        version=3,
        updated_at=now,
    )

    assert usage.remaining_bytes(quota_bytes=1_000) == 0
    assert usage.can_accept(1, quota_bytes=1_000) is False


@pytest.mark.unit
def test_negative_totals_are_rejected_at_construction() -> None:
    now = datetime.now(UTC)

    with pytest.raises(Exception, match="used_bytes is negative"):
        TenantStorageUsage(
            tenant_id=uuid4(), used_bytes=-1, reserved_bytes=0, version=0, updated_at=now
        )

    with pytest.raises(Exception, match="reserved_bytes is negative"):
        TenantStorageUsage(
            tenant_id=uuid4(), used_bytes=0, reserved_bytes=-1, version=0, updated_at=now
        )


# ---------------------------------------------------------------------------
# Reserve, commit, release
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_reserve_then_commit_charges_the_tenant(
    service: StorageQuotaService, tenant_context: Any, tenant_id: UUID, database: Database
) -> None:
    reservation = await service.reserve(tenant_context, incoming_bytes=2 * MEBIBYTE)

    async with database.transaction_scope() as unit_of_work:
        usage = await tenant_storage_usage_crud.get_for_tenant(
            unit_of_work.session_handle, tenant_id
        )
    assert usage is not None
    assert usage.reserved_bytes == 2 * MEBIBYTE
    assert usage.used_bytes == 0

    committed = await service.commit_reservation(reservation)

    assert committed.used_bytes == 2 * MEBIBYTE
    assert committed.reserved_bytes == 0


@pytest.mark.integration
async def test_reserve_then_release_returns_the_capacity(
    service: StorageQuotaService, tenant_context: Any, database: Database, tenant_id: UUID
) -> None:
    reservation = await service.reserve(tenant_context, incoming_bytes=3 * MEBIBYTE)

    released = await service.release_reservation(reservation, reason="storage_unavailable")

    assert released.reserved_bytes == 0
    assert released.used_bytes == 0

    async with database.transaction_scope() as unit_of_work:
        usage = await tenant_storage_usage_crud.get_for_tenant(
            unit_of_work.session_handle, tenant_id
        )
    assert usage is not None
    assert usage.reserved_bytes == 0


@pytest.mark.integration
async def test_reservation_that_exceeds_the_quota_is_refused(
    service: StorageQuotaService, tenant_context: Any
) -> None:
    with pytest.raises(StorageQuotaExceededError) as captured:
        await service.reserve(tenant_context, incoming_bytes=11 * MEBIBYTE)

    assert captured.value.http_status == 413
    # Actionable externally, without publishing the accounting.
    assert "storage limit" in captured.value.external().message.lower()
    assert "11534336" not in captured.value.external().message


@pytest.mark.integration
async def test_quota_is_cumulative_across_uploads(
    service: StorageQuotaService, tenant_context: Any
) -> None:
    for _ in range(3):
        reservation = await service.reserve(tenant_context, incoming_bytes=3 * MEBIBYTE)
        await service.commit_reservation(reservation)

    with pytest.raises(StorageQuotaExceededError):
        await service.reserve(tenant_context, incoming_bytes=2 * MEBIBYTE)


@pytest.mark.integration
async def test_a_reservation_plus_committed_bytes_cannot_both_fit(
    service: StorageQuotaService, tenant_context: Any
) -> None:
    """The reserved counter is what stops a second upload over-allocating."""
    await service.reserve(tenant_context, incoming_bytes=7 * MEBIBYTE)

    with pytest.raises(StorageQuotaExceededError):
        await service.reserve(tenant_context, incoming_bytes=4 * MEBIBYTE)


@pytest.mark.integration
async def test_deletion_returns_bytes_to_the_tenant(
    service: StorageQuotaService, tenant_context: Any
) -> None:
    reservation = await service.reserve(tenant_context, incoming_bytes=4 * MEBIBYTE)
    await service.commit_reservation(reservation)

    updated = await service.record_deletion(tenant_context, removed_bytes=4 * MEBIBYTE)

    assert updated.used_bytes == 0
    # Capacity is available again.
    await service.reserve(tenant_context, incoming_bytes=10 * MEBIBYTE)


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_concurrent_reservations_cannot_over_allocate(
    database: Database, tenant_id: UUID
) -> None:
    """Two devices, one remaining slot: exactly one may win.

    This is the test the row lock exists for. Without it, both requests read the
    same starting value, both decide they fit, and the tenant ends up over quota
    by the size of the losing upload.
    """
    service = StorageQuotaService(
        unit_of_work_factory=database.unit_of_work_factory(),
        quota_bytes=5 * MEBIBYTE,
    )
    context = build_tenant_context(
        user_id=uuid4(),
        tenant_id=tenant_id,
        membership_id=uuid4(),
        role_id=uuid4(),
        permission_codes=frozenset({"products.update"}),
        role_name="OWNER",
    )

    outcomes = await asyncio.gather(
        service.reserve(context, incoming_bytes=4 * MEBIBYTE),
        service.reserve(context, incoming_bytes=4 * MEBIBYTE),
        return_exceptions=True,
    )

    successes = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
    refusals = [outcome for outcome in outcomes if isinstance(outcome, StorageQuotaExceededError)]

    assert len(successes) == 1
    assert len(refusals) == 1

    async with database.transaction_scope() as unit_of_work:
        usage = await tenant_storage_usage_crud.get_for_tenant(
            unit_of_work.session_handle, tenant_id
        )
    assert usage is not None
    assert usage.reserved_bytes == 4 * MEBIBYTE
    assert usage.claimed_bytes <= 5 * MEBIBYTE


@pytest.mark.integration
async def test_concurrent_commits_accumulate_correctly(database: Database, tenant_id: UUID) -> None:
    """Five parallel uploads each fit; the total is the sum, not the last write."""
    service = StorageQuotaService(
        unit_of_work_factory=database.unit_of_work_factory(),
        quota_bytes=20 * MEBIBYTE,
    )
    context = build_tenant_context(
        user_id=uuid4(),
        tenant_id=tenant_id,
        membership_id=uuid4(),
        role_id=uuid4(),
        permission_codes=frozenset({"products.update"}),
        role_name="OWNER",
    )

    reservations = await asyncio.gather(
        *(service.reserve(context, incoming_bytes=MEBIBYTE) for _ in range(5))
    )
    await asyncio.gather(*(service.commit_reservation(reservation) for reservation in reservations))

    async with database.transaction_scope() as unit_of_work:
        usage = await tenant_storage_usage_crud.get_for_tenant(
            unit_of_work.session_handle, tenant_id
        )
    assert usage is not None
    assert usage.used_bytes == 5 * MEBIBYTE
    assert usage.reserved_bytes == 0


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_reconciliation_corrects_drift(
    service: StorageQuotaService, tenant_context: Any
) -> None:
    reservation = await service.reserve(tenant_context, incoming_bytes=6 * MEBIBYTE)
    await service.commit_reservation(reservation)

    corrected = await service.reconcile(tenant_context, stored_bytes_by_metadata=2 * MEBIBYTE)

    assert corrected.used_bytes == 2 * MEBIBYTE


@pytest.mark.integration
async def test_reconciliation_requires_a_permission(
    service: StorageQuotaService, tenant_id: UUID
) -> None:
    """An accounting correction is an administrative act, not a request."""
    context_without_permission = build_tenant_context(
        user_id=uuid4(),
        tenant_id=tenant_id,
        membership_id=uuid4(),
        role_id=uuid4(),
        permission_codes=frozenset({"products.update"}),
        role_name="SALES",
    )

    with pytest.raises(AuthorizationError):
        await service.reconcile(context_without_permission, stored_bytes_by_metadata=0)


@pytest.mark.integration
async def test_stale_reservations_are_released_after_the_threshold(
    service: StorageQuotaService, tenant_context: Any, tenant_id: UUID, database: Database
) -> None:
    await service.reserve(tenant_context, incoming_bytes=4 * MEBIBYTE)

    # Age the reservation past the threshold.
    async with database.transaction_scope() as unit_of_work:
        await unit_of_work.session_handle.execute(
            text(
                "UPDATE tenant_storage_usage SET updated_at = :stamp WHERE tenant_id = :tenant_id"
            ),
            {"stamp": datetime.now(UTC) - timedelta(hours=2), "tenant_id": tenant_id},
        )
        await unit_of_work.commit()

    released = await service.release_stale_reservations(
        tenant_context, older_than=timedelta(minutes=15)
    )

    assert released == 4 * MEBIBYTE

    async with database.transaction_scope() as unit_of_work:
        usage = await tenant_storage_usage_crud.get_for_tenant(
            unit_of_work.session_handle, tenant_id
        )
    assert usage is not None
    assert usage.reserved_bytes == 0


@pytest.mark.integration
async def test_a_fresh_reservation_is_not_reclaimed(
    service: StorageQuotaService, tenant_context: Any
) -> None:
    """Reclaiming a reservation a live upload is using would break the quota."""
    await service.reserve(tenant_context, incoming_bytes=4 * MEBIBYTE)

    released = await service.release_stale_reservations(
        tenant_context, older_than=timedelta(minutes=15)
    )

    assert released == 0


@pytest.mark.integration
async def test_usage_is_created_on_first_use(
    service: StorageQuotaService, tenant_context: Any
) -> None:
    usage = await service.get_usage(tenant_context)

    assert usage.used_bytes == 0
    assert usage.reserved_bytes == 0


@pytest.mark.integration
async def test_two_tenants_have_independent_accounting(database: Database) -> None:
    service = StorageQuotaService(
        unit_of_work_factory=database.unit_of_work_factory(),
        quota_bytes=5 * MEBIBYTE,
    )
    first_context = build_tenant_context(
        user_id=uuid4(),
        tenant_id=uuid4(),
        membership_id=uuid4(),
        role_id=uuid4(),
        permission_codes=frozenset({"products.update"}),
        role_name="OWNER",
    )
    second_context = build_tenant_context(
        user_id=uuid4(),
        tenant_id=uuid4(),
        membership_id=uuid4(),
        role_id=uuid4(),
        permission_codes=frozenset({"products.update"}),
        role_name="OWNER",
    )

    await service.reserve(first_context, incoming_bytes=5 * MEBIBYTE)

    # The first tenant is full; the second is untouched.
    second_usage = await service.get_usage(second_context)
    assert second_usage.used_bytes == 0

    await service.reserve(second_context, incoming_bytes=5 * MEBIBYTE)

    with pytest.raises(StorageQuotaExceededError):
        await service.reserve(first_context, incoming_bytes=1)


@pytest.mark.integration
async def test_session_is_not_held_across_the_provider_call(
    database: Database, tenant_id: UUID
) -> None:
    """The lock is released before the caller talks to the provider.

    Holding a row lock across a network call would couple database concurrency
    to a third party's latency, so the reserve transaction must have committed
    by the time it returns.
    """
    service = StorageQuotaService(
        unit_of_work_factory=database.unit_of_work_factory(),
        quota_bytes=10 * MEBIBYTE,
    )
    context = build_tenant_context(
        user_id=uuid4(),
        tenant_id=tenant_id,
        membership_id=uuid4(),
        role_id=uuid4(),
        permission_codes=frozenset({"products.update"}),
        role_name="OWNER",
    )

    await service.reserve(context, incoming_bytes=MEBIBYTE)

    # A second connection can read the row immediately: nothing is locked.
    async with database.transaction_scope() as unit_of_work:
        session: AsyncSession = unit_of_work.session_handle
        result = await session.execute(
            text("SELECT reserved_bytes FROM tenant_storage_usage WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
        assert result.scalar_one() == MEBIBYTE
