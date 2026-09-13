"""Security primitives: password hashing, token issuance and token generation.

Three rules shape this module.

1. No hand-rolled cryptography. Password hashing is Argon2id through
   argon2-cffi, token signing is HMAC through PyJWT, and randomness comes from
   `secrets`. Nothing here implements a primitive.
2. Comparison is constant time. A password check, a refresh-token check and a
   signature check all use a comparison that does not leak how much of a guess
   was correct.
3. Failures are opaque externally and specific internally. A caller learns
   "authentication is required"; the engineer reads "token expired" or
   "audience mismatch" in the log, with the reason and nothing else. A token
   value is never logged.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import uuid4

import jwt
from argon2 import PasswordHasher as Argon2PasswordHasher
from argon2 import Type as Argon2Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from ahia.core.errors import (
    AuthenticationError,
    ConfigurationError,
    UnauthenticatedError,
    require_correlation_id,
)

#: Claims every access token carries. `typ` is present so a refresh token can
#: never be replayed as an access token even if the signing key is shared.
#: The value is a token-type marker, not a credential; the scanner flags the
#: name because it contains "token".
_ACCESS_TOKEN_TYPE: Final[str] = "access"  # noqa: S105

#: Clock skew tolerated when validating `exp`, `iat` and `nbf`.
_ALLOWED_CLOCK_SKEW_SECONDS: Final[int] = 30

#: Refresh tokens are long random strings, not JWTs: they are looked up and
#: revoked server-side, so they carry no information worth decoding.
_REFRESH_TOKEN_BYTES: Final[int] = 48


@dataclass(frozen=True, slots=True)
class TokenClaims:
    """The validated contents of an access token.

    `session_id` links the token to the refresh session it was issued with. It is
    optional because a token can be issued without one, and it exists now so that a
    per-request session check can be added later without changing the token
    format or invalidating every issued token.
    """

    subject: str
    token_identifier: str
    issued_at: datetime
    expires_at: datetime
    issuer: str
    audience: str
    session_id: str | None = None


class PasswordHasher:
    """Argon2id password hashing with configuration-driven cost parameters."""

    def __init__(
        self,
        *,
        time_cost: int,
        memory_cost_kib: int,
        parallelism: int,
        minimum_length: int,
    ) -> None:
        self._hasher = Argon2PasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_cost_kib,
            parallelism=parallelism,
            # Argon2id resists both side-channel and GPU attacks; Argon2i and
            # Argon2d each trade one away.
            type=Argon2Type.ID,
            hash_len=32,
            salt_len=16,
        )
        self.minimum_length = minimum_length

    def validate_password_strength(self, password: str) -> None:
        """Reject a password that does not meet the configured policy.

        The external message never states the rule that failed, because that
        turns the registration endpoint into a policy oracle. The minimum length
        is published in the API documentation instead.
        """
        if len(password) < self.minimum_length:
            raise AuthenticationError(
                operation="validate_password_strength",
                entity="user",
                detail=f"password shorter than the configured minimum of {self.minimum_length}",
            )

    def hash_password(self, password: str) -> str:
        """Return an Argon2id hash. The plaintext is never stored or logged."""
        return self._hasher.hash(password)

    def verify_password(self, password: str, password_hash: str) -> bool:
        """Return True when the password matches the stored hash.

        Every failure mode - a mismatch, a malformed hash, unsupported
        parameters - returns False rather than raising a distinct error, so a
        caller cannot
        distinguish "wrong password" from "corrupt record", and the caller's
        external response is identical either way.
        """
        try:
            return self._hasher.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        """Return True when a stored hash uses parameters below the current cost.

        Called after a successful verification, which is the only moment the
        plaintext is available to re-hash with.
        """
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return True


class TokenService:
    """Issues and validates access tokens, and mints opaque refresh tokens."""

    def __init__(
        self,
        *,
        secret: str,
        algorithm: str,
        issuer: str,
        audience: str,
        access_token_ttl_minutes: int,
        refresh_token_pepper: str,
        public_token_bytes: int,
    ) -> None:
        if len(secret) < 16:
            raise ConfigurationError(
                operation="configure_token_service",
                entity="jwt_secret",
                detail="signing secret is too short to be safe",
            )
        self._secret = secret
        self._algorithm = algorithm
        self._issuer = issuer
        self._audience = audience
        self._access_token_ttl = timedelta(minutes=access_token_ttl_minutes)
        self._refresh_token_pepper = refresh_token_pepper.encode("utf-8")
        self._public_token_bytes = public_token_bytes

    def issue_access_token(
        self,
        *,
        subject: str,
        now: datetime | None = None,
        session_identifier: str | None = None,
    ) -> tuple[str, TokenClaims]:
        """Return a signed short-lived access token and its claims.

        `session_identifier` is embedded as the `sid` claim when supplied. It is
        what makes a future device or session revocation check possible without a
        token-format change or an invalidation of every issued token.
        """
        issued_at = now or datetime.now(UTC)
        expires_at = issued_at + self._access_token_ttl
        token_identifier = uuid4().hex

        payload: dict[str, Any] = {
            "sub": subject,
            "iss": self._issuer,
            "aud": self._audience,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": token_identifier,
            "typ": _ACCESS_TOKEN_TYPE,
        }
        if session_identifier is not None:
            payload["sid"] = session_identifier

        encoded = jwt.encode(payload, self._secret, algorithm=self._algorithm)
        claims = TokenClaims(
            subject=subject,
            token_identifier=token_identifier,
            issued_at=issued_at,
            expires_at=expires_at,
            issuer=self._issuer,
            audience=self._audience,
            session_id=session_identifier,
        )
        return encoded, claims

    def decode_access_token(self, token: str) -> TokenClaims:
        """Validate a token and return its claims.

        Every rejection raises the same external error. Internally the reason is
        recorded, because "the client sent an expired token" and "the client sent
        a token signed with the old key" are very different operational facts.
        """
        try:
            payload = jwt.decode(
                token,
                self._secret,
                # An allowlist, never the algorithm named in the token header:
                # trusting the header is the algorithm-confusion vulnerability.
                algorithms=[self._algorithm],
                audience=self._audience,
                issuer=self._issuer,
                leeway=_ALLOWED_CLOCK_SKEW_SECONDS,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
        except jwt.ExpiredSignatureError as expired_error:
            raise UnauthenticatedError(
                operation="decode_access_token",
                entity="access_token",
                detail="token expired",
                cause=expired_error,
            ) from expired_error
        except jwt.InvalidAudienceError as audience_error:
            raise UnauthenticatedError(
                operation="decode_access_token",
                entity="access_token",
                detail="token audience does not match the configured audience",
                cause=audience_error,
            ) from audience_error
        except jwt.InvalidIssuerError as issuer_error:
            raise UnauthenticatedError(
                operation="decode_access_token",
                entity="access_token",
                detail="token issuer does not match the configured issuer",
                cause=issuer_error,
            ) from issuer_error
        except jwt.InvalidTokenError as invalid_error:
            raise UnauthenticatedError(
                operation="decode_access_token",
                entity="access_token",
                detail=f"token rejected: {type(invalid_error).__name__}",
                cause=invalid_error,
            ) from invalid_error

        token_type = payload.get("typ")
        if token_type != _ACCESS_TOKEN_TYPE:
            raise UnauthenticatedError(
                operation="decode_access_token",
                entity="access_token",
                detail=f"token type is not an access token: typ={token_type}",
            )

        subject = payload.get("sub")
        token_identifier = payload.get("jti")
        if not isinstance(subject, str) or not subject:
            raise UnauthenticatedError(
                operation="decode_access_token",
                entity="access_token",
                detail="token has no subject claim",
            )
        if not isinstance(token_identifier, str) or not token_identifier:
            raise UnauthenticatedError(
                operation="decode_access_token",
                entity="access_token",
                detail="token has no identifier claim",
            )

        session_identifier = payload.get("sid")
        return TokenClaims(
            subject=subject,
            token_identifier=token_identifier,
            issued_at=datetime.fromtimestamp(int(payload["iat"]), tz=UTC),
            expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=UTC),
            issuer=str(payload["iss"]),
            audience=str(payload["aud"]),
            session_id=str(session_identifier) if session_identifier is not None else None,
        )

    # ------------------------------------------------------------------
    # Refresh tokens
    # ------------------------------------------------------------------

    def generate_refresh_token(self) -> tuple[str, str]:
        """Return a new refresh token and the hash to store.

        The plaintext is returned exactly once, to the client. Only the hash is
        persisted, so a database disclosure does not hand out live sessions.
        """
        plaintext = secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)
        return plaintext, self.hash_bearer_token(plaintext)

    def hash_bearer_token(self, plaintext: str) -> str:
        """Return the peppered digest stored for a bearer credential.

        A pepper is used as well as randomness because these credentials are
        long-lived: if the database alone leaks, the hashes are still useless
        without the pepper from the environment. Used for refresh tokens and for
        membership invitations alike.
        """
        return hmac.new(
            self._refresh_token_pepper,
            plaintext.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def verify_refresh_token(self, plaintext: str, stored_hash: str) -> bool:
        """Compare a presented bearer credential with the stored digest."""
        return hmac.compare_digest(self.hash_bearer_token(plaintext), stored_hash)

    # ------------------------------------------------------------------
    # Public share tokens
    # ------------------------------------------------------------------

    def generate_public_token(self) -> str:
        """Return a non-guessable token for a shareable artifact.

        Used for invoice, shipment and report links, where the token is the
        authorization. It is intentionally not derived from any identifier: a
        derived token is enumerable.
        """
        return secrets.token_urlsafe(self._public_token_bytes)


def fingerprint_for_log(value: str, *, visible_characters: int = 4) -> str:
    """Return a stable, non-reversible reference to a sensitive value.

    Logs sometimes need to correlate a token across two events without writing
    the token. A truncated digest plus the last few characters is enough to
    match records and useless to an attacker.
    """
    if not value:
        return "empty"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    tail = value[-visible_characters:] if len(value) > visible_characters else ""
    return f"sha256:{digest} tail:{tail}"


def constant_time_equals(left: str, right: str) -> bool:
    """Compare two strings without leaking length or prefix through timing."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def current_correlation_id_for_security_event() -> str:
    """Return the correlation ID to attach to an authorization decision log.

    A thin wrapper so call sites do not reach into the error module directly and
    a future change to how decisions are correlated has one place to change.
    """
    return require_correlation_id()
