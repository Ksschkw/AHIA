"""Tests for the change feed.

Four properties.

**The feed is written by the same call that writes the trail.** A test records an audit event
through the recorder and asserts the change row exists, in the same transaction, with the same
instant. The two cannot disagree about when something happened because one call writes both.

**Only what a client can hold offline is in it.** An event about a role's grants is real and is in
the trail; it is not in the feed, because no phone holds roles offline. And a refused action
produces no change: nothing happened, so there is nothing to fetch.

**The change type is declared, not guessed.** `CHANGE_TYPE_FOR_ACTION` names the creating
actions, and a test scans the services for every action string they pass to the recorder and
fails when one is missing from the map - so the map cannot fall behind the code.

**Pulling is filtered by what the caller may read.** A salesperson gets the catalogue, the
customers and the sales, and never an expense; a caller holding none of the read permissions the
feed covers is refused rather than handed an empty page that looks like "nothing changed".
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.errors import AuthorizationError
from ahia.core.permissions.permissions_registry import permission_codes_for_role
from ahia.core.tenant_context import TenantContext, build_tenant_context
from ahia.crud import sync_change_crud, tenant_crud
from ahia.models.entities.audit_event_model import AuditOutcome
from ahia.models.entities.sync_change_model import (
    SYNCHRONIZABLE_ENTITY_TYPES,
    ChangeType,
)
from ahia.models.entities.tenant_model import TenantModel
from ahia.services.audit_event_service import AuditEventService
from ahia.services.sync_change_service import (
    CHANGE_TYPE_FOR_ACTION,
    READ_PERMISSION_FOR_ENTITY_TYPE,
    SyncChangeService,
)

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 14, 16, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)

SERVICES_ROOT = Path(__file__).resolve().parents[2] / "src" / "ahia" / "services"


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
        await connection.execute(text("TRUNCATE TABLE sync_changes, audit_events, tenants CASCADE"))
    try:
        yield instance
    finally:
        await instance.dispose()


@pytest.fixture
def change_service(database: Database) -> SyncChangeService:
    return SyncChangeService(unit_of_work_factory=database.unit_of_work_factory())


@pytest.fixture
def audit_service(database: Database, change_service: SyncChangeService) -> AuditEventService:
    return AuditEventService(
        unit_of_work_factory=database.unit_of_work_factory(),
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


def context_for(tenant_id: UUID, role_name: str) -> TenantContext:
    return build_tenant_context(
        user_id=uuid4(),
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=permission_codes_for_role(role_name),
        role_name=role_name,
    )


async def record(
    audit_service: AuditEventService,
    database: Database,
    tenant_context: TenantContext,
    *,
    action: str,
    entity_type: str,
    entity_id: UUID | None = None,
    outcome: AuditOutcome = AuditOutcome.SUCCEEDED,
    now: datetime = NOW,
) -> None:
    async with database.transaction_scope() as unit_of_work:
        await audit_service.record_audit_event(
            unit_of_work.session_handle,
            tenant_context,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id if entity_id is not None else uuid4(),
            outcome=outcome,
            now=now,
        )
        await unit_of_work.commit()


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_recorded_action_writes_a_change_in_the_same_transaction(
    audit_service: AuditEventService,
    change_service: SyncChangeService,
    database: Database,
    tenant_id: UUID,
) -> None:
    context = context_for(tenant_id, "OWNER")
    entity_id = uuid4()

    await record(
        audit_service,
        database,
        context,
        action="create_product",
        entity_type="product",
        entity_id=entity_id,
    )

    page = await change_service.pull_changes(context, after_sequence=0)

    assert [change.entity_id for change in page.changes] == [entity_id]
    assert page.changes[0].change_type is ChangeType.CREATED
    assert page.changes[0].occurred_at == NOW
    assert page.latest_sequence == page.changes[0].change_sequence


@pytest.mark.integration
async def test_a_refused_action_writes_no_change(
    audit_service: AuditEventService,
    change_service: SyncChangeService,
    database: Database,
    tenant_id: UUID,
) -> None:
    """Nothing happened, so there is nothing for a device to fetch."""
    context = context_for(tenant_id, "OWNER")

    await record(
        audit_service,
        database,
        context,
        action="cancel_sale",
        entity_type="sale",
        outcome=AuditOutcome.DENIED,
    )

    page = await change_service.pull_changes(context, after_sequence=0)

    assert page.changes == []
    assert page.latest_sequence == 0


@pytest.mark.integration
async def test_an_entity_a_client_does_not_hold_offline_is_not_in_the_feed(
    audit_service: AuditEventService,
    change_service: SyncChangeService,
    database: Database,
    tenant_id: UUID,
) -> None:
    """A role's grants are real and are in the trail; no phone holds roles offline."""
    context = context_for(tenant_id, "OWNER")

    await record(
        audit_service,
        database,
        context,
        action="update_role_permissions",
        entity_type="role",
    )
    await record(
        audit_service,
        database,
        context,
        action="create_product",
        entity_type="product",
    )

    async with database.transaction_scope() as unit_of_work:
        changes = await sync_change_crud.changes_after(
            unit_of_work.session_handle, tenant_id, after_sequence=0
        )

    assert [change.entity_type for change in changes] == ["product"]


