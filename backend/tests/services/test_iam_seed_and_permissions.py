"""Tests for permission provisioning and resolution.

The seed and the resolver are the two halves of one guarantee: what the code
declares is what the database grants, and what the database grants is what a
request is allowed to do. These tests are integration tests against real
PostgreSQL, because indexes, partial uniqueness and joins are the mechanism.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.errors import AuthorizationError, ConflictError, DomainError, NotFoundError
from ahia.core.permissions.permissions_registry import (
    ALL_PERMISSIONS,
    PERMISSION_CODES,
    SYSTEM_ROLES,
    permission_codes_for_role,
)
from ahia.core.tenant_context import build_tenant_context
from ahia.crud import permission_crud, role_crud, role_permission_crud, tenant_crud
from ahia.models.entities.role_model import RoleModel
from ahia.models.entities.tenant_model import TenantModel
from ahia.services.audit_event_service import AuditEventService
from ahia.services.iam_seed_service import IamSeedService
from ahia.services.permission_service import PermissionService

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)


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
            text("TRUNCATE TABLE role_permissions, roles, permissions CASCADE")
        )
    try:
        yield instance
    finally:
        await instance.dispose()


async def insert_tenant(database: Database, tenant_id: UUID) -> None:
    """Create the business a custom role will belong to.

    A custom role carries a foreign key to the business that owns it, because a role
    named SUPERVISOR in one business is a different role from SUPERVISOR in another.
    A test that invents a tenant identifier therefore has to create the business
    first, which is the order a real caller follows.
    """
    async with database.transaction_scope() as unit_of_work:
        await tenant_crud.create(
            unit_of_work.session_handle,
            TenantModel.create(
                tenant_id=tenant_id,
                name=f"Tenant {tenant_id.hex[:6]}",
                slug=f"tenant-{tenant_id.hex[:8]}",
                now=datetime.now(UTC),
            ),
        )
        await unit_of_work.commit()


@pytest.fixture
async def tenant_id(database: Database) -> UUID:
    identifier = uuid4()
    await insert_tenant(database, identifier)
    return identifier


@pytest.fixture
def seed_service(database: Database) -> IamSeedService:
    return IamSeedService(unit_of_work_factory=database.unit_of_work_factory())


@pytest.fixture
def permission_service(database: Database) -> PermissionService:
    return PermissionService(
        unit_of_work_factory=database.unit_of_work_factory(),
        audit_event_service=AuditEventService(unit_of_work_factory=database.unit_of_work_factory()),
    )


def build_owner_context(tenant_id: UUID | None = None) -> Any:
    """An OWNER context with every permission, as the seed would grant."""
    return build_tenant_context(
        user_id=uuid4(),
        tenant_id=tenant_id or uuid4(),
        membership_id=uuid4(),
        permission_codes=PERMISSION_CODES,
        role_name="OWNER",
    )


def build_sales_context(tenant_id: UUID | None = None) -> Any:
    return build_tenant_context(
        user_id=uuid4(),
        tenant_id=tenant_id or uuid4(),
        membership_id=uuid4(),
        permission_codes=permission_codes_for_role("SALES"),
        role_name="SALES",
    )


# ---------------------------------------------------------------------------
# Provisioning
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_seed_installs_every_declared_permission(seed_service: IamSeedService) -> None:
    report = await seed_service.install_registry()

    assert report.permissions_created == len(ALL_PERMISSIONS)
    assert report.roles_created == len(SYSTEM_ROLES)
    assert report.grants_added == sum(
        len(definition.permissions) for definition in SYSTEM_ROLES.values()
    )


@pytest.mark.integration
async def test_the_seed_is_idempotent(seed_service: IamSeedService) -> None:
    """A rollout runs it every time; the second run must change nothing."""
    await seed_service.install_registry()

    second_report = await seed_service.install_registry()

    assert second_report.changed_anything is False
    assert second_report.permissions_created == 0
    assert second_report.roles_created == 0
    assert second_report.grants_added == 0
    assert second_report.grants_removed == 0


@pytest.mark.integration
async def test_the_seed_converges_when_a_grant_disappears_from_code(
    seed_service: IamSeedService, database: Database, permission_service: PermissionService
) -> None:
    """A stale grant is a capability nobody decided to keep."""
    await seed_service.install_registry()
    role_name = "SALES"

    async with database.transaction_scope() as unit_of_work:
        session = unit_of_work.session_handle
        role = await _system_role(session, role_name)
        extra_permission = await _permission(session, "tenants.deactivate")
        await role_permission_crud.add_grants(
            session, role_id=role, permission_ids=[extra_permission]
        )
        await unit_of_work.commit()

    escalated = await permission_service.resolve_role_permissions(role_name, tenant_id=None)
    assert "tenants.deactivate" in escalated

    report = await seed_service.install_registry()

    assert report.grants_removed == 1
    restored = await permission_service.resolve_role_permissions(role_name, tenant_id=None)
    assert restored == permission_codes_for_role(role_name)


@pytest.mark.integration
async def test_the_database_agrees_with_the_registry(seed_service: IamSeedService) -> None:
    """The guard that makes the two sources of truth safe to have."""
    await seed_service.install_registry()

    disagreements = await seed_service.find_disagreements()

    assert disagreements == []


@pytest.mark.integration
async def test_a_disagreement_is_detected(seed_service: IamSeedService, database: Database) -> None:
    """If the check cannot fail, it is not a check."""
    await seed_service.install_registry()

    async with database.transaction_scope() as unit_of_work:
        session = unit_of_work.session_handle
        # A permission the SALES bundle actually contains; removing one it never
        # had would prove nothing.
        permission = await _permission(session, "sales.read")
        role_id = await _system_role(session, "SALES")
        await role_permission_crud.remove_grants(
            session, role_id=role_id, permission_ids=[permission]
        )
        await unit_of_work.commit()

    disagreements = await seed_service.find_disagreements()

    assert len(disagreements) == 1
    assert disagreements[0].kind == "role_bundle_differs"
    assert "sales.read" in disagreements[0].detail


@pytest.mark.integration
async def test_system_roles_are_unique_by_name_across_the_installation(
    seed_service: IamSeedService, database: Database
) -> None:
    """PostgreSQL treats nulls as distinct, so this relies on a partial index."""
    await seed_service.install_registry()

    async with database.transaction_scope() as unit_of_work:
        session = unit_of_work.session_handle
        now = datetime.now(UTC)
        with pytest.raises(ConflictError):
            await _create_role(
                session,
                RoleModel.system_role(
                    role_id=uuid4(), name="OWNER", description="Duplicate", now=now
                ),
            )


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_resolution_returns_the_bundles_the_registry_declares(
    seed_service: IamSeedService, permission_service: PermissionService
) -> None:
    await seed_service.install_registry()

    for role_name in SYSTEM_ROLES:
        resolved = await permission_service.resolve_role_permissions(role_name, tenant_id=None)
        assert resolved == permission_codes_for_role(role_name)


@pytest.mark.integration
async def test_an_unprovisioned_role_resolves_to_nothing(
    permission_service: PermissionService,
) -> None:
    """Deny by default: a role nobody provisioned grants nothing."""
    assert await permission_service.resolve_role_permissions("OWNER", tenant_id=None) == frozenset()
    assert (
        await permission_service.resolve_role_permissions("SUPERVISOR", tenant_id=None)
        == frozenset()
    )


@pytest.mark.integration
async def test_a_tenant_role_may_not_take_a_system_role_name(
    seed_service: IamSeedService, permission_service: PermissionService
) -> None:
    """Shadowing SALES would make an audit record ambiguous about which one applied.

    The resolved bundle for a system role name is therefore the system bundle, in
    every business, which is what makes a permission decision reproducible six
    months later.
    """
    await seed_service.install_registry()
    tenant_id = uuid4()

    with pytest.raises(ConflictError, match="system role"):
        await permission_service.create_custom_role(
            build_owner_context(tenant_id),
            name="SALES",
            description="This business's own idea of a salesperson",
            permission_codes=["products.read"],
        )

    resolve_for_tenant = await permission_service.resolve_permissions_for_membership(
        role_name="SALES", tenant_id=tenant_id
    )

    assert resolve_for_tenant == permission_codes_for_role("SALES")


# ---------------------------------------------------------------------------
# Administration and escalation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_business_can_create_its_own_role(
    seed_service: IamSeedService, permission_service: PermissionService, tenant_id: UUID
) -> None:
    await seed_service.install_registry()

    view = await permission_service.create_custom_role(
        build_owner_context(tenant_id),
        name="SUPERVISOR",
        description="Watches the shop",
        permission_codes=["products.read", "inventory.read"],
    )

    assert view.role.is_custom is True
    assert view.role.tenant_id == tenant_id
    assert view.permission_codes == frozenset({"products.read", "inventory.read"})

    resolved = await permission_service.resolve_permissions_for_membership(
        role_name="SUPERVISOR", tenant_id=tenant_id
    )
    assert resolved == frozenset({"products.read", "inventory.read"})


@pytest.mark.integration
async def test_a_custom_role_is_invisible_to_another_business(
    database: Database,
    seed_service: IamSeedService,
    permission_service: PermissionService,
    tenant_id: UUID,
) -> None:
    """Cross-tenant isolation for roles, not only for records."""
    await seed_service.install_registry()
    first_tenant = tenant_id
    second_tenant = uuid4()
    await insert_tenant(database, second_tenant)

    await permission_service.create_custom_role(
        build_owner_context(first_tenant),
        name="SUPERVISOR",
        description="First business only",
        permission_codes=["products.read"],
    )

    resolved_elsewhere = await permission_service.resolve_permissions_for_membership(
        role_name="SUPERVISOR", tenant_id=second_tenant
    )

    assert resolved_elsewhere == frozenset()


@pytest.mark.integration
async def test_granting_a_permission_the_caller_does_not_hold_is_refused(
    seed_service: IamSeedService, permission_service: PermissionService
) -> None:
    """The rule that stops staff.update from becoming every other permission."""
    await seed_service.install_registry()
    tenant_id = uuid4()
    manager_context = build_tenant_context(
        user_id=uuid4(),
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=permission_codes_for_role("MANAGER"),
        role_name="MANAGER",
    )

    with pytest.raises(AuthorizationError) as captured:
        await permission_service.create_custom_role(
            manager_context,
            name="SUPERVISOR",
            description="An attempt to grant more than the caller holds",
            permission_codes=["tenants.deactivate"],
        )

    assert "does not hold" in str(captured.value)
    assert captured.value.external().code == "FORBIDDEN"


@pytest.mark.integration
async def test_a_salesperson_cannot_manage_roles_at_all(
    seed_service: IamSeedService, permission_service: PermissionService
) -> None:
    await seed_service.install_registry()

    with pytest.raises(AuthorizationError):
        await permission_service.create_custom_role(
            build_sales_context(),
            name="SUPERVISOR",
            description="Not allowed",
            permission_codes=["products.read"],
        )


@pytest.mark.integration
async def test_an_unknown_permission_code_is_refused(
    seed_service: IamSeedService, permission_service: PermissionService
) -> None:
    await seed_service.install_registry()

    with pytest.raises(DomainError, match="unknown permission codes"):
        await permission_service.create_custom_role(
            build_owner_context(),
            name="SUPERVISOR",
            description="Refers to something that does not exist",
            permission_codes=["products.teleport"],
        )


@pytest.mark.integration
async def test_a_custom_role_cannot_shadow_a_system_role_name(
    seed_service: IamSeedService, permission_service: PermissionService
) -> None:
    """An audit record must not be ambiguous about which OWNER applied."""
    await seed_service.install_registry()

    with pytest.raises(ConflictError, match="system role"):
        await permission_service.create_custom_role(
            build_owner_context(),
            name="OWNER",
            description="An attempt to redefine the owner",
            permission_codes=["products.read"],
        )


@pytest.mark.integration
async def test_updating_a_businesss_own_role_replaces_its_permissions(
    seed_service: IamSeedService, permission_service: PermissionService, tenant_id: UUID
) -> None:
    await seed_service.install_registry()
    owner_context = build_owner_context(tenant_id)
    await permission_service.create_custom_role(
        owner_context,
        name="SUPERVISOR",
        description="Watches the shop",
        permission_codes=["products.read"],
    )

    updated = await permission_service.update_role_permissions(
        owner_context,
        role_name="SUPERVISOR",
        permission_codes=["products.read", "reports.read"],
    )

    assert updated.permission_codes == frozenset({"products.read", "reports.read"})
    resolved = await permission_service.resolve_permissions_for_membership(
        role_name="SUPERVISOR", tenant_id=tenant_id
    )
    assert resolved == frozenset({"products.read", "reports.read"})


@pytest.mark.integration
async def test_a_system_role_cannot_be_edited_through_the_api(
    seed_service: IamSeedService, permission_service: PermissionService
) -> None:
    """It is provisioned from code; an edit would be overwritten by the next deploy."""
    await seed_service.install_registry()

    with pytest.raises(NotFoundError):
        await permission_service.update_role_permissions(
            build_owner_context(),
            role_name="SALES",
            permission_codes=["tenants.deactivate"],
        )


@pytest.mark.integration
async def test_the_catalogue_is_readable_by_a_salesperson(
    seed_service: IamSeedService, permission_service: PermissionService
) -> None:
    """A person deciding whether to accept a role may see what exists."""
    await seed_service.install_registry()

    permissions = await permission_service.list_permissions(build_sales_context())
    roles = await permission_service.list_roles(build_sales_context())

    assert len(permissions) == len(ALL_PERMISSIONS)
    assert {view.role.name for view in roles} == set(SYSTEM_ROLES)
    assert all(view.role.is_system_role for view in roles)


@pytest.mark.integration
async def test_the_catalogue_lists_a_businesss_own_roles_too(
    seed_service: IamSeedService, permission_service: PermissionService, tenant_id: UUID
) -> None:
    await seed_service.install_registry()
    owner_context = build_owner_context(tenant_id)
    await permission_service.create_custom_role(
        owner_context,
        name="SUPERVISOR",
        description="Watches the shop",
        permission_codes=["products.read"],
    )

    roles = await permission_service.list_roles(owner_context)

    custom = [view for view in roles if view.role.is_custom]
    assert [view.role.name for view in custom] == ["SUPERVISOR"]
    assert custom[0].permission_codes == frozenset({"products.read"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _system_role(session: Any, name: str) -> UUID:
    role = await role_crud.get_system_role_by_name(session, name)
    assert role is not None
    return role.id


async def _permission(session: Any, code: str) -> UUID:
    permission = await permission_crud.get_by_code(session, code)
    assert permission is not None
    return permission.id


async def _create_role(session: Any, role: Any) -> None:
    await role_crud.create(session, role)
