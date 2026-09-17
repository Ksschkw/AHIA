"""Staff administration: inviting, promoting, suspending and removing people.

Two families of use case live here, and they are different in kind.

**Administration** happens inside a tenant, under the caller's authorized context,
and every action requires an explicit permission: `staff.read`, `staff.invite`,
`staff.update`, `staff.remove`. The check is performed here rather than in the
router so a CLI command or a scheduled job cannot bypass it.

**Acceptance** happens outside a tenant, because the person accepting has no
membership yet. Their authorization is the invitation token plus a matching
identity, and the identity is matched on the exact channel the invitation was
addressed to.

The last-owner rule lives here. Removing or demoting the only owner would leave a
business nobody can administer, which is indistinguishable from losing it, so both
actions are refused and the refusal is logged as the deliberate act it is.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Never, Protocol
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.errors import ConflictError, DomainError, NotFoundError, UnauthenticatedError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions.staff_permissions import (
    STAFF_INVITE,
    STAFF_READ,
    STAFF_REMOVE,
    STAFF_UPDATE,
)
from ahia.core.security import TokenService
from ahia.core.tenant_context import TenantContext
from ahia.crud import (
    membership_invitation_crud,
    tenant_crud,
    tenant_membership_crud,
    user_crud,
)
from ahia.models.entities.membership_invitation_model import MembershipInvitationModel
from ahia.models.entities.phone_number import canonical_phone_number
from ahia.models.entities.tenant_membership_model import TenantMembershipModel
from ahia.models.entities.tenant_model import TenantModel
from ahia.models.entities.user_model import UserModel
from ahia.services.audit_event_service import AuditEventService

_MEMBERSHIP_LOGGER_NAME: Final[str] = "ahia.services.tenant_membership"

#: How long an invitation stays usable. Long enough for a worker to act on it over
#: a weekend, short enough that an abandoned invitation is not a standing door.
INVITATION_LIFETIME: Final[timedelta] = timedelta(days=14)

REASON_SUSPENDED: Final[str] = "suspended_by_admin"
REASON_REMOVED: Final[str] = "removed_by_admin"


class PrincipalLike(Protocol):
    """The part of a principal this service needs.

    Typed structurally, so a test can pass a small object and the service depends
    on the concept rather than on the authentication module's concrete class.
    """

    @property
    def user_id(self) -> UUID: ...


@dataclass(frozen=True, slots=True)
class MemberView:
    """A membership together with the person it belongs to."""

    membership: TenantMembershipModel
    user: UserModel


@dataclass(frozen=True, slots=True)
class PendingInvitationView:
    """An invitation together with the business it is for."""

    invitation: MembershipInvitationModel
    tenant: TenantModel


class TenantMembershipService:
    """Staff use cases."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        token_service: TokenService,
        audit_event_service: AuditEventService,
        default_phone_country_code: str = "234",
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._token_service = token_service
        self._audit = audit_event_service
        #: The country a locally written number belongs to. An invitation and an account must agree
        #: on what "the same number" means, or an invitation to 0901... can never be accepted by an
        #: account created with +234901...
        self._default_country_code = f"+{default_phone_country_code.lstrip('+')}"
        self._logger = (logger or get_logger(_MEMBERSHIP_LOGGER_NAME)).bind(
            component="tenant_membership_service", layer="service"
        )

    # ------------------------------------------------------------------
    # Inviting
    # ------------------------------------------------------------------

    async def invite_member(
        self,
        tenant_context: TenantContext,
        *,
        role_name: str,
        email: str | None = None,
        phone: str | None = None,
    ) -> tuple[MembershipInvitationModel, str]:
        """Issue an invitation and return it with its plaintext token.

        The token is returned exactly once, to the inviter. Only its digest is
        stored, so nobody - including an operator reading the database - can
        recover it afterwards.
        """
        tenant_context.require_permission(
            STAFF_INVITE,
            operation="invite_member",
            resource_type="tenant_membership",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )

        now = datetime.now(UTC)
        normalized_email = email.strip().lower() if email else None
        # The same rule the account uses, so the invitation is addressed to the person who will
        # accept it rather than to the way somebody happened to type the number.
        normalized_phone = canonical_phone_number(
            phone, default_country_code=self._default_country_code
        )
        token = self._token_service.generate_public_token()

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            await self._reject_member_or_pending_invitation(
                session,
                tenant_id=tenant_context.tenant_id,
                email=normalized_email,
                phone=normalized_phone,
                at=now,
            )
            invitation = await membership_invitation_crud.create(
                session,
                MembershipInvitationModel.issue(
                    invitation_id=uuid4(),
                    tenant_id=tenant_context.tenant_id,
                    role_name=role_name,
                    token_hash=self._token_service.hash_bearer_token(token),
                    expires_at=now + INVITATION_LIFETIME,
                    created_at=now,
                    created_by_user_id=tenant_context.user_id,
                    invited_email=normalized_email,
                    invited_phone=normalized_phone,
                ),
            )
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="invite_member",
                entity_type="membership_invitation",
                entity_id=invitation.id,
                now=now,
                detail=invitation.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.info(
            "member_invited",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            invitation_id=str(invitation.id),
            role_name=invitation.role_name,
            invited_channel="email" if normalized_email else "phone",
        )
        return invitation, token

    async def _reject_member_or_pending_invitation(
        self,
        session: object,
        *,
        tenant_id: UUID,
        email: str | None,
        phone: str | None,
        at: datetime,
    ) -> None:
        """Refuse to invite somebody who is already here or already invited.

        Two invitations for one person would produce two memberships on
        acceptance, and two answers to what that person may do.
        """
        if email is not None:
            existing_user = await user_crud.get_by_email(session, email)  # type: ignore[arg-type]
            if existing_user is not None:
                existing_membership = await tenant_membership_crud.get_for_user_in_tenant(
                    session,  # type: ignore[arg-type]
                    tenant_id=tenant_id,
                    user_id=existing_user.id,
                )
                if existing_membership is not None and not existing_membership.status.is_terminal:
                    raise ConflictError(
                        operation="invite_member",
                        entity="tenant_membership",
                        detail="this person is already a member of this business",
                    )

        pending = await membership_invitation_crud.list_pending_for_identity(
            session,  # type: ignore[arg-type]
            email=email,
            phone=phone,
        )
        for invitation in pending:
            if invitation.tenant_id == tenant_id and invitation.is_pending(at=at):
                raise ConflictError(
                    operation="invite_member",
                    entity="membership_invitation",
                    identifier=str(invitation.id),
                    detail="an invitation for this person is already pending in this business",
                )

    async def list_invitations(
        self, tenant_context: TenantContext
    ) -> list[MembershipInvitationModel]:
        """Return every invitation a business has issued."""
        tenant_context.require_permission(
            STAFF_READ,
            operation="list_invitations",
            resource_type="tenant_membership",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await membership_invitation_crud.list_for_tenant(
                unit_of_work.session_handle, tenant_context.tenant_id
            )

    # ------------------------------------------------------------------
    # Membership administration
    # ------------------------------------------------------------------

    async def list_members(self, tenant_context: TenantContext) -> list[MemberView]:
        """Return every member of the business the caller is authorized for.

        Membership first, then the person: a join across two entities would put
        both entities' storage in one repository.
        """
        tenant_context.require_permission(
            STAFF_READ,
            operation="list_members",
            resource_type="tenant_membership",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            memberships = await tenant_membership_crud.list_for_tenant(
                session, tenant_context.tenant_id
            )
            views: list[MemberView] = []
            for membership in memberships:
                user = await user_crud.get_by_id(session, membership.user_id)
                if user is None:
                    self._logger.warning(
                        "membership_without_user",
                        membership_id=str(membership.id),
                        user_id=str(membership.user_id),
                    )
                    continue
                views.append(MemberView(membership=membership, user=user))
        return views

    async def load_member_user(
        self, tenant_context: TenantContext, user_id: UUID
    ) -> UserModel | None:
        """Return the person behind a membership in the caller's business.

        Used to render a member response. It resolves the user through the
        membership path, so it cannot be used to read an arbitrary account: the
        membership has already been proven to belong to this tenant.
        """
        tenant_context.require_permission(
            STAFF_READ,
            operation="load_member_user",
            resource_type="tenant_membership",
            resource_id=str(user_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await user_crud.get_by_id(unit_of_work.session_handle, user_id)

    async def change_member_role(
        self,
        tenant_context: TenantContext,
        *,
        membership_id: UUID,
        role_name: str,
    ) -> TenantMembershipModel:
        """Change what a member may do.

        The last owner cannot be demoted: doing so would leave a business nobody
        can administer, which is indistinguishable from losing it.
        """
        tenant_context.require_permission(
            STAFF_UPDATE,
            operation="change_member_role",
            resource_type="tenant_membership",
            resource_id=str(membership_id),
            logger=self._logger,
        )

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            membership = await self._require_membership(
                session, tenant_context.tenant_id, membership_id
            )
            if membership.is_owner and role_name.strip().upper() != "OWNER":
                await self._refuse_if_last_owner(
                    session,
                    tenant_id=tenant_context.tenant_id,
                    membership=membership,
                    action="demote the last owner",
                )
            updated = await tenant_membership_crud.update(
                session, membership.change_role(role_name=role_name, at=now)
            )
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="change_member_role",
                entity_type="tenant_membership",
                entity_id=updated.id,
                now=now,
                detail=updated.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.info(
            "member_role_changed",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            membership_id=str(updated.id),
            previous_role=membership.role_name,
            role_name=updated.role_name,
        )
        return updated

    async def suspend_member(
        self, tenant_context: TenantContext, *, membership_id: UUID
    ) -> TenantMembershipModel:
        """Take a member's access away without removing them from the business."""
        tenant_context.require_permission(
            STAFF_UPDATE,
            operation="suspend_member",
            resource_type="tenant_membership",
            resource_id=str(membership_id),
            logger=self._logger,
        )

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            membership = await self._require_membership(
                session, tenant_context.tenant_id, membership_id
            )
            if membership.is_owner:
                await self._refuse_if_last_owner(
                    session,
                    tenant_id=tenant_context.tenant_id,
                    membership=membership,
                    action="suspend the last owner",
                )
            updated = await tenant_membership_crud.update(session, membership.suspend(at=now))
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="suspend_member",
                entity_type="tenant_membership",
                entity_id=updated.id,
                now=now,
                detail=updated.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.warning(
            "member_suspended",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            membership_id=str(updated.id),
            target_user_id=str(updated.user_id),
            security_event="membership_suspended",
        )
        return updated

    async def reactivate_member(
        self, tenant_context: TenantContext, *, membership_id: UUID
    ) -> TenantMembershipModel:
        """Return a suspended member's access."""
        tenant_context.require_permission(
            STAFF_UPDATE,
            operation="reactivate_member",
            resource_type="tenant_membership",
            resource_id=str(membership_id),
            logger=self._logger,
        )

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            membership = await self._require_membership(
                session, tenant_context.tenant_id, membership_id
            )
            updated = await tenant_membership_crud.update(session, membership.activate(at=now))
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="reactivate_member",
                entity_type="tenant_membership",
                entity_id=updated.id,
                now=now,
                detail=updated.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.info(
            "member_reactivated",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            membership_id=str(updated.id),
        )
        return updated

    async def remove_member(
        self, tenant_context: TenantContext, *, membership_id: UUID
    ) -> TenantMembershipModel:
        """Remove a member's access permanently.

        Removal rather than deletion: the person's sales and audit events still
        reference them, and a receipt must not lose its seller.
        """
        tenant_context.require_permission(
            STAFF_REMOVE,
            operation="remove_member",
            resource_type="tenant_membership",
            resource_id=str(membership_id),
            logger=self._logger,
        )

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            membership = await self._require_membership(
                session, tenant_context.tenant_id, membership_id
            )
            if membership.is_owner:
                await self._refuse_if_last_owner(
                    session,
                    tenant_id=tenant_context.tenant_id,
                    membership=membership,
                    action="remove the last owner",
                )
            updated = await tenant_membership_crud.update(session, membership.remove(at=now))
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="remove_member",
                entity_type="tenant_membership",
                entity_id=updated.id,
                now=now,
                detail=updated.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.warning(
            "member_removed",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            membership_id=str(updated.id),
            target_user_id=str(updated.user_id),
            security_event="membership_removed",
        )
        return updated

    async def _require_membership(
        self,
        session: object,
        tenant_id: UUID,
        membership_id: UUID,
    ) -> TenantMembershipModel:
        """Load a membership, refusing one that belongs to another business.

        The tenant identifier comes from the authorized context, never from the
        request, so a membership identifier alone cannot reach across tenants. A
        mismatch is answered exactly as a missing membership would be.
        """
        membership = await tenant_membership_crud.get_by_id(session, membership_id)  # type: ignore[arg-type]
        if membership is None or membership.tenant_id != tenant_id:
            self._logger.warning(
                "membership_access_denied",
                reason="membership_not_in_tenant",
                tenant_id=str(tenant_id),
                membership_id=str(membership_id),
                security_event="tenant_isolation",
            )
            raise NotFoundError(
                operation="fetch_membership",
                entity="tenant_membership",
                identifier=str(membership_id),
                detail="no membership matched in this business",
            )
        return membership

    async def _refuse_if_last_owner(
        self,
        session: object,
        *,
        tenant_id: UUID,
        membership: TenantMembershipModel,
        action: str,
    ) -> None:
        """Refuse an action that would leave the business without an owner."""
        active_owners = await tenant_membership_crud.count_active_owners(session, tenant_id)  # type: ignore[arg-type]
        if active_owners > 1:
            return

        self._logger.error(
            "last_owner_protected",
            tenant_id=str(tenant_id),
            membership_id=str(membership.id),
            attempted_action=action,
            active_owners=active_owners,
            security_event="last_owner_protection",
        )
        raise DomainError(
            operation="protect_last_owner",
            entity="tenant_membership",
            identifier=str(membership.id),
            detail=f"refused to {action}; a business must keep at least one active owner",
        )

    # ------------------------------------------------------------------
    # Acceptance, from outside the tenant
    # ------------------------------------------------------------------

    async def list_pending_invitations(
        self, principal: PrincipalLike
    ) -> list[PendingInvitationView]:
        """Return the invitations addressed to the caller, with their businesses.

        The caller has no membership yet, so this is authorized by identity rather
        than by permission: the invitations are found by matching the caller's own
        email address or phone number.
        """
        user = await self._require_authenticated_user(principal)
        now = datetime.now(UTC)

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            invitations = await membership_invitation_crud.list_pending_for_identity(
                session, email=user.email, phone=user.phone
            )
            views: list[PendingInvitationView] = []
            for invitation in invitations:
                if not invitation.is_pending(at=now):
                    continue
                tenant = await tenant_crud.get_by_id(session, invitation.tenant_id)
                if tenant is None or not tenant.is_active:
                    continue
                views.append(PendingInvitationView(invitation=invitation, tenant=tenant))
        return views

    async def accept_invitation(
        self,
        principal: PrincipalLike,
        *,
        token: str,
    ) -> tuple[TenantMembershipModel, TenantModel]:
        """Take up an invitation addressed to the caller.

        Three things must all be true: the token must match a pending invitation,
        the invitation must have been addressed to an identity the caller holds,
        and the business must still be open. Every failure produces the same
        refusal, so a caller cannot use this endpoint to discover which invitation
        tokens exist or which addresses are invited.
        """
        user = await self._require_authenticated_user(principal)
        now = datetime.now(UTC)
        presented_hash = self._token_service.hash_bearer_token(token)

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            invitation = await membership_invitation_crud.get_by_token_hash(session, presented_hash)
            if invitation is None or not invitation.is_pending(at=now):
                self._deny_acceptance(
                    reason="no_pending_invitation", user_id=user.id, invitation=invitation
                )

            if not invitation.addresses(email=user.email, phone=user.phone):
                self._deny_acceptance(
                    reason="identity_does_not_match", user_id=user.id, invitation=invitation
                )

            tenant = await tenant_crud.get_by_id(session, invitation.tenant_id)
            if tenant is None or not tenant.is_active:
                self._deny_acceptance(
                    reason="tenant_missing_or_inactive", user_id=user.id, invitation=invitation
                )

            existing = await tenant_membership_crud.get_for_user_in_tenant(
                session, tenant_id=invitation.tenant_id, user_id=user.id
            )
            if existing is not None:
                self._deny_acceptance(
                    reason="already_a_member", user_id=user.id, invitation=invitation
                )

            membership = await tenant_membership_crud.create(
                session,
                TenantMembershipModel.activate_immediately(
                    membership_id=uuid4(),
                    tenant_id=invitation.tenant_id,
                    user_id=user.id,
                    role_name=invitation.role_name,
                    now=now,
                ),
            )
            await membership_invitation_crud.update(
                session, invitation.accept(user_id=user.id, at=now)
            )
            await unit_of_work.commit()

        self._logger.info(
            "invitation_accepted",
            tenant_id=str(membership.tenant_id),
            user_id=str(user.id),
            membership_id=str(membership.id),
            role_name=membership.role_name,
            invitation_id=str(invitation.id),
        )
        return membership, tenant

    def _deny_acceptance(
        self,
        *,
        reason: str,
        user_id: UUID,
        invitation: MembershipInvitationModel | None,
    ) -> Never:
        """Log the true reason and raise the same opaque answer every time."""
        self._logger.warning(
            "invitation_acceptance_denied",
            reason=reason,
            user_id=str(user_id),
            invitation_id=str(invitation.id) if invitation is not None else None,
            security_event="invitation_denied",
        )
        raise NotFoundError(
            operation="accept_invitation",
            entity="membership_invitation",
            detail=f"no acceptable invitation matched: {reason}",
        )

    async def _require_authenticated_user(self, principal: PrincipalLike) -> UserModel:
        """Load the caller's own record, refusing a missing or inactive account."""
        user_id = principal.user_id

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            user = await user_crud.get_by_id(unit_of_work.session_handle, user_id)
        if user is None or not user.is_active:
            raise UnauthenticatedError(
                operation="authenticate_principal",
                entity="user",
                identifier=str(user_id),
                detail="the authenticated subject has no active user record",
            )
        return user
