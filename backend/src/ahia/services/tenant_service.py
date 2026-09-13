"""Tenant use cases: creating a business, reading it, changing it, closing it.

This service also owns tenant context resolution, which is the operation every
tenant-scoped request depends on. Resolution is the proof that separates a
requested tenant from an authorized one:

    JWT                    who the caller claims to be
     -> requested tenant    a path parameter, which is a hint
     -> membership lookup   the only source of truth
     -> active?             no, and the request is denied as if it were absent
     -> permissions         resolved from the role, not stored per request
     -> TenantContext       the object every service call receives

A tenant identifier from a URL is never treated as evidence of access. This is the
one place that decides, so there is one place to audit.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Never, Protocol
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.errors import ConflictError, InvalidInputError, NotFoundError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions.tenant_permissions import (
    TENANTS_DEACTIVATE,
    TENANTS_MANAGE,
    TENANTS_READ,
)
from ahia.core.slug import normalize_slug
from ahia.core.tenant_context import TenantContext, build_tenant_context
from ahia.crud import tenant_crud, tenant_membership_crud
from ahia.models.entities.tenant_membership_model import TenantMembershipModel
from ahia.models.entities.tenant_model import TenantModel

_TENANT_SERVICE_LOGGER_NAME: Final[str] = "ahia.services.tenant"

#: The role the creator of a business receives. The product's first-run journey is
#: "create account, create business, get to work", and an owner who had to be
#: invited to their own business would be a strange beginning.
OWNER_ROLE_NAME: Final[str] = "OWNER"

#: Profile fields a member may change. An allowlist, so a new column cannot become
#: externally writable merely by being added to the entity.
_EDITABLE_PROFILE_FIELDS: Final[frozenset[str]] = frozenset(
    {"name", "business_type", "phone", "email", "address", "city", "state"}
)

#: How many suffixes to try before giving up on a readable slug. Small on purpose:
#: a person who cannot get `obi-electronics` within a few attempts should be told
#: to choose, rather than receive `obi-electronics-47`.
_MAXIMUM_SLUG_ATTEMPTS: Final[int] = 9


@dataclass(frozen=True, slots=True)
class TenantMembershipView:
    """A business and the caller's role in it, for a list response."""

    tenant: TenantModel
    role_name: str


class PrincipalLike(Protocol):
    """The part of a principal this service needs.

    Typed structurally so the service depends on the concept rather than on the
    authentication module's concrete class, and a test can pass a small object.
    """

    @property
    def user_id(self) -> UUID: ...


