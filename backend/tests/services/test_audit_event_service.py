"""Tests for the audit use cases.

Two subjects.

**Writing happens in the caller's transaction.** The event and the change it describes land
together or not at all - asserted by breaking the change after the event was written and
checking that nothing survives. An audit trail that can claim something happened that did not
is worse than no trail, because it is believed.

**Reading is owner-facing and scoped.** `reports.read` is what the query surface needs, a
salesperson does not hold it, and a second business sees none of the first business's events
through any path.
"""

from __future__ import annotations

import inspect
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.errors import AuthorizationError
from ahia.core.permissions.permissions_registry import permission_codes_for_role
from ahia.core.tenant_context import TenantContext, build_tenant_context
from ahia.crud import audit_event_crud, device_crud, tenant_crud, user_crud
from ahia.models.entities.audit_event_model import AuditOutcome
from ahia.models.entities.device_model import DeviceModel
from ahia.models.entities.tenant_model import TenantModel
from ahia.models.entities.user_model import UserModel
from ahia.services.audit_event_service import AuditEventService

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=2)


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
            text("TRUNCATE TABLE audit_events, devices, tenants, users CASCADE")
        )
    try:
        yield instance
    finally:
        await instance.dispose()


@pytest.fixture
def service(database: Database) -> AuditEventService:
    return AuditEventService(unit_of_work_factory=database.unit_of_work_factory())


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


@pytest.fixture
async def tenant_id(database: Database) -> UUID:
    return await insert_tenant(database)


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


async def insert_device(database: Database, *, tenant_id: UUID, actor_id: UUID) -> UUID:
    """Register a device the way the device use case does, so the foreign key holds."""
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
    """The person the events in these tests are attributed to.

    A required fixture rather than a random identifier: `audit_events.actor_id` is a foreign key
    to `users`, and an actor who does not exist is not an actor.
    """
    return await insert_user(database)


