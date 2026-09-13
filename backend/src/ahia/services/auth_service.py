"""Authentication use cases.

Registration, sign-in, refresh, sign-out and password change. This is the most
security-sensitive service in the product, so the decisions are stated rather
than implied.

Enumeration
    Sign-in answers the same way whether the account exists, the password is
    wrong, or the account is deactivated: one code, one message, and the same work
    performed on every path. When the identifier matches no row the service still
    verifies against a dummy hash, so the response time does not answer the
    question the response body refuses to.

Refresh rotation and reuse
    Every refresh issues a new session and revokes the presented one. If a
    revoked-and-rotated token is presented again, one of the two copies is in the
    wrong hands, so the entire session family is revoked and the event is logged
    as a security incident. This is the standard defence against a stolen refresh
    token being used alongside the legitimate one.

Duplicate registration
    This is the one place where the product spec accepts a specific external
    answer rather than an opaque one, because a person signing up must be told
    that the address is taken. The response says exactly that and nothing more: it
    does not confirm whether the account is active, who owns it, or when it was
    created.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.errors import (
    AuthenticationError,
    ConflictError,
    InvalidInputError,
    UnauthenticatedError,
)
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.security import PasswordHasher, TokenService
from ahia.crud import session_crud, user_crud
from ahia.models.entities.session_model import SessionModel
from ahia.models.entities.user_model import UserModel, normalize_email, normalize_phone

_AUTH_LOGGER_NAME: Final[str] = "ahia.services.auth"

#: Revocation reasons. Fixed strings because they are read during incident review
#: and a typo would silently create a second category.
REASON_SIGNED_OUT: Final[str] = "signed_out"
REASON_ROTATED: Final[str] = "rotated"
REASON_REUSE_DETECTED: Final[str] = "reuse_detected"
# The name contains "PASSWORD" and the scanner flags it; the value is a
# revocation-reason label, not a credential.
REASON_PASSWORD_CHANGED: Final[str] = "password_changed"  # noqa: S105


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """A freshly issued credential pair and the account it belongs to."""

    user: UserModel
    session: SessionModel
    access_token: str
    refresh_token: str
    access_token_expires_in_seconds: int


class AuthService:
    """Identity use cases."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        token_service: TokenService,
        password_hasher: PasswordHasher,
        refresh_token_ttl_days: int,
        access_token_ttl_minutes: int,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._token_service = token_service
        self._password_hasher = password_hasher
        self._refresh_token_lifetime = timedelta(days=refresh_token_ttl_days)
        self._access_token_expires_in_seconds = access_token_ttl_minutes * 60
        self._logger = (logger or get_logger(_AUTH_LOGGER_NAME)).bind(
            component="auth_service", layer="service"
        )
        # Verified against when the identifier matches no account, so an unknown
        # identifier costs the same as a wrong password.
        self._dummy_password_hash = self._password_hasher.hash_password(
            "a-value-that-is-never-a-real-password"
        )

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def register_user(
        self,
        *,
        first_name: str,
        password: str,
        last_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
    ) -> IssuedSession:
        """Create an account and sign the person in."""
        self._password_hasher.validate_password_strength(password)
        now = datetime.now(UTC)

        if email is None and phone is None:
            raise InvalidInputError(
                operation="register_user",
                entity="user",
                detail="registration needs an email address or a phone number",
            )

        new_user = UserModel.create(
            user_id=uuid4(),
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            password_hash=self._password_hasher.hash_password(password),
            now=now,
        )

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            # A friendly failure before the insert, and the unique index remains
            # the authority: two simultaneous registrations of the same address
            # are still caught by the database.
            await self._reject_existing_account(session, new_user)
            stored_user = await user_crud.create(session, new_user)
            issued = await self._issue_session(
                session,
                user=stored_user,
                at=now,
                device_id=None,
            )
            await unit_of_work.commit()

        self._logger.info(
            "user_registered",
            user_id=str(stored_user.id),
            session_id=str(issued.session.id),
            has_email=email is not None,
            has_phone=phone is not None,
        )
        return issued

    async def _reject_existing_account(self, session: object, candidate: UserModel) -> None:
        """Raise ConflictError when the address or number is already registered.

        The external message is specific here, and this is the one documented
        exception to the product's opaque-error rule, because a person signing up
        has to be told that the address is taken. It confirms nothing else: not
        whether the account is active, not who owns it, not when it was created.
        """
        if candidate.email is not None:
            existing = await user_crud.get_by_email(session, candidate.email)  # type: ignore[arg-type]
            if existing is not None:
                self._logger.warning(
                    "registration_rejected",
                    reason="email_already_registered",
                    existing_user_id=str(existing.id),
                )
                raise ConflictError(
                    operation="register_user",
                    entity="user",
                    detail="the email address is already registered",
                )

        if candidate.phone is not None:
            existing_by_phone = await user_crud.get_by_phone(session, candidate.phone)  # type: ignore[arg-type]
            if existing_by_phone is not None:
                self._logger.warning(
                    "registration_rejected",
                    reason="phone_already_registered",
                    existing_user_id=str(existing_by_phone.id),
                )
                raise ConflictError(
                    operation="register_user",
                    entity="user",
                    detail="the phone number is already registered",
                )

    # ------------------------------------------------------------------
    # Sign-in
    # ------------------------------------------------------------------

    async def authenticate_user(
        self,
        *,
        identifier: str,
        password: str,
        device_id: UUID | None = None,
    ) -> IssuedSession:
        """Exchange credentials for a session.

        Every failure produces the same external error, whether the account does
        not exist, the password is wrong, or the account is deactivated. The work
        performed is also the same: a hash is verified on every path.
        """
        now = datetime.now(UTC)
        normalized_email = normalize_email(identifier)
        normalized_phone = normalize_phone(identifier)

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            user = await self._find_by_identifier(session, normalized_email, normalized_phone)

            if user is None or user.password_hash is None:
                # Verify against a dummy hash so the timing matches the
                # wrong-password path. Skipping the hash here is what turns a
                # sign-in endpoint into a user-enumeration oracle.
                self._password_hasher.verify_password(password, self._dummy_password_hash)
                self._log_failed_sign_in(reason="no_matching_account")
                raise AuthenticationError(
                    operation="authenticate_user",
                    entity="user",
                    detail="no account matched the supplied identifier",
                )

            if not self._password_hasher.verify_password(password, user.password_hash):
                self._log_failed_sign_in(reason="password_mismatch", user_id=user.id)
                raise AuthenticationError(
                    operation="authenticate_user",
                    entity="user",
                    identifier=str(user.id),
                    detail="password did not match",
                )

            if not user.is_active:
                self._log_failed_sign_in(reason="account_inactive", user_id=user.id)
                raise AuthenticationError(
                    operation="authenticate_user",
                    entity="user",
                    identifier=str(user.id),
                    detail="the account is deactivated",
                )

            if self._password_hasher.needs_rehash(user.password_hash):
                # The only moment the plaintext is available is right after a
                # successful verification, so this is where the cost is raised.
                user = user.change_password_hash(
                    password_hash=self._password_hasher.hash_password(password),
                    at=now,
                )
                user = await user_crud.update(session, user)
                self._logger.info("password_rehashed", user_id=str(user.id))

            user = await user_crud.update(session, user.record_login(at=now))
            issued = await self._issue_session(session, user=user, at=now, device_id=device_id)
            await unit_of_work.commit()

        self._logger.info(
            "user_signed_in",
            user_id=str(user.id),
            session_id=str(issued.session.id),
        )
        return issued

    @staticmethod
    async def _find_by_identifier(
        session: object,
        email: str | None,
        phone: str | None,
    ) -> UserModel | None:
        """Look the identifier up as an email first, then as a phone number.

        An identifier containing an at-sign is an email; anything else is treated
        as a phone number. Trying both shapes costs two queries and removes a
        class of "it says my account does not exist" support requests.
        """
        if email is not None and "@" in email:
            found = await user_crud.get_by_email(session, email)  # type: ignore[arg-type]
            if found is not None:
                return found
        if phone is not None:
            return await user_crud.get_by_phone(session, phone)  # type: ignore[arg-type]
        return None

    def _log_failed_sign_in(self, *, reason: str, user_id: UUID | None = None) -> None:
        """Record the failure with its real reason, internally."""
        fields: dict[str, object] = {"reason": reason, "outcome": "denied"}
        if user_id is not None:
            fields["user_id"] = str(user_id)
        self._logger.warning("sign_in_failed", **fields)

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    async def refresh_session(self, *, refresh_token: str) -> IssuedSession:
        """Rotate a refresh token into a new session.

        Rotation is not optional: a refresh token that can be used twice is a
        refresh token that can be used by a thief indefinitely.
        """
        now = datetime.now(UTC)
        presented_hash = self._token_service.hash_refresh_token(refresh_token)

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            # Locked for update: two concurrent refreshes of the same token must
            # not both rotate, or the reuse detector would see a legitimate
            # client as a replay.
            stored_session = await session_crud.get_by_token_hash_for_update(
                session, presented_hash
            )

            if stored_session is None:
                self._logger.warning("refresh_rejected", reason="unknown_token")
                raise UnauthenticatedError(
                    operation="refresh_session",
                    entity="session",
                    detail="the refresh token does not match any session",
                )

            if stored_session.is_reuse_suspect:
                # A rotated token has been presented again. Either it was stolen,
                # or the replacement was. End the family.
                revoked = await session_crud.revoke_all_for_user(
                    session,
                    user_id=stored_session.user_id,
                    at=now,
                    reason=REASON_REUSE_DETECTED,
                )
                await unit_of_work.commit()
                self._logger.error(
                    "refresh_token_reuse_detected",
                    user_id=str(stored_session.user_id),
                    session_id=str(stored_session.id),
                    sessions_revoked=revoked,
                    security_event="refresh_token_reuse",
                )
                raise UnauthenticatedError(
                    operation="refresh_session",
                    entity="session",
                    identifier=str(stored_session.id),
                    detail=(
                        "a rotated refresh token was presented again; "
                        "the session family was revoked"
                    ),
                )

            if stored_session.is_revoked():
                self._logger.warning(
                    "refresh_rejected",
                    reason="session_revoked",
                    session_id=str(stored_session.id),
                    revocation_reason=stored_session.revocation_reason,
                )
                raise UnauthenticatedError(
                    operation="refresh_session",
                    entity="session",
                    identifier=str(stored_session.id),
                    detail=f"the session was revoked: {stored_session.revocation_reason}",
                )

            if stored_session.is_expired(at=now):
                self._logger.warning(
                    "refresh_rejected", reason="session_expired", session_id=str(stored_session.id)
                )
                raise UnauthenticatedError(
                    operation="refresh_session",
                    entity="session",
                    identifier=str(stored_session.id),
                    detail="the session has expired",
                )

            user = await user_crud.get_by_id(session, stored_session.user_id)
            if user is None or not user.is_active:
                await session_crud.update(
                    session,
                    stored_session.revoke(at=now, reason="account_inactive"),
                )
                await unit_of_work.commit()
                self._logger.warning(
                    "refresh_rejected",
                    reason="account_inactive",
                    user_id=str(stored_session.user_id),
                )
                raise UnauthenticatedError(
                    operation="refresh_session",
                    entity="user",
                    identifier=str(stored_session.user_id),
                    detail="the account is missing or deactivated",
                )

            issued = await self._issue_session(
                session,
                user=user,
                at=now,
                device_id=stored_session.device_id,
            )
            await session_crud.update(
                session,
                stored_session.rotate(replacement_session_id=issued.session.id, at=now),
            )
            await unit_of_work.commit()

        self._logger.info(
            "session_refreshed",
            user_id=str(user.id),
            previous_session_id=str(stored_session.id),
            session_id=str(issued.session.id),
        )
        return issued

    # ------------------------------------------------------------------
    # Sign-out
    # ------------------------------------------------------------------

    async def revoke_session(self, *, refresh_token: str, reason: str = REASON_SIGNED_OUT) -> None:
        """End one session.

        Idempotent and quiet: signing out with an unknown or already-revoked token
        succeeds, because a client that has lost track of its session should be
        able to reach a signed-out state without an error in its logs.
        """
        now = datetime.now(UTC)
        presented_hash = self._token_service.hash_refresh_token(refresh_token)

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            stored_session = await session_crud.get_by_token_hash(session, presented_hash)
            if stored_session is None:
                self._logger.info("sign_out_ignored", reason="unknown_token")
                return
            await session_crud.update(session, stored_session.revoke(at=now, reason=reason))
            await unit_of_work.commit()

        self._logger.info(
            "session_revoked",
            session_id=str(stored_session.id),
            user_id=str(stored_session.user_id),
            reason=reason,
        )

    async def revoke_all_sessions(
        self,
        *,
        user_id: UUID,
        reason: str,
        except_session_id: UUID | None = None,
    ) -> int:
        """End every session a user holds, optionally sparing the current one."""
        now = datetime.now(UTC)

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            revoked = await session_crud.revoke_all_for_user(
                unit_of_work.session_handle,
                user_id=user_id,
                at=now,
                reason=reason,
                except_session_id=except_session_id,
            )
            await unit_of_work.commit()

        self._logger.info(
            "sessions_revoked",
            user_id=str(user_id),
            sessions_revoked=revoked,
            reason=reason,
            kept_session_id=str(except_session_id) if except_session_id else None,
        )
        return revoked

    # ------------------------------------------------------------------
    # Password change
    # ------------------------------------------------------------------

    async def change_password(
        self,
        *,
        user_id: UUID,
        current_password: str,
        new_password: str,
        current_session_id: UUID | None = None,
    ) -> int:
        """Change a password and end every other session.

        Every other session ends because a password change is the action a person
        takes when they believe their account is compromised. Sparing the session
        that performed the change keeps them signed in on the device they are
        holding.
        """
        self._password_hasher.validate_password_strength(new_password)
        now = datetime.now(UTC)

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            user = await user_crud.get_by_id(session, user_id)
            if user is None or not user.is_active:
                raise UnauthenticatedError(
                    operation="change_password",
                    entity="user",
                    identifier=str(user_id),
                    detail="the account is missing or deactivated",
                )

            if user.password_hash is None or not self._password_hasher.verify_password(
                current_password, user.password_hash
            ):
                self._logger.warning(
                    "password_change_rejected",
                    reason="current_password_mismatch",
                    user_id=str(user_id),
                )
                raise AuthenticationError(
                    operation="change_password",
                    entity="user",
                    identifier=str(user_id),
                    detail="the current password did not match",
                )

            await user_crud.update(
                session,
                user.change_password_hash(
                    password_hash=self._password_hasher.hash_password(new_password),
                    at=now,
                ),
            )
            revoked = await session_crud.revoke_all_for_user(
                session,
                user_id=user_id,
                at=now,
                reason=REASON_PASSWORD_CHANGED,
                except_session_id=current_session_id,
            )
            await unit_of_work.commit()

        self._logger.warning(
            "password_changed",
            user_id=str(user_id),
            sessions_revoked=revoked,
            security_event="password_changed",
        )
        return revoked

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _issue_session(
        self,
        session: object,
        *,
        user: UserModel,
        at: datetime,
        device_id: UUID | None,
    ) -> IssuedSession:
        """Create a session row and the token pair that belongs to it."""
        refresh_token, refresh_token_hash = self._token_service.generate_refresh_token()
        entity = SessionModel.issue(
            session_id=uuid4(),
            user_id=user.id,
            refresh_token_hash=refresh_token_hash,
            expires_at=at + self._refresh_token_lifetime,
            created_at=at,
            device_id=device_id,
        )
        stored_session = await session_crud.create(session, entity)  # type: ignore[arg-type]
        access_token, _ = self._token_service.issue_access_token(
            subject=str(user.id),
            session_identifier=str(stored_session.id),
        )
        return IssuedSession(
            user=user,
            session=stored_session,
            access_token=access_token,
            refresh_token=refresh_token,
            access_token_expires_in_seconds=self._access_token_expires_in_seconds,
        )
