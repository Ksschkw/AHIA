"""Tests for the device entity and its persistence.

A device is an identity, not an authorization, so the tests are about identity:
what makes one installation distinguishable from another, what revocation means,
and the uniqueness rule that keeps one installation from becoming two rows.
"""

from __future__ import annotations

import os
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.errors import ConflictError, EntityInvariantError, NotFoundError
from ahia.crud import device_crud, tenant_crud, user_crud
from ahia.models.entities.device_model import KNOWN_PLATFORMS, DeviceModel
from ahia.models.entities.tenant_model import TenantModel
from ahia.models.entities.user_model import UserModel

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)


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


def build_device(**overrides: object) -> DeviceModel:
    parameters: dict[str, object] = {
        "device_id": uuid4(),
        "tenant_id": uuid4(),
        "user_id": uuid4(),
        "device_identifier": "installation-abc123",
        "platform": "android",
        "now": NOW,
        "device_name": "Obi's phone",
        "app_version": "1.0.0",
    }
    parameters.update(overrides)
    return DeviceModel.register(**parameters)  # type: ignore[arg-type]


@pytest.fixture
async def database() -> Any:
    instance = Database(build_settings())
    async with instance.engine.begin() as connection:
        # The whole schema, created from the models. A table's foreign keys require
        # the tables they reference to exist first, and creating everything in
        # dependency order is exactly what create_all does.
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(sync_connection, checkfirst=True)
        )
        await connection.execute(text("TRUNCATE TABLE devices CASCADE"))
    try:
        yield instance
    finally:
        await instance.dispose()


async def insert_tenant(database: Database, tenant_id: UUID) -> None:
    """Create the business a device row will reference.

    A device carries foreign keys to the business and the person it belongs to, so a
    test that invents identifiers has to create those rows first - which is the order
    a real caller follows, because a device is registered by somebody who is already
    a member of a business.
    """
    async with database.transaction_scope() as unit_of_work:
        await tenant_crud.create(
            unit_of_work.session_handle,
            TenantModel.create(
                tenant_id=tenant_id,
                name=f"Tenant {tenant_id.hex[:6]}",
                slug=f"tenant-{tenant_id.hex[:8]}",
                now=NOW,
            ),
        )
        await unit_of_work.commit()


async def insert_user(database: Database, user_id: UUID) -> None:
    """Create the person a device row will reference.

    Each test that needs a device creates the rows it references, one call per
    distinct identifier: creating the same business twice is a primary-key collision,
    and swallowing that would hide a test that forgot to reuse an identifier.
    """
    async with database.transaction_scope() as unit_of_work:
        await user_crud.create(
            unit_of_work.session_handle,
            UserModel.create(
                user_id=user_id,
                first_name="Emeka",
                last_name="Okonkwo",
                email=f"emeka.{user_id.hex[:8]}@example.com",
                now=NOW,
            ),
        )
        await unit_of_work.commit()


async def insert_device_parents(database: Database, device: DeviceModel) -> None:
    """Create both rows one device references, for tests that register one device."""
    await insert_tenant(database, device.tenant_id)
    await insert_user(database, device.user_id)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_registered_device_records_when_it_was_first_and_last_seen() -> None:
    device = build_device()

    assert device.created_at == NOW
    assert device.last_seen_at == NOW
    assert device.is_revoked() is False
    assert device.platform == "android"
    assert device.device_name == "Obi's phone"


@pytest.mark.unit
@pytest.mark.parametrize("platform", sorted(KNOWN_PLATFORMS))
def test_every_shipped_client_platform_is_accepted(platform: str) -> None:
    assert build_device(platform=platform).platform == platform


@pytest.mark.unit
@pytest.mark.parametrize("platform", ["windows", "symbian", "", "ANDROID"])
def test_an_unknown_platform_is_rejected(platform: str) -> None:
    """An unknown platform is a client nobody registered here, or a claim."""
    with pytest.raises(EntityInvariantError, match="unknown platform"):
        build_device(platform=platform)


@pytest.mark.unit
def test_an_empty_identifier_is_rejected() -> None:
    with pytest.raises(EntityInvariantError, match="device_identifier is empty"):
        build_device(device_identifier="   ")


