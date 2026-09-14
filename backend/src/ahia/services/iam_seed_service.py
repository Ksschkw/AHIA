"""Provisioning the permission registry into the database.

The registry in `core.permissions` is the declaration: what capabilities exist and
which bundles they form. This service is how that declaration becomes rows, so the
API can list roles and permissions without reading Python, and so a tenant's own
role can later be resolved the same way a system role is.

Two properties matter more than the mechanics.

Idempotent
    It runs on every deployment. Running it twice must change nothing and must not
    fail, or a rollout becomes an outage.

Convergent
    It does not merely add. If a permission was removed from a bundle in code, the
    grant is removed here too, because the registry is the source of truth and a
    stale grant is a capability nobody intended to keep. Removals are logged.

It never touches a tenant's own roles. A custom role belongs to a business, and
provisioning is not the place to decide what that business needs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.errors import DomainError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions.permissions_registry import (
    ALL_PERMISSIONS,
    SYSTEM_ROLES,
    validate_registry,
)
from ahia.crud import permission_crud, role_crud, role_permission_crud
from ahia.models.entities.permission_model import PermissionModel
from ahia.models.entities.role_model import RoleModel
from ahia.services.audit_event_service import AuditEventService
from ahia.services.permission_service import PermissionService

_IAM_SEED_LOGGER_NAME: Final[str] = "ahia.services.iam_seed"

#: The permission required to run provisioning from an API surface rather than at
#: startup. Provisioning changes what every business can do, so it is owner-level.
SEED_PERMISSION: Final[str] = "tenants.deactivate"


@dataclass(slots=True)
class SeedReport:
    """What provisioning changed.

    Reported rather than assumed: a deployment log that says "permissions: 0
    created, 2 updated, 1 removed" answers the question "did the rollout take
    effect" without anyone opening a database client.
    """

    permissions_created: int = 0
    permissions_updated: int = 0
    roles_created: int = 0
    roles_updated: int = 0
    grants_added: int = 0
    grants_removed: int = 0
    role_names: list[str] = field(default_factory=list)

    @property
    def changed_anything(self) -> bool:
        return any(
            (
                self.permissions_created,
                self.permissions_updated,
                self.roles_created,
                self.roles_updated,
                self.grants_added,
                self.grants_removed,
            )
        )

    def as_log_fields(self) -> dict[str, object]:
        return {
            "permissions_created": self.permissions_created,
            "permissions_updated": self.permissions_updated,
            "roles_created": self.roles_created,
            "roles_updated": self.roles_updated,
            "grants_added": self.grants_added,
            "grants_removed": self.grants_removed,
            "role_names": sorted(self.role_names),
        }


@dataclass(frozen=True, slots=True)
class RegistryDisagreement:
    """One way the database and the registry differ."""

    kind: str
    detail: str


class IamSeedService:
    """Installs the declared registry into the database, idempotently."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._logger = (logger or get_logger(_IAM_SEED_LOGGER_NAME)).bind(
            component="iam_seed_service", layer="service"
        )

    async def install_registry(self) -> SeedReport:
        """Write the registry into the database and report what changed.

        A registry that is internally inconsistent is refused before anything is
        written: provisioning a broken bundle would install a permission model
        that does not mean what it says.
        """
        try:
            validate_registry()
        except ValueError as invalid_registry:
            raise DomainError(
                operation="install_permission_registry",
                entity="permission",
                detail=f"the registry is inconsistent: {invalid_registry}",
            ) from invalid_registry

        now = datetime.now(UTC)
        report = SeedReport()
        report.role_names.extend(sorted(SYSTEM_ROLES))

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle

            permission_ids = await self._provision_permissions(session, now, report)
            for role_name, role_definition in SYSTEM_ROLES.items():
                await self._provision_role(
                    session,
                    name=role_name,
                    description=role_definition.description,
                    permission_codes=role_definition.permissions,
                    permission_ids=permission_ids,
                    now=now,
                    report=report,
                )
            await unit_of_work.commit()

        self._logger.info("permission_registry_installed", **report.as_log_fields())
        return report

    async def _provision_permissions(
        self,
        session: object,
        now: datetime,
        report: SeedReport,
    ) -> dict[str, UUID]:
        """Create or update every declared permission, returning code to identifier."""
        permission_ids: dict[str, UUID] = {}
        for definition in ALL_PERMISSIONS:
            existing = await permission_crud.get_by_code(session, definition.code)  # type: ignore[arg-type]
            if existing is None:
                created = await permission_crud.create(
                    session,  # type: ignore[arg-type]
                    PermissionModel(
                        id=uuid4(),
                        code=definition.code,
                        module=definition.module,
                        description=definition.description,
                    ),
                )
                permission_ids[created.code] = created.id
                report.permissions_created += 1
                continue

            if (
                existing.description != definition.description
                or existing.module != definition.module
            ):
                updated = await permission_crud.update(
                    session,  # type: ignore[arg-type]
                    PermissionModel(
                        id=existing.id,
                        code=existing.code,
                        module=definition.module,
                        description=definition.description,
                    ),
                )
                permission_ids[updated.code] = updated.id
                report.permissions_updated += 1
                continue

            permission_ids[existing.code] = existing.id
        return permission_ids

    async def _provision_role(
        self,
        session: object,
        *,
        name: str,
        description: str,
        permission_codes: frozenset[str],
        permission_ids: dict[str, UUID],
        now: datetime,
        report: SeedReport,
    ) -> None:
        """Create or converge one system role and its grants."""
        role = await role_crud.get_system_role_by_name(session, name)  # type: ignore[arg-type]
        if role is None:
            role = await role_crud.create(
                session,  # type: ignore[arg-type]
                RoleModel.system_role(
                    role_id=uuid4(),
                    name=name,
                    description=description,
                    now=now,
                ),
            )
            report.roles_created += 1
        elif role.description != description:
            role = await role_crud.update(
                session,  # type: ignore[arg-type]
                RoleModel(
                    id=role.id,
                    name=role.name,
                    description=description,
                    is_system_role=True,
                    tenant_id=None,
                    created_at=role.created_at,
                    updated_at=now,
                ),
            )
            report.roles_updated += 1

        wanted_ids = {permission_ids[code] for code in permission_codes if code in permission_ids}
        granted_ids = set(
            await role_permission_crud.list_permission_ids_for_role(session, role.id)  # type: ignore[arg-type]
        )

        to_add = sorted(wanted_ids - granted_ids)
        to_remove = sorted(granted_ids - wanted_ids)

        report.grants_added += await role_permission_crud.add_grants(
            session,  # type: ignore[arg-type]
            role_id=role.id,
            permission_ids=to_add,
        )
        report.grants_removed += await role_permission_crud.remove_grants(
            session,  # type: ignore[arg-type]
            role_id=role.id,
            permission_ids=to_remove,
        )

        if to_remove:
            # A grant that disappeared from code is a capability nobody decided to
            # keep, so its removal is worth a line of its own.
            self._logger.warning(
                "role_grants_removed_by_provisioning",
                role_name=name,
                removed_grant_count=len(to_remove),
            )

    async def find_disagreements(self) -> list[RegistryDisagreement]:
        """Return every way the database differs from the declaration.

        Used by tests and by an operational check. An empty list means the two
        agree; anything else means authorization would resolve differently from
        what the code says, which is exactly the failure this guards against.
        """
        # A read-only helper: the permission service needs a recorder to be constructed, and
        # nothing on this path writes an event.
        permission_service = PermissionService(
            unit_of_work_factory=self._unit_of_work_factory,
            audit_event_service=AuditEventService(unit_of_work_factory=self._unit_of_work_factory),
        )
        disagreements: list[RegistryDisagreement] = []

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            stored_permissions = {item.code for item in await permission_crud.list_all(session)}
            for definition in ALL_PERMISSIONS:
                if definition.code not in stored_permissions:
                    disagreements.append(
                        RegistryDisagreement(
                            kind="permission_missing",
                            detail=f"{definition.code} is declared but not provisioned",
                        )
                    )
            declared_codes = {definition.code for definition in ALL_PERMISSIONS}
            for code in sorted(stored_permissions - declared_codes):
                disagreements.append(
                    RegistryDisagreement(
                        kind="permission_undeclared",
                        detail=f"{code} is provisioned but not declared",
                    )
                )

            for role_name, role_definition in SYSTEM_ROLES.items():
                resolved = await permission_service.resolve_role_permissions(
                    role_name, tenant_id=None
                )
                if resolved != role_definition.permissions:
                    missing = sorted(role_definition.permissions - resolved)
                    extra = sorted(resolved - role_definition.permissions)
                    disagreements.append(
                        RegistryDisagreement(
                            kind="role_bundle_differs",
                            detail=(f"{role_name}: missing {missing}, unexpected {extra}"),
                        )
                    )
        return disagreements
