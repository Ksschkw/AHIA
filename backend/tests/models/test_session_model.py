"""Tests for the session entity and its persistence.

Sessions are credential material, so the tests are about the rules that keep them
safe: an expired or revoked session never authenticates, rotation leaves a
detectable trail, and revoking a family spares the device the person kept.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.errors import EntityInvariantError, NotFoundError
from ahia.crud import session_crud, user_crud
from ahia.models.entities.session_model import SessionModel
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


def build_session(**overrides: Any) -> SessionModel:
    parameters: dict[str, Any] = {
        "session_id": uuid4(),
        "user_id": uuid4(),
        "refresh_token_hash": "a" * 64,
        "expires_at": NOW + timedelta(days=30),
        "created_at": NOW,
    }
    parameters.update(overrides)
    return SessionModel.issue(**parameters)  # type: ignore[arg-type]


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
        await connection.execute(text("TRUNCATE TABLE user_sessions CASCADE"))
    try:
        yield instance
    finally:
        await instance.dispose()


async def insert_user(database: Database, user_id: UUID) -> None:
    """Create the person a session row will reference.

    A session belongs to a user, so a test that invents a user identifier has to
    create the user first - the order a real caller follows, because nobody holds a
    session before they exist.
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


# ---------------------------------------------------------------------------
# Entity invariants
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_new_session_is_active() -> None:
    session = build_session()

    assert session.is_active(at=NOW) is True
    assert session.is_revoked() is False
    assert session.is_expired(at=NOW) is False
    assert session.was_rotated() is False


@pytest.mark.unit
def test_an_empty_token_hash_is_rejected() -> None:
    with pytest.raises(EntityInvariantError, match="refresh_token_hash is empty"):
        build_session(refresh_token_hash="   ")


@pytest.mark.unit
def test_expiry_must_be_after_creation() -> None:
    with pytest.raises(EntityInvariantError, match="expires_at is not later"):
        build_session(expires_at=NOW)


@pytest.mark.unit
def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(EntityInvariantError, match="naive datetime"):
        # The naive value is the input under test.
        build_session(expires_at=datetime(2026, 10, 13, 9, 30))  # noqa: DTZ001


@pytest.mark.unit
def test_a_revocation_before_creation_is_rejected() -> None:
    """A timestamp that predates the row is corruption, however it arrived."""
    with pytest.raises(EntityInvariantError, match="revoked_at is earlier"):
        SessionModel(
            id=uuid4(),
            user_id=uuid4(),
            refresh_token_hash="a" * 64,
            expires_at=NOW + timedelta(days=30),
            created_at=NOW,
            revoked_at=NOW - timedelta(hours=1),
            revocation_reason="stolen",
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("at_offset_days", "expected"),
    [(0, False), (29, False), (30, True), (40, True)],
)
def test_expiry_is_evaluated_against_the_clock(at_offset_days: int, expected: bool) -> None:
    session = build_session()

    assert session.is_expired(at=NOW + timedelta(days=at_offset_days)) is expected


@pytest.mark.unit
def test_revoking_returns_a_new_instance_and_records_the_reason() -> None:
    session = build_session()
    revoked = session.revoke(at=NOW + timedelta(hours=1), reason="signed_out")

    assert revoked.is_revoked() is True
    assert revoked.revocation_reason == "signed_out"
    assert revoked.is_active(at=NOW + timedelta(hours=2)) is False
    assert session.is_revoked() is False, "the original is untouched"


@pytest.mark.unit
def test_revoking_twice_keeps_the_first_reason() -> None:
    """The first reason is the true one; a later call must not rewrite history."""
    session = build_session()
    first = session.revoke(at=NOW, reason="password_changed")
    second = first.revoke(at=NOW + timedelta(minutes=1), reason="signed_out")

    assert second.revocation_reason == "password_changed"
    assert second.revoked_at == NOW


@pytest.mark.unit
def test_rotation_marks_the_session_and_points_at_the_replacement() -> None:
    session = build_session()
    replacement_id = uuid4()

    rotated = session.rotate(replacement_session_id=replacement_id, at=NOW + timedelta(days=1))

    assert rotated.is_revoked() is True
    assert rotated.revocation_reason == "rotated"
    assert rotated.replaced_by_session_id == replacement_id
    assert rotated.was_rotated() is True
    assert rotated.is_reuse_suspect is True
    assert rotated.last_used_at == NOW + timedelta(days=1)


@pytest.mark.unit
def test_a_plainly_revoked_session_is_not_a_reuse_suspect() -> None:
    """Signing out is not theft, and must not trigger a family revocation."""
    signed_out = build_session().revoke(at=NOW, reason="signed_out")

    assert signed_out.is_reuse_suspect is False


@pytest.mark.unit
def test_touch_and_device_binding_return_new_instances() -> None:
    session = build_session()
    device_id = uuid4()
    later = NOW + timedelta(minutes=5)

    touched = session.touch(at=later)
    bound = touched.bind_to_device(device_id=device_id)

    assert touched.last_used_at == later
    assert bound.device_id == device_id
    assert session.last_used_at is None
    assert session.device_id is None