class TenantService:
    """Business use cases."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._logger = (logger or get_logger(_TENANT_SERVICE_LOGGER_NAME)).bind(
            component="tenant_service", layer="service"
        )

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------

    async def create_tenant(
        self,
        principal: PrincipalLike,
        *,
        name: str,
        requested_slug: str | None = None,
        business_type: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        address: str | None = None,
        city: str | None = None,
        state: str | None = None,
        country: str = "NG",
        currency: str = "NGN",
        timezone: str = "Africa/Lagos",
    ) -> TenantModel:
        """Create a business and make the caller its owner, in one transaction.

        No permission is required beyond being authenticated: starting a business
        is how a person acquires their first permission, and requiring one would
        make the first-run journey impossible.

        The transaction matters. A business without its owner membership is a
        business nobody can reach, so the two rows commit together or not at all.
        """
        now = datetime.now(UTC)
        user_id = _principal_user_id(principal)

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            slug = await self._allocate_slug(
                session,
                requested_slug=requested_slug,
                name=name,
            )
            tenant = TenantModel.create(
                tenant_id=uuid4(),
                name=name,
                slug=slug,
                business_type=business_type,
                phone=phone,
                email=email,
                address=address,
                city=city,
                state=state,
                country=country,
                currency=currency,
                timezone=timezone,
                now=now,
            )
            stored_tenant = await tenant_crud.create(session, tenant)
            await tenant_membership_crud.create(
                session,
                TenantMembershipModel.activate_immediately(
                    membership_id=uuid4(),
                    tenant_id=stored_tenant.id,
                    user_id=user_id,
                    role_name=OWNER_ROLE_NAME,
                    now=now,
                ),
            )
            await unit_of_work.commit()

        self._logger.info(
            "tenant_created",
            tenant_id=str(stored_tenant.id),
            tenant_slug=stored_tenant.slug,
            owner_user_id=str(user_id),
            slug_was_requested=requested_slug is not None,
        )
        return stored_tenant

    async def _allocate_slug(
        self,
        session: object,
        *,
        requested_slug: str | None,
        name: str,
    ) -> str:
        """Return a free slug.

        A requested slug that is taken is a conflict, because the person chose it
        and silently receiving a different address would be worse than being told.
        A slug derived from the name is nudged with a numeric suffix instead, since
        the person never chose it and a working address is more useful than an
        error about a string they did not type.
        """
        if requested_slug is not None:
            candidate = normalize_slug(requested_slug)
            if await tenant_crud.slug_is_taken(session, candidate):  # type: ignore[arg-type]
                raise ConflictError(
                    operation="create_tenant",
                    entity="tenant",
                    detail="the requested slug is already taken",
                )
            return candidate

        base = normalize_slug(name)
        if not await tenant_crud.slug_is_taken(session, base):  # type: ignore[arg-type]
            return base

        for suffix in range(2, _MAXIMUM_SLUG_ATTEMPTS + 2):
            candidate = normalize_slug(f"{base}-{suffix}")
            if not await tenant_crud.slug_is_taken(session, candidate):  # type: ignore[arg-type]
                return candidate

        raise ConflictError(
            operation="create_tenant",
            entity="tenant",
            detail=(
                f"no free slug could be derived from the name after "
                f"{_MAXIMUM_SLUG_ATTEMPTS} attempts"
            ),
        )

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    async def list_own_tenants(self, principal: PrincipalLike) -> list[TenantMembershipView]:
        """Return every business the caller may reach, with their role in each.

        Assembled from memberships and then tenants rather than by a join, because
        a join would put two entities' storage in one repository.

        Memberships that are not active are excluded, since they grant nothing; a
        suspended or removed membership is not a business the person can open. A
        membership whose tenant row has vanished is skipped rather than fatal: it
        is a data defect, and one bad row must not break somebody's whole list.
        """
        user_id = _principal_user_id(principal)

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            memberships = await tenant_membership_crud.list_for_user(session, user_id)
            views: list[TenantMembershipView] = []
            for membership in memberships:
                if not membership.grants_access:
                    continue
                tenant = await tenant_crud.get_by_id(session, membership.tenant_id)
                if tenant is None:
                    self._logger.warning(
                        "membership_without_tenant",
                        membership_id=str(membership.id),
                        tenant_id=str(membership.tenant_id),
                    )
                    continue
                views.append(TenantMembershipView(tenant=tenant, role_name=membership.role_name))
        return views

    async def get_tenant(self, tenant_context: TenantContext) -> TenantModel:
        """Return the business the context is authorized for."""
        tenant_context.require_permission(
            TENANTS_READ,
            operation="get_tenant",
            resource_type="tenant",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            tenant = await tenant_crud.get_by_id(
                unit_of_work.session_handle, tenant_context.tenant_id
            )
        if tenant is None:
            # A membership pointing at a missing business is a data defect, and the
            # external answer is the same not-found a stranger would receive.
            raise NotFoundError(
                operation="get_tenant",
                entity="tenant",
                identifier=str(tenant_context.tenant_id),
                detail="the membership references a tenant row that does not exist",
            )
        return tenant

    # ------------------------------------------------------------------
    # Changing
    # ------------------------------------------------------------------

    async def update_tenant_profile(
        self,
        tenant_context: TenantContext,
        *,
        changes: Mapping[str, str | None],
    ) -> TenantModel:
        """Apply a partial profile update to the business.

        The slug is not editable here and never appears in the allowlist: it is
        published on links customers already hold.
        """
        tenant_context.require_permission(
            TENANTS_MANAGE,
            operation="update_tenant_profile",
            resource_type="tenant",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )

        unexpected_fields = sorted(set(changes) - _EDITABLE_PROFILE_FIELDS)
        if unexpected_fields:
            raise InvalidInputError(
                operation="update_tenant_profile",
                entity="tenant",
                identifier=str(tenant_context.tenant_id),
                detail=(
                    f"fields are not editable on a business profile: {', '.join(unexpected_fields)}"
                ),
            )

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            tenant = await tenant_crud.require_by_id(session, tenant_context.tenant_id)
            updated = tenant.with_profile(
                name=changes.get("name"),
                business_type=changes.get("business_type"),
                phone=changes.get("phone"),
                email=changes.get("email"),
                address=changes.get("address"),
                city=changes.get("city"),
                state=changes.get("state"),
                at=now,
            )
            stored = await tenant_crud.update(session, updated)
            await unit_of_work.commit()

        self._logger.info(
            "tenant_profile_updated",
            tenant_id=str(stored.id),
            actor_id=str(tenant_context.user_id),
            changed_fields=sorted(changes),
        )
        return stored

    async def deactivate_tenant(self, tenant_context: TenantContext) -> TenantModel:
        """Close the business.

        Deactivation, never deletion: every sale, movement and customer belongs to
        this tenant, and destroying the row would destroy the history with it.
        """
        tenant_context.require_permission(
            TENANTS_DEACTIVATE,
            operation="deactivate_tenant",
            resource_type="tenant",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            tenant = await tenant_crud.require_by_id(session, tenant_context.tenant_id)
            stored = await tenant_crud.update(session, tenant.deactivate(at=now))
            await unit_of_work.commit()

        self._logger.warning(
            "tenant_deactivated",
            tenant_id=str(stored.id),
            tenant_slug=stored.slug,
            actor_id=str(tenant_context.user_id),
            security_event="tenant_deactivated",
        )
        return stored

    # ------------------------------------------------------------------
    # Context resolution
    # ------------------------------------------------------------------

    async def resolve_tenant_context(
        self,
        principal: PrincipalLike,
        *,
        requested_tenant_id: UUID,
    ) -> TenantContext:
        """Resolve the caller's authorized context for one business.

        Deny-by-default and deliberately indistinguishable from absence: a caller
        with no membership receives the same NotFoundError a stranger receives for
        a business that does not exist, so the endpoint cannot be used to discover
        which tenant identifiers are real.

        An inactive business denies for everyone, including its owner: a closed
        business must stop answering on the next request, not at the next login.
        """
        user_id = _principal_user_id(principal)

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            membership = await tenant_membership_crud.get_for_user_in_tenant(
                session,
                tenant_id=requested_tenant_id,
                user_id=user_id,
            )
            if membership is None or not membership.grants_access:
                self._deny_context_resolution(
                    reason="no_active_membership",
                    user_id=user_id,
                    tenant_id=requested_tenant_id,
                    membership=membership,
                )

            tenant = await tenant_crud.get_by_id(session, requested_tenant_id)
            if tenant is None or not tenant.is_active:
                self._deny_context_resolution(
                    reason="tenant_missing_or_inactive",
                    user_id=user_id,
                    tenant_id=requested_tenant_id,
                    membership=membership,
                )

        # The deny path is typed as Never, so the type checker knows the flow only
        # reaches here with a membership. No assertion is needed, and none is used:
        # an assert would vanish under -O and take the guarantee with it.
        context = build_tenant_context(
            user_id=user_id,
            tenant_id=requested_tenant_id,
            membership_id=membership.id,
            role_id=None,
            permission_codes=membership.permission_codes,
            role_name=membership.role_name,
        )
        self._logger.info(
            "tenant_context_resolved",
            tenant_id=str(requested_tenant_id),
            actor_id=str(user_id),
            role_name=membership.role_name,
            permission_count=len(context.permissions),
        )
        return context

    def _deny_context_resolution(
        self,
        *,
        reason: str,
        user_id: UUID,
        tenant_id: UUID,
        membership: TenantMembershipModel | None,
    ) -> Never:
        """Log the denial with its true reason and raise the opaque answer."""
        self._logger.warning(
            "tenant_context_denied",
            reason=reason,
            actor_id=str(user_id),
            tenant_id=str(tenant_id),
            membership_status=membership.status.value if membership is not None else None,
            security_event="tenant_isolation",
        )
        raise NotFoundError(
            operation="resolve_tenant_context",
            entity="tenant",
            identifier=str(tenant_id),
            detail=f"no authorized access to this business: {reason}",
        )


def _principal_user_id(principal: PrincipalLike) -> UUID:
    """Return the principal's user identifier.

    The principal is typed structurally, so this is the one place the attribute is
    read and a reader can see exactly what the service depends on.
    """
    return principal.user_id
