"""The authorized tenant context and the deny-by-default authorization policy.

Two ideas, kept apart on purpose.

The **requested** tenant is a hint. It arrives in a URL, a header or a body, and
a client controls all three. The **authorized** tenant is a fact: it is resolved
from the authenticated identity plus an active membership, and only then does a
service act on it. A `TenantContext` can only be built from resolved membership,
so a service cannot accidentally act on a request parameter.

**Deny by default.** `require_permission` denies unless the permission is
explicitly present in the resolved set. There is no "allow unless blocked" path,
and an empty or unresolved permission set always denies. A service that cannot
resolve permissions denies; a degraded authorization dependency is a denied
request, never a permitted one.

Every decision is logged with the principal, the tenant, the resource, the
action and the outcome. Denials matter as much as approvals: they are how an
attempted cross-tenant access becomes visible at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from ahia.core.errors import AuthorizationError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions.permissions_registry import PERMISSION_CODES

_AUTHORIZATION_LOGGER_NAME: Final[str] = "ahia.core.authorization"


class MembershipStatus(StrEnum):
    """The lifecycle of a user's access to one business."""

    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REMOVED = "removed"

    @property
    def grants_access(self) -> bool:
        """Return True only for an active membership.

        The three other states deny. An invitation that has not been accepted is
        not access, and a suspended or removed membership is a decision someone
        made on purpose.
        """
        return self is MembershipStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class TenantContext:
    """The resolved, authorized identity of a caller within one business.

    Constructed only after the identity is authenticated and the membership is
    confirmed active. Nothing in this object came from the request body.
    """

    user_id: UUID
    tenant_id: UUID
    membership_id: UUID
    role_id: UUID
    permissions: frozenset[str]
    device_id: UUID | None = None
    role_name: str | None = None

    def has_permission(self, permission_code: str) -> bool:
        """Return True only when the permission is explicitly present.

        An unknown code is not special-cased into an allow: it simply is not in
        the set, so it denies like any other absence.
        """
        return permission_code in self.permissions

    def require_permission(
        self,
        permission_code: str,
        *,
        operation: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        logger: StructuredLogger | None = None,
    ) -> None:
        """Raise unless the caller holds the permission.

        This is the single authorization entry point in the service layer. It is
        called by the use case that performs the work, not only by the router
        that happened to route to it, because a router check can be bypassed by a
        scheduled job, a CLI command or another service.
        """
        decision_logger = (logger or get_logger(_AUTHORIZATION_LOGGER_NAME)).bind(
            operation=operation,
            tenant_id=str(self.tenant_id),
            actor_id=str(self.user_id),
            membership_id=str(self.membership_id),
            action=permission_code,
        )
        if resource_type is not None:
            decision_logger = decision_logger.bind(resource_type=resource_type)
        if resource_id is not None:
            decision_logger = decision_logger.bind(resource_id=resource_id)
        if self.device_id is not None:
            decision_logger = decision_logger.bind(device_id=str(self.device_id))

        if self.has_permission(permission_code):
            decision_logger.info("authorization_allowed", decision="allowed")
            return

        decision_logger.warning(
            "authorization_denied",
            decision="denied",
            reason="permission_absent",
            held_permission_count=len(self.permissions),
        )
        raise AuthorizationError(
            operation=operation,
            entity=resource_type or "authorization",
            identifier=resource_id,
            detail=(
                f"permission={permission_code} role={self.role_name or 'unknown'} "
                f"tenant_id={self.tenant_id}"
            ),
        )

    def describe_for_audit(self) -> dict[str, str]:
        """Return the fields written to an audit event for an action by this caller."""
        description = {
            "tenant_id": str(self.tenant_id),
            "actor_id": str(self.user_id),
            "membership_id": str(self.membership_id),
            "role_id": str(self.role_id),
        }
        if self.device_id is not None:
            description["device_id"] = str(self.device_id)
        return description


def build_tenant_context(
    *,
    user_id: UUID,
    tenant_id: UUID,
    membership_id: UUID,
    role_id: UUID,
    permission_codes: frozenset[str],
    device_id: UUID | None = None,
    role_name: str | None = None,
) -> TenantContext:
    """Build a context from resolved membership.

    Unknown permission codes are dropped rather than carried: a code that is not
    in the registry cannot grant anything, and carrying it would make an audit
    record claim a capability the application does not implement. Dropping is
    safe precisely because authorization is deny-by-default.
    """
    return TenantContext(
        user_id=user_id,
        tenant_id=tenant_id,
        membership_id=membership_id,
        role_id=role_id,
        permissions=frozenset(permission_codes & PERMISSION_CODES),
        device_id=device_id,
        role_name=role_name,
    )


def authorization_logger(component: str) -> StructuredLogger:
    """Return a logger bound to the authorization component.

    Exposed so the code that resolves contexts logs the resolution outcome with
    the same component field as the decisions themselves, which is what makes
    "who tried, and what happened" answerable from one query.
    """
    return get_logger(_AUTHORIZATION_LOGGER_NAME).bind(component=component)