@pytest.mark.unit
def test_audit_description_carries_no_token_material() -> None:
    session = build_session(device_id=uuid4())

    description = session.describe_for_audit()
    rendered = repr(description)

    assert set(description) == {"session_id", "user_id", "is_revoked", "device_id"}
    assert session.refresh_token_hash not in rendered


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_and_look_up_by_token_hash(database: Database) -> None:
    session = build_session(refresh_token_hash="b" * 64)
    await insert_user(database, session.user_id)

    async with database.transaction_scope() as unit_of_work:
        created = await session_crud.create(unit_of_work.session_handle, session)
        await unit_of_work.commit()

    assert created == session

    async with database.transaction_scope() as unit_of_work:
        found = await session_crud.get_by_token_hash(unit_of_work.session_handle, "b" * 64)
        missing = await session_crud.get_by_token_hash(unit_of_work.session_handle, "c" * 64)

    assert found is not None and found.id == session.id
    assert missing is None


@pytest.mark.integration
async def test_a_revoked_session_is_still_found_by_its_digest(database: Database) -> None:
    """The reuse detector needs the row, so filtering it out would hide a theft."""
    session = build_session(refresh_token_hash="d" * 64)
    await insert_user(database, session.user_id)
    rotated = session.rotate(replacement_session_id=uuid4(), at=NOW + timedelta(days=1))

    async with database.transaction_scope() as unit_of_work:
        await session_crud.create(unit_of_work.session_handle, rotated)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        found = await session_crud.get_by_token_hash(unit_of_work.session_handle, "d" * 64)

    assert found is not None
    assert found.was_rotated() is True


@pytest.mark.integration
async def test_lookup_for_update_returns_the_session(database: Database) -> None:
    session = build_session(refresh_token_hash="e" * 64)
    await insert_user(database, session.user_id)

    async with database.transaction_scope() as unit_of_work:
        await session_crud.create(unit_of_work.session_handle, session)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        locked = await session_crud.get_by_token_hash_for_update(
            unit_of_work.session_handle, "e" * 64
        )
        assert locked is not None
        stored = await session_crud.update(
            unit_of_work.session_handle, locked.touch(at=NOW + timedelta(minutes=1))
        )
        await unit_of_work.commit()

    assert stored.last_used_at == NOW + timedelta(minutes=1)


@pytest.mark.integration
async def test_update_of_a_missing_session_is_a_typed_not_found(database: Database) -> None:
    async with database.transaction_scope() as unit_of_work:
        with pytest.raises(NotFoundError):
            await session_crud.update(unit_of_work.session_handle, build_session())


@pytest.mark.integration
async def test_revoke_all_spares_the_named_session(database: Database) -> None:
    """Changing a password must not sign the person out of the device they are on."""
    user_id = uuid4()
    kept = build_session(user_id=user_id, refresh_token_hash="f" * 64)
    other = build_session(user_id=user_id, refresh_token_hash="g" * 64)
    unrelated = build_session(refresh_token_hash="h" * 64)
    await insert_user(database, user_id)
    await insert_user(database, unrelated.user_id)

    async with database.transaction_scope() as unit_of_work:
        session = unit_of_work.session_handle
        await session_crud.create(session, kept)
        await session_crud.create(session, other)
        await session_crud.create(session, unrelated)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        revoked = await session_crud.revoke_all_for_user(
            unit_of_work.session_handle,
            user_id=user_id,
            at=NOW + timedelta(minutes=1),
            reason="password_changed",
            except_session_id=kept.id,
        )
        await unit_of_work.commit()

    assert revoked == 1

    async with database.transaction_scope() as unit_of_work:
        session = unit_of_work.session_handle
        kept_row = await session_crud.get_by_id(session, kept.id)
        other_row = await session_crud.get_by_id(session, other.id)
        unrelated_row = await session_crud.get_by_id(session, unrelated.id)

    assert kept_row is not None and kept_row.is_revoked() is False
    assert other_row is not None and other_row.revocation_reason == "password_changed"
    assert unrelated_row is not None and unrelated_row.is_revoked() is False


@pytest.mark.integration
async def test_listing_active_sessions_excludes_revoked_and_expired(database: Database) -> None:
    user_id = uuid4()
    active = build_session(user_id=user_id, refresh_token_hash="i" * 64)
    revoked = build_session(user_id=user_id, refresh_token_hash="j" * 64).revoke(
        at=NOW, reason="signed_out"
    )
    expired = build_session(
        user_id=user_id,
        refresh_token_hash="k" * 64,
        expires_at=NOW + timedelta(hours=1),
    )
    await insert_user(database, user_id)

    async with database.transaction_scope() as unit_of_work:
        session = unit_of_work.session_handle
        for entity in (active, revoked, expired):
            await session_crud.create(session, entity)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        listed = await session_crud.list_active_for_user(
            unit_of_work.session_handle, user_id=user_id, at=NOW + timedelta(hours=2)
        )

    assert [entity.id for entity in listed] == [active.id]


@pytest.mark.integration
async def test_expired_sessions_can_be_pruned(database: Database) -> None:
    expired = build_session(refresh_token_hash="l" * 64, expires_at=NOW + timedelta(days=1))
    live = build_session(refresh_token_hash="m" * 64, expires_at=NOW + timedelta(days=60))
    await insert_user(database, expired.user_id)
    await insert_user(database, live.user_id)

    async with database.transaction_scope() as unit_of_work:
        session = unit_of_work.session_handle
        await session_crud.create(session, expired)
        await session_crud.create(session, live)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        removed = await session_crud.delete_expired(
            unit_of_work.session_handle, before=NOW + timedelta(days=30)
        )
        await unit_of_work.commit()

    assert removed == 1

    async with database.transaction_scope() as unit_of_work:
        assert await session_crud.count_sessions(unit_of_work.session_handle) == 1
