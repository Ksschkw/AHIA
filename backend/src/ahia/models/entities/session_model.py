"""The session entity: a refresh credential issued to one device.

A session is the durable half of authentication. The access token is short-lived
and stateless; the session is what can be revoked, rotated and audited.

Design decisions worth stating, because each one is a security property:

The refresh token is never stored
    Only a peppered digest is persisted. A database disclosure therefore does not
    hand out live sessions, and a session row cannot be replayed by whoever reads
    it.

Rotation keeps the family
    Refreshing issues a new session and marks the old one rotated, recording which
    session replaced it. Keeping the chain is what makes reuse detectable: if a
    rotated token is presented again, either it was stolen or the legitimate
    holder's new token was, and the right response is to end the whole family
    rather than guess.

Expiry and revocation are separate
    A session can be unexpired and revoked (signed out, password changed,
    suspected theft) or expired and never revoked. Both deny; they are different
    facts and the audit trail distinguishes them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from ahia.core.errors import EntityInvariantError

_MAXIMUM_TOKEN_HASH_LENGTH: int = 128
_MAXIMUM_REVOCATION_REASON_LENGTH: int = 64


@dataclass(frozen=True, slots=True)
class SessionModel:
    """One refresh session, bound to one user and optionally one device."""

    id: UUID
    user_id: UUID
    refresh_token_hash: str
    expires_at: datetime
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    revocation_reason: str | None = None
    replaced_by_session_id: UUID | None = None
    device_id: UUID | None = None

    def __post_init__(self) -> None:
        if not self.refresh_token_hash.strip():
            raise EntityInvariantError(
                operation="build_session",
                entity="session",
                identifier=str(self.id),
                detail="refresh_token_hash is empty",
            )
        if len(self.refresh_token_hash) > _MAXIMUM_TOKEN_HASH_LENGTH:
            raise EntityInvariantError(
                operation="build_session",
                entity="session",
                identifier=str(self.id),
                detail=f"refresh_token_hash exceeds {_MAXIMUM_TOKEN_HASH_LENGTH} characters",
            )
        _require_aware(self.created_at, field_name="created_at", session_id=self.id)
        _require_aware(self.expires_at, field_name="expires_at", session_id=self.id)
        if self.expires_at <= self.created_at:
            raise EntityInvariantError(
                operation="build_session",
                entity="session",
                identifier=str(self.id),
                detail="expires_at is not later than created_at",
            )
        if self.revocation_reason is not None and len(self.revocation_reason) > (
            _MAXIMUM_REVOCATION_REASON_LENGTH
        ):
            raise EntityInvariantError(
                operation="build_session",
                entity="session",
                identifier=str(self.id),
                detail="revocation_reason is too long",
            )
        if self.revoked_at is not None and self.revoked_at < self.created_at:
            raise EntityInvariantError(
                operation="build_session",
                entity="session",
                identifier=str(self.id),
                detail="revoked_at is earlier than created_at",
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def issue(
        cls,
        *,
        session_id: UUID,
        user_id: UUID,
        refresh_token_hash: str,
        expires_at: datetime,
        created_at: datetime,
        device_id: UUID | None = None,
    ) -> SessionModel:
        """Create a new session."""
        return cls(
            id=session_id,
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            expires_at=expires_at,
            created_at=created_at,
            device_id=device_id,
        )

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def is_expired(self, *, at: datetime) -> bool:
        return at >= self.expires_at

    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_active(self, *, at: datetime) -> bool:
        """Return True only when the session is neither revoked nor expired."""
        return not self.is_revoked() and not self.is_expired(at=at)

    def was_rotated(self) -> bool:
        """Return True when this session was replaced by a newer one."""
        return self.replaced_by_session_id is not None

    @property
    def is_reuse_suspect(self) -> bool:
        """Return True when a revoked-and-rotated token is being presented again.

        A rotated session whose token appears a second time means one of two
        copies is in the wrong hands. The caller's correct response is to end the
        whole session family, not just refuse this request.
        """
        return self.was_rotated()

    def describe_for_audit(self) -> dict[str, str]:
        """Return the fields an audit record needs, and no token material."""
        description = {
            "session_id": str(self.id),
            "user_id": str(self.user_id),
            "is_revoked": "true" if self.is_revoked() else "false",
        }
        if self.device_id is not None:
            description["device_id"] = str(self.device_id)
        return description

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def rotate(
        self,
        *,
        replacement_session_id: UUID,
        at: datetime,
    ) -> SessionModel:
        """Return the session revoked because a replacement was issued."""
        return replace(
            self,
            revoked_at=at,
            revocation_reason="rotated",
            replaced_by_session_id=replacement_session_id,
            last_used_at=at,
        )

    def revoke(self, *, at: datetime, reason: str) -> SessionModel:
        """Return the session revoked for a stated reason.

        The reason is recorded because "the user signed out" and "the password
        changed" and "reuse was detected" are different events with different
        follow-up. Idempotent: revoking a revoked session keeps the first reason.
        """
        if self.is_revoked():
            return self
        return replace(self, revoked_at=at, revocation_reason=reason)

    def touch(self, *, at: datetime) -> SessionModel:
        """Return the session with its last-use timestamp updated.

        Updating this on every refresh is what makes an abandoned session
        distinguishable from an active one during incident review.
        """
        return replace(self, last_used_at=at)

    def bind_to_device(self, *, device_id: UUID) -> SessionModel:
        """Return the session bound to a device.

        Binding is what lets a single device be revoked without signing the person
        out everywhere.
        """
        return replace(self, device_id=device_id)


def _require_aware(moment: datetime, *, field_name: str, session_id: UUID) -> None:
    """Reject a naive timestamp, for the same reason the user entity does."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="build_session",
            entity="session",
            identifier=str(session_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
