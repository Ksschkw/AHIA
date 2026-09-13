"""User use cases.

The service owns business behaviour: which user may be read, what a profile
change may alter, and what happens when an account is deactivated. It receives
its persistence through a unit of work, so it never imports a database driver and
never builds a query.

Authorization is enforced here rather than only in the router. A router check can
be bypassed by a scheduled job, a CLI command or another service calling the same
use case, so every use case that touches protected data performs its own check.

For this slice the rule is self-scoped: a caller may read and change their own
account. That is expressed as a real decision with a log record, not as an
assumption, because the moment a use case gains a target-identifier parameter the
omitted check becomes a vulnerability.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Final, Protocol
from uuid import UUID

from ahia.core.database import UnitOfWork
from ahia.core.errors import AuthorizationError, InvalidInputError, UnauthenticatedError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.crud import user_crud
from ahia.models.entities.user_model import UserModel

_USER_SERVICE_LOGGER_NAME: Final[str] = "ahia.services.user"

#: The profile fields a caller may change on their own account. An allowlist, so
#: a new column cannot become externally writable by being added to the entity.
_EDITABLE_PROFILE_FIELDS: Final[frozenset[str]] = frozenset(
    {"first_name", "last_name", "email", "phone"}
)


class PrincipalLike(Protocol):
    """The part of a principal this service needs.

    Typed structurally so the service depends on the concept rather than on the
    authentication module's concrete class, and a test can pass a small object.
    """

    @property
    def user_id(self) -> UUID: ...

    @property
    def token_identifier(self) -> str: ...


class UserService:
    """Use cases for a user's own account."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._logger = (logger or get_logger(_USER_SERVICE_LOGGER_NAME)).bind(
            component="user_service", layer="service"
        )

    async def get_authenticated_user(self, principal: PrincipalLike) -> UserModel:
        """Return the authenticated caller's own record.

        A missing row and an inactive account produce the same external answer as
        an expired token. A deactivated account's tokens must stop working at
        once, and telling the holder that the account still exists but is
        disabled is information they have not been granted.
        """
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            user = self._require_active_self(
                principal,
                await user_crud.get_by_id(unit_of_work.session_handle, principal.user_id),
            )
            # A read needs no commit; leaving the block rolls the empty
            # transaction back, which is a no-op and avoids a pointless round
            # trip on every profile read.
        return user

    async def update_own_profile(
        self,
        principal: PrincipalLike,
        *,
        changes: Mapping[str, str | None],
    ) -> UserModel:
        """Apply a partial profile update to the caller's own account.

        Unknown keys are rejected rather than ignored. The transport schema
        already forbids them, but a service is callable from a CLI or a job, and
        silently ignoring a field there means an operator believes a change was
        saved when it was not.
        """
        unexpected_fields = sorted(set(changes) - _EDITABLE_PROFILE_FIELDS)
        if unexpected_fields:
            raise InvalidInputError(
                operation="update_own_profile",
                entity="user",
                identifier=str(principal.user_id),
                detail=f"fields are not editable on a profile: {', '.join(unexpected_fields)}",
            )

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            user = self._require_active_self(
                principal,
                await user_crud.get_by_id(session, principal.user_id),
            )

            # An omitted field and an explicitly null field both mean "leave this
            # alone": clearing a contact channel is a change of value, and the
            # entity refuses one that would leave the account unreachable.
            updated = user.with_profile(
                first_name=changes.get("first_name"),
                last_name=changes.get("last_name"),
                email=changes.get("email"),
                phone=changes.get("phone"),
                at=datetime.now(UTC),
            )
            stored = await user_crud.update(session, updated)
            await unit_of_work.commit()

        self._logger.info(
            "user_profile_updated",
            operation="update_own_profile",
            user_id=str(user.id),
            changed_fields=sorted(changes),
        )
        return stored

    async def deactivate_own_account(self, principal: PrincipalLike) -> UserModel:
        """Deactivate the caller's own account.

        Deactivation, never deletion: business history references this person, and
        a receipt must not lose its seller because they closed their account.
        """
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            user = self._require_active_self(
                principal,
                await user_crud.get_by_id(session, principal.user_id),
            )

            deactivated = user.deactivate(at=datetime.now(UTC))
            stored = await user_crud.update(session, deactivated)
            await unit_of_work.commit()

        self._logger.warning(
            "user_account_deactivated",
            operation="deactivate_own_account",
            user_id=str(stored.id),
            outcome="deactivated",
        )
        return stored

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------

    def _require_active_self(self, principal: PrincipalLike, user: UserModel | None) -> UserModel:
        """Deny unless the caller is acting on their own active account.

        Written as one function so the rule appears once. It logs both outcomes:
        an approval and a denial are equally interesting when reconstructing what
        an account did.
        """
        decision_logger = self._logger.bind(
            operation="authorize_self", actor_id=str(principal.user_id)
        )

        if user is None:
            decision_logger.warning(
                "authorization_denied",
                decision="denied",
                reason="subject_has_no_account",
            )
            raise UnauthenticatedError(
                operation="authenticate_principal",
                entity="user",
                identifier=str(principal.user_id),
                detail="the authenticated subject has no user record",
            )

        if not user.is_active:
            decision_logger.warning(
                "authorization_denied",
                decision="denied",
                reason="account_inactive",
            )
            raise UnauthenticatedError(
                operation="authenticate_principal",
                entity="user",
                identifier=str(user.id),
                detail="the account is deactivated; its tokens no longer authenticate",
            )

        if user.id != principal.user_id:
            # Reachable when a lookup returns a record that is not the caller's,
            # which is exactly the shape of a future cross-account defect. It is
            # checked on every call, not only on the paths that currently pass a
            # target identifier.
            decision_logger.warning(
                "authorization_denied",
                decision="denied",
                reason="not_the_account_holder",
                target_user_id=str(user.id),
            )
            raise AuthorizationError(
                operation="authorize_self",
                entity="user",
                identifier=str(user.id),
                detail="the principal is not the account holder",
            )

        decision_logger.info("authorization_allowed", decision="allowed")
        return user
