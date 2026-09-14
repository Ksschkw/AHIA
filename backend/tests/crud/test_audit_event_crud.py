"""Tests for the audit trail's persistence.

Three properties are tested here that only the database can prove.

The trail cannot be rewritten
    A trigger refuses UPDATE and DELETE. Tested with raw SQL rather than by calling a function
    that does not exist, because the point is that the rule holds for a writer that never loads
    this product's Python: a psql session, a migration, a future service.

There is no function in this module that could attempt either
    Asserted mechanically against the source. A helper added later "to fix a typo in an old
    event" is exactly how a trail becomes editable, and the absence is the design.

Reads are scoped and ordered
    A business's events, one record's history, one person's actions. A second business sees
    none of them, through every path.
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
from ahia.crud import audit_event_crud, tenant_crud, user_crud
from ahia.models.entities.audit_event_model import AuditEventModel, AuditOutcome
from ahia.models.entities.tenant_model import TenantModel
from ahia.models.entities.user_model import UserModel

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=2)

AUDIT_CRUD_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "ahia" / "crud" / "audit_event_crud.py"
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
        # The whole schema, created from the models. The append-only trigger is created by the
        # migration rather than by the metadata, so the tests that depend on it apply it here.
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(sync_connection, checkfirst=True)
        )
        await connection.execute(text("TRUNCATE TABLE audit_events, tenants CASCADE"))
        # asyncpg refuses more than one statement per prepared statement, so the function and
        # the trigger are created in separate round trips.
        await connection.execute(
            text(
                """
                CREATE OR REPLACE FUNCTION ahia_audit_events_append_only() RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION
                        'audit_events is append-only: record a compensating event instead';
                END;
                $$ LANGUAGE plpgsql;
                """
            )
        )
        await connection.execute(
            text("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
        )
        await connection.execute(
            text(
                """
                CREATE TRIGGER audit_events_append_only
                BEFORE UPDATE OR DELETE ON audit_events
                FOR EACH ROW EXECUTE FUNCTION ahia_audit_events_append_only();
                """
            )
        )
    try:
        yield instance
    finally:
        await instance.dispose()


async def insert_tenant(database: Database, *, name: str = "Obi Electronics") -> UUID:
    identifier = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await tenant_crud.create(
            unit_of_work.session_handle,
            TenantModel.create(
                tenant_id=identifier,
                name=name,
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


@pytest.fixture
async def tenant_id(database: Database) -> UUID:
    return await insert_tenant(database)


@pytest.fixture
async def actor_id(database: Database) -> UUID:
    return await insert_user(database)


def build_event(
    *,
    tenant_id: UUID,
    actor_id: UUID | None = None,
    action: str = "record_expense",
    entity_type: str = "expense",
    entity_id: UUID | None = None,
    occurred_at: datetime = NOW,
    **overrides: object,
) -> AuditEventModel:
    parameters: dict[str, object] = {
        "event_id": uuid4(),
        "tenant_id": tenant_id,
        "action": action,
        "entity_type": entity_type,
        "now": occurred_at,
        "actor_id": actor_id,
        "entity_id": entity_id,
        "detail": {"expense_id": str(uuid4())},
    }
    parameters.update(overrides)
    return AuditEventModel.record(**parameters)  # type: ignore[arg-type]


async def persist_event(database: Database, event: AuditEventModel) -> AuditEventModel:
    async with database.transaction_scope() as unit_of_work:
        stored = await audit_event_crud.record(unit_of_work.session_handle, event)
        await unit_of_work.commit()
    return stored


# ---------------------------------------------------------------------------
# Writing and reading back
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_an_event_round_trips_through_storage(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    entity_id = uuid4()
    event = build_event(tenant_id=tenant_id, actor_id=actor_id, entity_id=entity_id)

    stored = await persist_event(database, event)

    async with database.transaction_scope() as unit_of_work:
        reread = await audit_event_crud.list_for_entity(
            unit_of_work.session_handle,
            tenant_id=tenant_id,
            entity_type="expense",
            entity_id=entity_id,
        )

    assert stored.id == event.id
    assert len(reread) == 1
    assert reread[0].action == "record_expense"
    assert reread[0].actor_id == actor_id
    assert reread[0].occurred_at == NOW
    assert reread[0].detail == event.detail


@pytest.mark.integration
async def test_an_event_with_no_actor_is_stored_without_one(
    database: Database, tenant_id: UUID
) -> None:
    stored = await persist_event(
        database,
        build_event(tenant_id=tenant_id, action="install_permission_registry", actor_id=None),
    )

    assert stored.actor_id is None


@pytest.mark.integration
async def test_events_of_two_businesses_do_not_see_each_other(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    other_tenant = await insert_tenant(database, name="Ada Provisions")
    event = build_event(tenant_id=tenant_id, actor_id=actor_id)
    await persist_event(database, event)

    async with database.transaction_scope() as unit_of_work:
        listed = await audit_event_crud.list_for_tenant(unit_of_work.session_handle, other_tenant)
        by_actor = await audit_event_crud.list_for_actor(
            unit_of_work.session_handle, tenant_id=other_tenant, actor_id=actor_id
        )
        count = await audit_event_crud.count_for_tenant(unit_of_work.session_handle, other_tenant)

    assert listed == []
    assert by_actor == []
    assert count == 0


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_businesss_events_are_returned_most_recent_first(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    older = build_event(
        tenant_id=tenant_id, actor_id=actor_id, action="create_product", occurred_at=NOW
    )
    newer = build_event(
        tenant_id=tenant_id, actor_id=actor_id, action="complete_sale", occurred_at=LATER
    )
    await persist_event(database, older)
    await persist_event(database, newer)

    async with database.transaction_scope() as unit_of_work:
        listed = await audit_event_crud.list_for_tenant(unit_of_work.session_handle, tenant_id)

    assert [event.action for event in listed] == ["complete_sale", "create_product"]


@pytest.mark.integration
async def test_a_period_excludes_the_moment_it_ends(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    inside = build_event(tenant_id=tenant_id, actor_id=actor_id, occurred_at=NOW)
    on_the_boundary = build_event(tenant_id=tenant_id, actor_id=actor_id, occurred_at=LATER)
    await persist_event(database, inside)
    await persist_event(database, on_the_boundary)

    async with database.transaction_scope() as unit_of_work:
        listed = await audit_event_crud.list_for_tenant(
            unit_of_work.session_handle, tenant_id, since=NOW, until=LATER
        )

    assert [event.id for event in listed] == [inside.id]


@pytest.mark.integration
async def test_one_records_history_is_ordered_by_when_it_happened(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    entity_id = uuid4()
    first = build_event(
        tenant_id=tenant_id, actor_id=actor_id, entity_id=entity_id, occurred_at=NOW
    )
    second = build_event(
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_id=entity_id,
        action="reverse_expense",
        occurred_at=LATER,
    )
    await persist_event(database, second)
    await persist_event(database, first)

    async with database.transaction_scope() as unit_of_work:
        history = await audit_event_crud.list_for_entity(
            unit_of_work.session_handle,
            tenant_id=tenant_id,
            entity_type="expense",
            entity_id=entity_id,
        )

    assert [event.action for event in history] == ["record_expense", "reverse_expense"]


@pytest.mark.integration
async def test_what_one_person_did_is_returned(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    other_actor = await insert_user(database)
    await persist_event(database, build_event(tenant_id=tenant_id, actor_id=actor_id))
    await persist_event(database, build_event(tenant_id=tenant_id, actor_id=other_actor))

    async with database.transaction_scope() as unit_of_work:
        actions = await audit_event_crud.list_for_actor(
            unit_of_work.session_handle, tenant_id=tenant_id, actor_id=actor_id
        )

    assert len(actions) == 1
    assert actions[0].actor_id == actor_id


@pytest.mark.integration
async def test_a_refusal_is_stored_and_readable(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    """The half of a trail that reaches beyond "who did" into "who tried"."""
    await persist_event(
        database,
        build_event(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="cancel_sale",
            entity_id=None,
            outcome=AuditOutcome.DENIED,
        ),
    )

    async with database.transaction_scope() as unit_of_work:
        listed = await audit_event_crud.list_for_tenant(unit_of_work.session_handle, tenant_id)

    assert listed[0].outcome is AuditOutcome.DENIED
    assert listed[0].is_refusal() is True


# ---------------------------------------------------------------------------
# Append-only, enforced by the database
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_an_event_cannot_be_deleted(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    stored = await persist_event(database, build_event(tenant_id=tenant_id, actor_id=actor_id))

    with pytest.raises(DBAPIError) as raised:
        async with database.transaction_scope() as unit_of_work:
            await unit_of_work.session_handle.execute(
                text("DELETE FROM audit_events WHERE id = :id"), {"id": stored.id}
            )
            await unit_of_work.commit()

    assert "append-only" in str(raised.value)


@pytest.mark.integration
async def test_an_event_cannot_be_changed(
    database: Database, tenant_id: UUID, actor_id: UUID
) -> None:
    stored = await persist_event(database, build_event(tenant_id=tenant_id, actor_id=actor_id))

    with pytest.raises(DBAPIError) as raised:
        async with database.transaction_scope() as unit_of_work:
            await unit_of_work.session_handle.execute(
                text("UPDATE audit_events SET action = 'something_else' WHERE id = :id"),
                {"id": stored.id},
            )
            await unit_of_work.commit()

    assert "append-only" in str(raised.value)


@pytest.mark.unit
def test_the_trail_offers_no_way_to_change_or_remove_an_event() -> None:
    tree = ast.parse(AUDIT_CRUD_PATH.read_text(encoding="utf-8"))
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
    assert not forbidden, f"the audit trail gained a mutating function: {sorted(forbidden)}"