@pytest.mark.unit
def test_an_overlong_identifier_is_rejected() -> None:
    with pytest.raises(EntityInvariantError, match="exceeds"):
        build_device(device_identifier="x" * 129)


@pytest.mark.unit
def test_timestamps_must_carry_a_timezone() -> None:
    with pytest.raises(EntityInvariantError, match="naive datetime"):
        build_device(now=datetime(2026, 9, 13, 9, 30))  # noqa: DTZ001 - the input under test


@pytest.mark.unit
def test_a_device_grants_no_authority_and_says_so() -> None:
    """The rule the whole entity exists to express, asserted rather than commented."""
    device = build_device()

    assert device.grants_no_authority is True
    assert not hasattr(device, "permissions")
    assert not hasattr(device, "role_name")


@pytest.mark.unit
def test_the_entity_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        build_device().platform = "ios"  # type: ignore[misc]


@pytest.mark.unit
def test_audit_description_carries_no_hardware_or_network_identifier() -> None:
    description = build_device().describe_for_audit()

    assert set(description) == {
        "device_id",
        "tenant_id",
        "platform",
        "is_revoked",
        "app_version",
    }
    assert "installation-abc123" not in repr(description)


# ---------------------------------------------------------------------------
# Heartbeat and revocation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_heartbeat_updates_the_last_seen_time() -> None:
    device = build_device()
    later = NOW + timedelta(hours=3)

    seen = device.seen(at=later, app_version="1.0.1")

    assert seen.last_seen_at == later
    assert seen.app_version == "1.0.1"
    assert seen.created_at == NOW, "the first sighting does not move"
    assert device.last_seen_at == NOW, "the original is untouched"


@pytest.mark.unit
def test_a_revoked_device_cannot_report_in() -> None:
    """Otherwise a revoked phone would quietly renew itself."""
    revoked = build_device().revoke(at=NOW + timedelta(days=1))

    with pytest.raises(EntityInvariantError, match="revoked device cannot report in"):
        revoked.seen(at=NOW + timedelta(days=2))


@pytest.mark.unit
def test_revocation_is_terminal_and_idempotent() -> None:
    device = build_device()
    first = device.revoke(at=NOW + timedelta(days=1))
    second = first.revoke(at=NOW + timedelta(days=2))

    assert first.is_revoked() is True
    assert second.revoked_at == first.revoked_at, "the first decision stands"
    assert device.is_revoked() is False


@pytest.mark.unit
def test_belongs_to_requires_both_the_business_and_the_person() -> None:
    device = build_device()

    assert device.belongs_to(tenant_id=device.tenant_id, user_id=device.user_id) is True
    assert device.belongs_to(tenant_id=uuid4(), user_id=device.user_id) is False
    assert device.belongs_to(tenant_id=device.tenant_id, user_id=uuid4()) is False


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_and_look_up_by_identifier(database: Database) -> None:
    device = build_device()
    await insert_device_parents(database, device)

    async with database.transaction_scope() as unit_of_work:
        created = await device_crud.create(unit_of_work.session_handle, device)
        await unit_of_work.commit()

    assert created == device

    async with database.transaction_scope() as unit_of_work:
        found = await device_crud.get_by_identifier(
            unit_of_work.session_handle,
            tenant_id=device.tenant_id,
            device_identifier=device.device_identifier,
        )
        elsewhere = await device_crud.get_by_identifier(
            unit_of_work.session_handle,
            tenant_id=uuid4(),
            device_identifier=device.device_identifier,
        )

    assert found is not None and found.id == device.id
    assert elsewhere is None, "the same identifier in another business is another device"


@pytest.mark.integration
async def test_a_device_for_an_unknown_business_is_a_typed_not_found(
    database: Database,
) -> None:
    """The database enforces the reference, and the error says what actually happened.

    The person exists but the business does not, so the row is refused by the foreign
    key. Reporting that as "already registered" would send whoever read the log
    looking for a duplicate that was never there.
    """
    device = build_device()
    await insert_user(database, device.user_id)

    with pytest.raises(NotFoundError) as captured:
        async with database.transaction_scope() as unit_of_work:
            await device_crud.create(unit_of_work.session_handle, device)

    assert "does not exist" in (captured.value.context.detail or "")
    assert captured.value.__cause__ is not None, "the driver's failure is still reachable"