def context_for(tenant_id: UUID, role_name: str, *, actor_id: UUID) -> TenantContext:
    return build_tenant_context(
        user_id=actor_id,
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=permission_codes_for_role(role_name),
        role_name=role_name,
    )


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_an_event_is_written_inside_the_callers_transaction(
    service: AuditEventService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    context = context_for(tenant_id, "OWNER", actor_id=actor_id)

    async with database.transaction_scope() as unit_of_work:
        stored = await service.record_audit_event(
            unit_of_work.session_handle,
            context,
            action="record_expense",
            entity_type="expense",
            entity_id=uuid4(),
            now=NOW,
            detail={"category": "TRANSPORT"},
        )
        await unit_of_work.commit()

    assert stored.action == "record_expense"
    assert stored.actor_id == context.user_id
    assert stored.tenant_id == tenant_id
    assert stored.occurred_at == NOW
    assert stored.outcome is AuditOutcome.SUCCEEDED

    async with database.transaction_scope() as unit_of_work:
        listed = await audit_event_crud.list_for_tenant(unit_of_work.session_handle, tenant_id)
    assert len(listed) == 1


@pytest.mark.integration
async def test_an_event_does_not_survive_a_transaction_that_fails(
    service: AuditEventService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    """The trail must never claim something happened that did not."""
    context = context_for(tenant_id, "OWNER", actor_id=actor_id)

    with pytest.raises(RuntimeError):
        async with database.transaction_scope() as unit_of_work:
            await service.record_audit_event(
                unit_of_work.session_handle,
                context,
                action="complete_sale",
                entity_type="sale",
                now=NOW,
            )
            raise RuntimeError("the change this event describes failed")

    async with database.transaction_scope() as unit_of_work:
        listed = await audit_event_crud.list_for_tenant(unit_of_work.session_handle, tenant_id)

    assert listed == [], "a rolled-back change must leave no trail entry behind"


@pytest.mark.integration
async def test_the_device_and_operation_come_from_the_context_and_the_arguments(
    service: AuditEventService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    device_id = await insert_device(database, tenant_id=tenant_id, actor_id=actor_id)
    operation_id = uuid4()
    context = build_tenant_context(
        user_id=actor_id,
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=permission_codes_for_role("OWNER"),
        role_name="OWNER",
        device_id=device_id,
    )

    async with database.transaction_scope() as unit_of_work:
        stored = await service.record_audit_event(
            unit_of_work.session_handle,
            context,
            action="record_expense",
            entity_type="expense",
            operation_id=operation_id,
            now=NOW,
        )
        await unit_of_work.commit()

    assert stored.device_id == device_id
    assert stored.operation_id == operation_id


@pytest.mark.unit
def test_recording_takes_a_session_rather_than_opening_its_own_transaction() -> None:
    """The mechanism M14.1.3 wires into every use case: no unit of work of its own."""
    parameters = inspect.signature(AuditEventService.record_audit_event).parameters

    assert "session" in parameters
    assert "unit_of_work" not in parameters


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_an_owner_reads_the_trail_most_recent_first(
    service: AuditEventService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    context = context_for(tenant_id, "OWNER", actor_id=actor_id)
    for action, moment in (("create_product", NOW), ("complete_sale", LATER)):
        async with database.transaction_scope() as unit_of_work:
            await service.record_audit_event(
                unit_of_work.session_handle,
                context,
                action=action,
                entity_type="sale" if action == "complete_sale" else "product",
                now=moment,
            )
            await unit_of_work.commit()

    events = await service.list_events(context)

    assert [event.action for event in events] == ["complete_sale", "create_product"]


@pytest.mark.integration
async def test_a_period_narrows_the_trail(
    service: AuditEventService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    context = context_for(tenant_id, "OWNER", actor_id=actor_id)
    for action, moment in (("create_product", NOW), ("complete_sale", LATER)):
        async with database.transaction_scope() as unit_of_work:
            await service.record_audit_event(
                unit_of_work.session_handle, context, action=action, entity_type="sale", now=moment
            )
            await unit_of_work.commit()

    events = await service.list_events(context, since=NOW, until=LATER)

    assert [event.action for event in events] == ["create_product"]


@pytest.mark.integration
async def test_a_record_s_history_reads_from_the_beginning(
    service: AuditEventService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    context = context_for(tenant_id, "OWNER", actor_id=actor_id)
    entity_id = uuid4()
    for action, moment in (("record_expense", NOW), ("reverse_expense", LATER)):
        async with database.transaction_scope() as unit_of_work:
            await service.record_audit_event(
                unit_of_work.session_handle,
                context,
                action=action,
                entity_type="expense",
                entity_id=entity_id,
                now=moment,
            )
            await unit_of_work.commit()

    history = await service.get_entity_history(context, entity_type="expense", entity_id=entity_id)

    assert [event.action for event in history] == ["record_expense", "reverse_expense"]


@pytest.mark.integration
async def test_the_trail_can_be_narrowed_to_one_person(
    service: AuditEventService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    own = context_for(tenant_id, "OWNER", actor_id=actor_id)
    somebody_else = context_for(tenant_id, "OWNER", actor_id=await insert_user(database))
    for context in (own, somebody_else):
        async with database.transaction_scope() as unit_of_work:
            await service.record_audit_event(
                unit_of_work.session_handle,
                context,
                action="create_product",
                entity_type="product",
                now=NOW,
            )
            await unit_of_work.commit()

    events = await service.list_events(own, actor_id=actor_id)

    assert len(events) == 1
    assert events[0].actor_id == actor_id


@pytest.mark.integration
async def test_a_salesperson_cannot_read_the_trail(
    service: AuditEventService,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    """The trail names who did what, and it is not a screen a salesperson needs."""
    with pytest.raises(AuthorizationError):
        await service.list_events(context_for(tenant_id, "SALES", actor_id=actor_id))

    with pytest.raises(AuthorizationError):
        await service.get_entity_history(
            context_for(tenant_id, "SALES", actor_id=actor_id),
            entity_type="expense",
            entity_id=uuid4(),
        )


@pytest.mark.integration
async def test_another_business_sees_none_of_the_trail(
    service: AuditEventService,
    database: Database,
    tenant_id: UUID,
    actor_id: UUID,
) -> None:
    owner = context_for(tenant_id, "OWNER", actor_id=actor_id)
    async with database.transaction_scope() as unit_of_work:
        await service.record_audit_event(
            unit_of_work.session_handle,
            owner,
            action="complete_sale",
            entity_type="sale",
            now=NOW,
        )
        await unit_of_work.commit()
    other_tenant = await insert_tenant(database, name="Ada Provisions")
    intruder = context_for(other_tenant, "OWNER", actor_id=actor_id)

    assert await service.list_events(intruder) == []
    assert await service.get_entity_history(intruder, entity_type="sale", entity_id=uuid4()) == []
