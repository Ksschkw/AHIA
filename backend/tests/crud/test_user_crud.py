"""Tests for user persistence.

Integration tests against the real test database, because the behaviour that
matters here is PostgreSQL's: a unique index that refuses a duplicate, a row
that round-trips every field, and an UPDATE that reports a missing row instead
of silently doing nothing. A mocked session would assert none of it.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.errors import ConflictError, NotFoundError
from ahia.crud import user_crud
from ahia.crud.user_crud import UserRecord
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


@pytest.fixture
async def database() -> Any:
    """A database with the users table present and emptied around each test."""
    instance = Database(build_settings())
    async with instance.engine.begin() as connection:
        # The whole schema, created from the models. A table's foreign keys require
        # the tables they reference to exist first, and creating everything in
        # dependency order is exactly what create_all does.
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(sync_connection, checkfirst=True)
        )
        await connection.execute(text("TRUNCATE TABLE users CASCADE"))
    try:
        yield instance
    finally:
        await instance.dispose()


def build_user(**overrides: object) -> UserModel:
    parameters: dict[str, object] = {
        "user_id": uuid4(),
        "first_name": "Emeka",
        "now": NOW,
        "last_name": "Okonkwo",
        "email": f"emeka.{uuid4().hex[:8]}@example.com",
        "phone": None,
    }
    parameters.update(overrides)
    return UserModel.create(**parameters)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_mapping_round_trips_every_field() -> None:
    user = (
        build_user(
            phone="+2348031234567",
            password_hash="$argon2id$v=19$m=65536,t=3,p=2$c2FsdA$aGFzaA",
        )
        .mark_email_verified(at=NOW)
        .mark_phone_verified(at=NOW)
        .record_login(at=NOW)
    )

    record = UserRecord(id=user.id)
    user_crud.apply_entity(record, user)
    restored = user_crud.to_entity(record)

    assert restored == user


@pytest.mark.unit
def test_mapping_keeps_optional_fields_absent() -> None:
    user = build_user(phone=None, last_name=None)

    record = UserRecord(id=user.id)
    user_crud.apply_entity(record, user)
    restored = user_crud.to_entity(record)

    assert restored.phone is None
    assert restored.last_name is None
    assert restored.password_hash is None
    assert restored.last_login_at is None


# ---------------------------------------------------------------------------
# Create and read
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_persists_and_returns_the_entity(database: Database) -> None:
    user = build_user()

    async with database.transaction_scope() as unit_of_work:
        created = await user_crud.create(unit_of_work.session_handle, user)
        await unit_of_work.commit()

    assert created == user

    async with database.transaction_scope() as unit_of_work:
        fetched = await user_crud.get_by_id(unit_of_work.session_handle, user.id)

    assert fetched == user


@pytest.mark.integration
async def test_get_by_id_returns_none_for_an_unknown_identifier(database: Database) -> None:
    async with database.transaction_scope() as unit_of_work:
        fetched = await user_crud.get_by_id(unit_of_work.session_handle, uuid4())

    assert fetched is None


@pytest.mark.integration
async def test_require_by_id_raises_a_typed_not_found(database: Database) -> None:
    missing_id = uuid4()

    async with database.transaction_scope() as unit_of_work:
        with pytest.raises(NotFoundError) as captured:
            await user_crud.require_by_id(unit_of_work.session_handle, missing_id)

    assert captured.value.external().code == "NOT_FOUND"
    assert str(missing_id) not in captured.value.external().message


@pytest.mark.integration
async def test_lookup_by_email_and_phone(database: Database) -> None:
    email = f"ngozi.{uuid4().hex[:8]}@example.com"
    user = build_user(email=email, phone="+2348031234567")

    async with database.transaction_scope() as unit_of_work:
        await user_crud.create(unit_of_work.session_handle, user)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        by_email = await user_crud.get_by_email(unit_of_work.session_handle, email)
        by_phone = await user_crud.get_by_phone(unit_of_work.session_handle, "+2348031234567")
        unknown = await user_crud.get_by_email(unit_of_work.session_handle, "nobody@example.com")

    assert by_email is not None and by_email.id == user.id
    assert by_phone is not None and by_phone.id == user.id
    assert unknown is None


@pytest.mark.integration
async def test_a_deactivated_user_is_still_readable(database: Database) -> None:
    """Whether an inactive user may act is an authorization decision, not a query filter."""
    user = build_user()
    deactivated = user.deactivate(at=NOW + timedelta(days=1))

    async with database.transaction_scope() as unit_of_work:
        await user_crud.create(unit_of_work.session_handle, user)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        await user_crud.update(unit_of_work.session_handle, deactivated)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        fetched = await user_crud.get_by_id(unit_of_work.session_handle, user.id)

    assert fetched is not None
    assert fetched.is_active is False


# ---------------------------------------------------------------------------
# Uniqueness
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_duplicate_email_is_a_typed_conflict(database: Database) -> None:
    email = f"ada.{uuid4().hex[:8]}@example.com"

    async with database.transaction_scope() as unit_of_work:
        await user_crud.create(unit_of_work.session_handle, build_user(email=email))
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        with pytest.raises(ConflictError) as captured:
            await user_crud.create(unit_of_work.session_handle, build_user(email=email))

    assert captured.value.external().code == "CONFLICT"
    # The conflict names the violated constraint internally, which is what makes
    # the log actionable, and nothing externally: which of email or phone
    # collided would confirm that an account exists for an address.
    # A unique index rather than a unique constraint, because the column is
    # indexed for lookup as well; PostgreSQL enforces both identically, and the
    # naming convention gives the index a deterministic name.
    assert "ix_users_email" in str(captured.value)
    assert email not in captured.value.external().message
    assert "ix_users_email" not in repr(captured.value.external().to_payload())


@pytest.mark.integration
async def test_a_duplicate_phone_is_a_typed_conflict(database: Database) -> None:
    phone = f"+234803{uuid4().int % 10_000_000:07d}"

    async with database.transaction_scope() as unit_of_work:
        await user_crud.create(unit_of_work.session_handle, build_user(phone=phone))
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        with pytest.raises(ConflictError):
            await user_crud.create(
                unit_of_work.session_handle,
                build_user(email=None, phone=phone),
            )


@pytest.mark.integration
async def test_many_users_may_have_no_phone(database: Database) -> None:
    """A nullable unique column must permit many nulls, which PostgreSQL does."""
    async with database.transaction_scope() as unit_of_work:
        await user_crud.create(unit_of_work.session_handle, build_user(phone=None))
        await user_crud.create(unit_of_work.session_handle, build_user(phone=None))
        await unit_of_work.commit()

        assert await user_crud.count_users(unit_of_work.session_handle) == 2


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_update_persists_changed_fields(database: Database) -> None:
    user = build_user()

    async with database.transaction_scope() as unit_of_work:
        await user_crud.create(unit_of_work.session_handle, user)
        await unit_of_work.commit()

    later = NOW + timedelta(hours=2)
    renamed = user.with_profile(first_name="Chinedu", at=later)

    async with database.transaction_scope() as unit_of_work:
        updated = await user_crud.update(unit_of_work.session_handle, renamed)
        await unit_of_work.commit()

    assert updated.first_name == "Chinedu"
    assert updated.updated_at == later

    async with database.transaction_scope() as unit_of_work:
        fetched = await user_crud.get_by_id(unit_of_work.session_handle, user.id)

    assert fetched is not None
    assert fetched.first_name == "Chinedu"
    assert fetched.email == user.email


@pytest.mark.integration
async def test_update_of_a_missing_row_is_a_typed_not_found(database: Database) -> None:
    """A stale entity must not silently create or resurrect a row."""
    ghost = build_user()

    async with database.transaction_scope() as unit_of_work:
        with pytest.raises(NotFoundError):
            await user_crud.update(unit_of_work.session_handle, ghost)


@pytest.mark.integration
async def test_update_preserves_fields_it_did_not_change(database: Database) -> None:
    user = build_user(phone="+2348039998888")

    async with database.transaction_scope() as unit_of_work:
        await user_crud.create(unit_of_work.session_handle, user)
        await unit_of_work.commit()

    changed = user.with_profile(last_name="Uzoma", at=NOW + timedelta(minutes=5))

    async with database.transaction_scope() as unit_of_work:
        await user_crud.update(unit_of_work.session_handle, changed)
        await unit_of_work.commit()

    async with database.transaction_scope() as unit_of_work:
        fetched = await user_crud.get_by_id(unit_of_work.session_handle, user.id)

    assert fetched is not None
    assert fetched.last_name == "Uzoma"
    assert fetched.phone == "+2348039998888"
    assert fetched.created_at == NOW, "created_at is immutable"


# ---------------------------------------------------------------------------
# Transaction behaviour
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_rolled_back_create_leaves_no_row(database: Database) -> None:
    """A failed use case must leave nothing behind, including a half-built user."""
    user = build_user()

    with pytest.raises(RuntimeError):
        async with database.transaction_scope() as unit_of_work:
            await user_crud.create(unit_of_work.session_handle, user)
            raise RuntimeError("a later step in the use case failed")

    async with database.transaction_scope() as unit_of_work:
        assert await user_crud.count_users(unit_of_work.session_handle) == 0


@pytest.mark.integration
async def test_the_conflict_error_does_not_poison_the_next_transaction(database: Database) -> None:
    """The failed insert rolls its own transaction back, so the pool stays usable."""
    email = f"two.{uuid4().hex[:8]}@example.com"

    async with database.transaction_scope() as unit_of_work:
        await user_crud.create(unit_of_work.session_handle, build_user(email=email))
        await unit_of_work.commit()

    with pytest.raises(ConflictError):
        async with database.transaction_scope() as unit_of_work:
            await user_crud.create(unit_of_work.session_handle, build_user(email=email))

    async with database.transaction_scope() as unit_of_work:
        await user_crud.create(
            unit_of_work.session_handle, build_user(email=f"fresh.{uuid4().hex[:8]}@example.com")
        )
        await unit_of_work.commit()

        assert await user_crud.count_users(unit_of_work.session_handle) == 2