@pytest.mark.integration
async def test_the_same_installation_cannot_be_registered_twice_in_one_business(
    database: Database,
) -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    first = build_device(tenant_id=tenant_id, user_id=user_id)
    await insert_device_parents(database, first)

    async with database.transaction_scope() as unit_of_work:
        await device_crud.create(unit_of_work.session_handle, first)
        await unit_of_work.commit()

    with pytest.raises(ConflictError):
        async with database.transaction_scope() as unit_of_work:
            await device_crud.create(
                unit_of_work.session_handle,
                build_device(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    device_identifier=first.device_identifier,
                ),
            )


@pytest.mark.integration
async def test_two_businesses_may_hold_the_same_identifier(database: Database) -> None:
    """Two businesses are two worlds; the same installation visits both."""
    identifier = "shared-installation"
    visiting_first = build_device(device_identifier=identifier)
    visiting_second = build_device(device_identifier=identifier)
    await insert_device_parents(database, visiting_first)
    await insert_device_parents(database, visiting_second)

    async with database.transaction_scope() as unit_of_work:
        await device_crud.create(unit_of_work.session_handle, visiting_first)
        await device_crud.create(unit_of_work.session_handle, visiting_second)
        await unit_of_work.commit()

        listed_first = await device_crud.list_for_tenant(unit_of_work.session_handle, uuid4())

    assert listed_first == []


@pytest.mark.integration
async def test_revocation_is_persisted(database: Database) -> None:
    device = build_device()
    await insert_device_parents(database, device)

    async with database.transaction_scope() as unit_of_work:
        await device_crud.create(unit_of_work.session_handle, device)
        await unit_of_work.commit()

    revoked_at = NOW + timedelta(days=2)
    async with database.transaction_scope() as unit_of_work:
        await device_crud.update(unit_of_work.session_handle, device.revoke(at=revoked_at))
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        found = await device_crud.get_by_id(unit_of_work.session_handle, device.id)

    assert found is not None
    assert found.is_revoked() is True
    assert found.revoked_at == revoked_at


@pytest.mark.integration
async def test_update_of_a_missing_device_is_a_typed_not_found(database: Database) -> None:
    async with database.transaction_scope() as unit_of_work:
        with pytest.raises(NotFoundError):
            await device_crud.update(unit_of_work.session_handle, build_device())


@pytest.mark.integration
async def test_listing_is_scoped_to_the_business_and_ordered_by_last_seen(
    database: Database,
) -> None:
    tenant_id = uuid4()
    # Distinct identifiers: one installation per business is the uniqueness rule,
    # so three devices in one business must be three installations.
    first = build_device(
        tenant_id=tenant_id, device_name="First", device_identifier="installation-first"
    )
    second = build_device(
        tenant_id=tenant_id, device_name="Second", device_identifier="installation-second"
    )
    elsewhere = build_device(device_name="Elsewhere", device_identifier="installation-elsewhere")
    # The two installations in the same business share one business and two people;
    # the third lives somewhere else entirely.
    await insert_tenant(database, tenant_id)
    for user_id in (first.user_id, second.user_id):
        await insert_user(database, user_id)
    await insert_device_parents(database, elsewhere)

    async with database.transaction_scope() as unit_of_work:
        session = unit_of_work.session_handle
        await device_crud.create(session, first)
        await device_crud.create(session, second)
        await device_crud.create(session, elsewhere)
        await device_crud.update(session, second.seen(at=NOW + timedelta(hours=1)))
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        listed = await device_crud.list_for_tenant(unit_of_work.session_handle, tenant_id)
        mine = await device_crud.list_for_user(
            unit_of_work.session_handle, tenant_id=tenant_id, user_id=first.user_id
        )

    assert [device.device_name for device in listed] == ["Second", "First"]
    assert [device.device_name for device in mine] == ["First"]
