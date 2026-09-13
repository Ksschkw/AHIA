"""Authorization resolution: what a membership may do, and who may change that.

Everything here answers one of two questions. **Resolution** asks what a role
grants, and is on the hot path of every tenant-scoped request. **Administration**
asks who may change a role, and is where privilege escalation would happen if it
were not refused explicitly.

Resolution is deny-by-default. A role that cannot be found resolves to no
permissions, a missing grant resolves to no permissions, and an error resolving is
a denial rather than an approval. The failure mode is "you cannot do this", never
"you can do this because the answer was unclear".

Escalation is refused by a rule rather than by a convention: a caller may not grant
a permission they do not themselves hold. Without it, `staff.update` would be
equivalent to `tenants.deactivate` after two requests, which is the classic
privilege-escalation path in a system with editable roles.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.errors import AuthorizationError, ConflictError, DomainError, NotFoundError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions.permissions_registry import PERMISSION_CODES, SYSTEM_ROLES
from ahia.core.permissions.staff_permissions import STAFF_READ, STAFF_UPDATE
from ahia.core.tenant_context import TenantContext
from ahia.crud import permission_crud, role_crud, role_permission_crud
from ahia.models.entities.permission_model import PermissionModel
from ahia.models.entities.role_model import RoleModel

_PERMISSION_LOGGER_NAME: Final[str] = "ahia.services.permission"

#: The permission required to create or change a tenant-defined role. Role
#: administration is not a separate capability in the product's list, and it is the
#: same act as changing what a member may do, so it uses the same permission.
MANAGE_ROLES_PERMISSION: Final[str] = STAFF_UPDATE

#: Reading the catalogue of roles and permissions needs a permission, but not a new
#: one: it is the same capability as seeing who is in the business, because a person
#: asks both questions together when deciding what to hand out.
STAFF_READ_PERMISSION: Final[str] = STAFF_READ

_MAXIMUM_CUSTOM_ROLES_PER_TENANT: Final[int] = 20


@dataclass(frozen=True, slots=True)
class RoleView:
    """A role and the codes it grants."""

    role: RoleModel
    permission_codes: frozenset[str]


class PermissionService:
    """Resolves and administers roles and permissions."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._logger = (logger or get_logger(_PERMISSION_LOGGER_NAME)).bind(
            component="permission_service", layer="service"
        )

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    async def resolve_role_permissions(
        self,
        role_name: str,
        *,
        tenant_id: UUID | None,
    ) -> frozenset[str]:
        """Return the permission codes a role grants, or nothing.

        A tenant's own role shadows a system role of the same name, so a business
        that defines its own SUPERVISOR gets its definition. A role that does not
        exist resolves to the empty set: deny by default, and the caller logs it.
        """
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            if tenant_id is None:
                role = await role_crud.get_system_role_by_name(session, role_name)
            else:
                role = await role_crud.get_role_for_tenant(
                    session, tenant_id=tenant_id, name=role_name
                )
            if role is None:
                self._logger.error(
                    "role_not_provisioned",
                    reason="role_missing",
                    role_name=role_name,
                    tenant_id=str(tenant_id) if tenant_id else None,
                )
                return frozenset()

            permission_ids = await role_permission_crud.list_permission_ids_for_role(
                session, role.id
            )
            codes: set[str] = set()
            for permission_id in permission_ids:
                permission = await permission_crud.get_by_id(session, permission_id)
                if permission is not None:
                    codes.add(permission.code)
        return frozenset(codes)

    async def resolve_permissions_for_membership(
        self,
        *,
        role_name: str,
        tenant_id: UUID,
    ) -> frozenset[str]:
        """Return what one membership may do, resolved from its role."""
        return await self.resolve_role_permissions(role_name, tenant_id=tenant_id)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    async def list_permissions(self, tenant_context: TenantContext) -> list[PermissionModel]:
        """Return every capability the deployment has.

        Reference data, not tenant data: the catalogue is the same in every
        business and contains no record of anybody. Any active member may read it,
        because a person cannot judge a role they are being given without knowing
        what it means, and requiring staff.read would hide the meaning of a role
        from the very people who hold it.

        The check that matters already happened: the caller has an authorized
        tenant context, so they are an active member of a real business.
        """
        self._logger.info(
            "permission_catalogue_read",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await permission_crud.list_all(unit_of_work.session_handle)

    async def list_roles(self, tenant_context: TenantContext) -> list[RoleView]:
        """Return the roles available to this business, with their codes.

        A member may see the roles in their own business, including the custom
        ones, for the same reason they may see the permission catalogue: a role
        they cannot inspect is a role they cannot consent to.
        """
        self._logger.info(
            "role_catalogue_read",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            roles = await role_crud.list_for_tenant(session, tenant_context.tenant_id)
            views: list[RoleView] = []
            for role in roles:
                permission_ids = await role_permission_crud.list_permission_ids_for_role(
                    session, role.id
                )
                codes: set[str] = set()
                for permission_id in permission_ids:
                    permission = await permission_crud.get_by_id(session, permission_id)
                    if permission is not None:
                        codes.add(permission.code)
                views.append(RoleView(role=role, permission_codes=frozenset(codes)))
        return views

    # ------------------------------------------------------------------
    # Administration
    # ------------------------------------------------------------------

    async def create_custom_role(
        self,
        tenant_context: TenantContext,
        *,
        name: str,
        description: str,
        permission_codes: Iterable[str],
    ) -> RoleView:
        """Create a role for one business.

        The requested permissions are checked against the caller's own before
        anything is written: a person cannot create a role more powerful than
        themselves, which is what stops `staff.update` from becoming a route to
        every other permission.
        """
        tenant_context.require_permission(
            MANAGE_ROLES_PERMISSION,
            operation="create_custom_role",
            resource_type="role",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )

        requested = frozenset(permission_codes)
        self._reject_unknown_codes(requested, operation="create_custom_role")
        self._reject_escalation(tenant_context, requested=requested, operation="create_custom_role")
        self._reject_reserved_name(name)

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            existing_custom_roles = [
                role
                for role in await role_crud.list_for_tenant(session, tenant_context.tenant_id)
                if role.is_custom
            ]
            if len(existing_custom_roles) >= _MAXIMUM_CUSTOM_ROLES_PER_TENANT:
                raise DomainError(
                    operation="create_custom_role",
                    entity="role",
                    identifier=str(tenant_context.tenant_id),
                    detail=(
                        f"this business already has {len(existing_custom_roles)} custom roles, "
                        f"the maximum of {_MAXIMUM_CUSTOM_ROLES_PER_TENANT}"
                    ),
                )

            role = await role_crud.create(
                session,
                RoleModel.custom_role(
                    role_id=uuid4(),
                    tenant_id=tenant_context.tenant_id,
                    name=name,
                    description=description,
                    now=now,
                ),
            )
            permissions = await permission_crud.list_by_codes(session, requested)
            await role_permission_crud.add_grants(
                session,
                role_id=role.id,
                permission_ids=[permission.id for permission in permissions],
            )
            await unit_of_work.commit()

        self._logger.info(
            "custom_role_created",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            role_name=role.name,
            permission_count=len(requested),
        )
        return RoleView(role=role, permission_codes=requested)

    async def update_role_permissions(
        self,
        tenant_context: TenantContext,
        *,
        role_name: str,
        permission_codes: Iterable[str],
    ) -> RoleView:
        """Replace the permission set of a business's own role.

        A system role cannot be edited: it is provisioned from code, and an edit
        here would be overwritten by the next deployment while appearing to work
        in the meantime.
        """
        tenant_context.require_permission(
            MANAGE_ROLES_PERMISSION,
            operation="update_role_permissions",
            resource_type="role",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )

        requested = frozenset(permission_codes)
        self._reject_unknown_codes(requested, operation="update_role_permissions")
        self._reject_escalation(
            tenant_context, requested=requested, operation="update_role_permissions"
        )

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            role = await role_crud.get_custom_role_for_tenant(
                session, tenant_id=tenant_context.tenant_id, name=role_name
            )
            if role is None:
                raise NotFoundError(
                    operation="update_role_permissions",
                    entity="role",
                    identifier=role_name,
                    detail="no custom role with that name exists in this business",
                )

            wanted = await permission_crud.list_by_codes(session, requested)
            wanted_ids = {permission.id for permission in wanted}
            granted_ids = set(
                await role_permission_crud.list_permission_ids_for_role(session, role.id)
            )
            await role_permission_crud.add_grants(
                session, role_id=role.id, permission_ids=sorted(wanted_ids - granted_ids)
            )
            await role_permission_crud.remove_grants(
                session, role_id=role.id, permission_ids=sorted(granted_ids - wanted_ids)
            )
            updated = await role_crud.update(
                session,
                RoleModel(
                    id=role.id,
                    name=role.name,
                    description=role.description,
                    is_system_role=False,
                    tenant_id=role.tenant_id,
                    created_at=role.created_at,
                    updated_at=now,
                ),
            )
            await unit_of_work.commit()

        self._logger.warning(
            "role_permissions_changed",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            role_name=updated.name,
            permission_count=len(requested),
            security_event="role_permissions_changed",
        )
        return RoleView(role=updated, permission_codes=requested)

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def _reject_escalation(
        self,
        tenant_context: TenantContext,
        *,
        requested: frozenset[str],
        operation: str,
    ) -> None:
        """Refuse to grant a permission the caller does not hold.

        Without this rule, anybody with the permission to change roles could grant
        themselves the rest of them, and every other check in the product would be
        decoration.
        """
        beyond_the_caller = sorted(requested - tenant_context.permissions)
        if not beyond_the_caller:
            return

        self._logger.error(
            "privilege_escalation_refused",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            operation=operation,
            refused_permissions=beyond_the_caller,
            security_event="privilege_escalation_refused",
        )
        raise AuthorizationError(
            operation=operation,
            entity="role",
            identifier=str(tenant_context.tenant_id),
            detail=(
                "refused to grant permissions the caller does not hold: "
                f"{', '.join(beyond_the_caller)}"
            ),
        )

    def _reject_unknown_codes(self, requested: frozenset[str], *, operation: str) -> None:
        """Refuse a code the application does not implement."""
        unknown = sorted(requested - PERMISSION_CODES)
        if not unknown:
            return
        raise DomainError(
            operation=operation,
            entity="permission",
            detail=f"unknown permission codes: {', '.join(unknown)}",
        )

    def _reject_reserved_name(self, name: str) -> None:
        """Refuse a custom role that would shadow a system role's name.

        A business may define its own roles, but not one called OWNER: the name is
        reserved for the provisioned role, and shadowing it would make an audit
        record ambiguous about which meaning applied.
        """
        if name.strip().upper() in SYSTEM_ROLES:
            raise ConflictError(
                operation="create_custom_role",
                entity="role",
                identifier=name,
                detail="that name belongs to a system role",
            )