@pytest.mark.integration
async def test_the_feed_is_scoped_to_its_business(
    audit_service: AuditEventService,
    change_service: SyncChangeService,
    database: Database,
    tenant_id: UUID,
) -> None:
    other_tenant = await insert_tenant(database)
    await record(
        audit_service,
        database,
        context_for(tenant_id, "OWNER"),
        action="create_product",
        entity_type="product",
    )

    page = await change_service.pull_changes(context_for(other_tenant, "OWNER"), after_sequence=0)

    assert page.changes == []
    assert page.latest_sequence == 0


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_feed_reads_forward_from_cursor(
    audit_service: AuditEventService,
    change_service: SyncChangeService,
    database: Database,
    tenant_id: UUID,
) -> None:
    context = context_for(tenant_id, "OWNER")
    for entity_type in ("product", "customer", "sale"):
        await record(
            audit_service,
            database,
            context,
            action="create_product",
            entity_type=entity_type,
        )

    first_page = await change_service.pull_changes(context, after_sequence=0)
    second_page = await change_service.pull_changes(
        context, after_sequence=first_page.changes[0].change_sequence
    )

    assert [change.entity_type for change in first_page.changes] == [
        "product",
        "customer",
        "sale",
    ]
    assert [change.entity_type for change in second_page.changes] == ["customer", "sale"]


@pytest.mark.integration
async def test_a_page_says_whether_there_is_more(
    audit_service: AuditEventService,
    change_service: SyncChangeService,
    database: Database,
    tenant_id: UUID,
) -> None:
    context = context_for(tenant_id, "OWNER")
    for _ in range(3):
        await record(
            audit_service, database, context, action="create_product", entity_type="product"
        )

    page = await change_service.pull_changes(context, after_sequence=0, limit=2)
    all_changes = await change_service.pull_changes(context, after_sequence=0, limit=10)

    assert len(page.changes) == 2
    assert page.has_more is True
    assert len(all_changes.changes) == 3
    # The sequence is global, so the assertion is about the feed's own last entry rather than
    # about a number this test could predict.
    assert page.latest_sequence == all_changes.changes[-1].change_sequence
    assert all_changes.has_more is False


@pytest.mark.integration
async def test_a_salesperson_is_not_told_about_expenses(
    audit_service: AuditEventService,
    change_service: SyncChangeService,
    database: Database,
    tenant_id: UUID,
) -> None:
    await record(
        audit_service,
        database,
        context_for(tenant_id, "OWNER"),
        action="record_expense",
        entity_type="expense",
    )
    await record(
        audit_service,
        database,
        context_for(tenant_id, "OWNER"),
        action="create_product",
        entity_type="product",
    )

    page = await change_service.pull_changes(context_for(tenant_id, "SALES"), after_sequence=0)

    assert [change.entity_type for change in page.changes] == ["product"]


@pytest.mark.integration
async def test_a_caller_holding_no_read_permission_is_refused(
    change_service: SyncChangeService, tenant_id: UUID
) -> None:
    """An empty page looks like "nothing changed", so the refusal is the honest answer."""
    context = build_tenant_context(
        user_id=uuid4(),
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=frozenset(),
        role_name="NONE",
    )

    with pytest.raises(AuthorizationError):
        await change_service.pull_changes(context, after_sequence=0)


# ---------------------------------------------------------------------------
# The declared vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_every_action_the_services_record_has_a_declared_change_type() -> None:
    """So the map cannot fall behind the code that writes the events."""
    recorded_actions: set[str] = set()
    for path in sorted(SERVICES_ROOT.glob("*_service.py")):
        source = path.read_text(encoding="utf-8")
        recorded_actions.update(re.findall(r'action="([a-z0-9_]+)"', source))

    # Reading the category vocabulary is not a mutation and records nothing; every other action
    # string in the services is passed to the recorder and must be classified.
    known = set(CHANGE_TYPE_FOR_ACTION)
    unknown = {
        action
        for action in recorded_actions
        if action not in known and action not in {"list_expense_categories"}
    }
    assert not unknown, (
        "these recorded actions have no declared change type, so the feed would call them "
        f"updates by default: {sorted(unknown)}"
    )


@pytest.mark.unit
def test_every_synchronizable_entity_type_has_a_read_permission() -> None:
    """A feed entry nobody can be authorized to read is an entry nobody receives."""
    assert set(READ_PERMISSION_FOR_ENTITY_TYPE) == SYNCHRONIZABLE_ENTITY_TYPES


@pytest.mark.unit
def test_the_creating_actions_are_the_ones_that_create_something() -> None:
    assert CHANGE_TYPE_FOR_ACTION["create_product"] is ChangeType.CREATED
    assert CHANGE_TYPE_FOR_ACTION["complete_sale"] is ChangeType.CREATED
    assert CHANGE_TYPE_FOR_ACTION["reverse_expense"] is ChangeType.UPDATED
