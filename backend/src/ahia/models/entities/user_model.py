"""The user entity: a person with an AHIA identity.

This is the domain source of truth for a user, and it is deliberately
framework-free: no Pydantic, no SQLAlchemy, no FastAPI. Persistence maps to and
from it at the CRUD boundary.

Two decisions worth stating.

Authentication identity is separate from tenant membership
    A user exists once and may belong to several businesses through
    memberships. This entity therefore carries nothing about a role or a
    permission: an authenticated person with no active membership can do nothing,
    and that is correct.

Contacts are normalized here, not at the edge
    "  Emeka@Example.COM " and "emeka@example.com" are the same account, and a
    phone number written with spaces, dashes or a local trunk prefix is the same
    number. Normalization is a domain invariant because uniqueness depends on it:
    a database unique index on an unnormalized column does not prevent two
    accounts for one person.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.phone_number import (
    is_plausible_phone_number,
    normalize_phone_number,
)

_EMAIL_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

_MAXIMUM_NAME_LENGTH: Final[int] = 100
_MAXIMUM_EMAIL_LENGTH: Final[int] = 254
_MAXIMUM_PHONE_LENGTH: Final[int] = 20


def normalize_email(email: str | None) -> str | None:
    """Return the canonical form of an email address, or None.

    Lowercased and trimmed. The local part of an address is technically
    case-sensitive, but no mail provider in use treats it that way, and treating
    it as case-sensitive creates two accounts for one person.
    """
    if email is None:
        return None
    normalized = email.strip().lower()
    return normalized or None


def normalize_phone(phone: str | None) -> str | None:
    """Return the canonical syntax of a phone number, or None.

    Kept as a name on this entity because a user's own module is where a reader looks for
    it, and implemented by the shared rule in `phone_number` so that a customer's phone
    and a user's phone cannot end up canonicalised differently.
    """
    return normalize_phone_number(phone)


@dataclass(frozen=True, slots=True)
class UserModel:
    """A person's AHIA identity."""

    id: UUID
    first_name: str
    created_at: datetime
    updated_at: datetime
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    is_active: bool = True
    password_hash: str | None = None
    email_verified_at: datetime | None = None
    phone_verified_at: datetime | None = None
    last_login_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_aware(self.created_at, field_name="created_at", user_id=self.id)
        _require_aware(self.updated_at, field_name="updated_at", user_id=self.id)

        if self.updated_at < self.created_at:
            raise EntityInvariantError(
                operation="build_user",
                entity="user",
                identifier=str(self.id),
                detail="updated_at is earlier than created_at",
            )

        if not self.first_name.strip():
            raise EntityInvariantError(
                operation="build_user",
                entity="user",
                identifier=str(self.id),
                detail="first_name is empty after trimming",
            )
        if len(self.first_name) > _MAXIMUM_NAME_LENGTH:
            raise EntityInvariantError(
                operation="build_user",
                entity="user",
                identifier=str(self.id),
                detail=f"first_name exceeds {_MAXIMUM_NAME_LENGTH} characters",
            )

        if self.last_name is not None and len(self.last_name) > _MAXIMUM_NAME_LENGTH:
            raise EntityInvariantError(
                operation="build_user",
                entity="user",
                identifier=str(self.id),
                detail=f"last_name exceeds {_MAXIMUM_NAME_LENGTH} characters",
            )

        if self.email is None and self.phone is None:
            # A user with no contact channel can never authenticate and can never
            # be reached. Allowing one produces an account nobody can use and
            # nobody can find.
            raise EntityInvariantError(
                operation="build_user",
                entity="user",
                identifier=str(self.id),
                detail="a user needs at least one of email or phone",
            )

        if self.email is not None:
            if not _EMAIL_PATTERN.match(self.email):
                raise EntityInvariantError(
                    operation="build_user",
                    entity="user",
                    identifier=str(self.id),
                    detail="email is not a valid address shape",
                )
            if len(self.email) > _MAXIMUM_EMAIL_LENGTH:
                raise EntityInvariantError(
                    operation="build_user",
                    entity="user",
                    identifier=str(self.id),
                    detail=f"email exceeds {_MAXIMUM_EMAIL_LENGTH} characters",
                )

        if self.phone is not None:
            # The shared rule, so a user's phone and a customer's phone are judged by the
            # same shape rather than by two patterns that agree until one is edited.
            if not is_plausible_phone_number(self.phone):
                raise EntityInvariantError(
                    operation="build_user",
                    entity="user",
                    identifier=str(self.id),
                    detail="phone is not a valid number shape",
                )
            if len(self.phone) > _MAXIMUM_PHONE_LENGTH:
                raise EntityInvariantError(
                    operation="build_user",
                    entity="user",
                    identifier=str(self.id),
                    detail=f"phone exceeds {_MAXIMUM_PHONE_LENGTH} characters",
                )

        if self.password_hash is not None and not self.password_hash.strip():
            raise EntityInvariantError(
                operation="build_user",
                entity="user",
                identifier=str(self.id),
                detail="password_hash is present but empty",
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        first_name: str,
        now: datetime,
        last_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        password_hash: str | None = None,
    ) -> UserModel:
        """Create a new user, normalizing the contact fields.

        The normalizing constructor is the only supported way to make a user, so
        a caller cannot bypass normalization and defeat the uniqueness index.
        """
        return cls(
            id=user_id,
            first_name=first_name.strip(),
            last_name=last_name.strip() if last_name is not None else None,
            email=normalize_email(email),
            phone=normalize_phone(phone),
            password_hash=password_hash,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    @property
    def full_name(self) -> str:
        """Return the name to show a person, trimmed to what exists."""
        if self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name

    @property
    def has_password(self) -> bool:
        """Return True when the account can authenticate with a password."""
        return self.password_hash is not None

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def is_phone_verified(self) -> bool:
        return self.phone_verified_at is not None

    def describe_for_audit(self) -> dict[str, str]:
        """Return the identifiers written to an audit event.

        Identifiers only. An audit trail does not need a person's name, email or
        phone number to be useful, and those are personal data that should not be
        copied into a second store.
        """
        return {"user_id": str(self.id), "is_active": "true" if self.is_active else "false"}

    # ------------------------------------------------------------------
    # Transitions. Each returns a new instance; the entity is immutable.
    # ------------------------------------------------------------------

    def with_profile(
        self,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        at: datetime,
    ) -> UserModel:
        """Return the user with profile fields changed.

        A field passed as None keeps its current value, which is what a partial
        update from the transport layer means. Clearing a contact channel is
        expressed by changing the channel to another value, not by omission, so
        a request cannot silently remove the only way to reach an account.
        """
        candidate = replace(
            self,
            first_name=first_name.strip() if first_name is not None else self.first_name,
            last_name=last_name.strip() if last_name is not None else self.last_name,
            email=normalize_email(email) if email is not None else self.email,
            phone=normalize_phone(phone) if phone is not None else self.phone,
            updated_at=at,
        )
        return candidate

    def deactivate(self, *, at: datetime) -> UserModel:
        """Return the user deactivated.

        Deactivation, never deletion: business history references this person,
        and a receipt must not lose its seller because they left the business.
        """
        return replace(self, is_active=False, updated_at=at)

    def activate(self, *, at: datetime) -> UserModel:
        return replace(self, is_active=True, updated_at=at)

    def mark_email_verified(self, *, at: datetime) -> UserModel:
        return replace(self, email_verified_at=at, updated_at=at)

    def mark_phone_verified(self, *, at: datetime) -> UserModel:
        return replace(self, phone_verified_at=at, updated_at=at)

    def record_login(self, *, at: datetime) -> UserModel:
        """Return the user with the login timestamp recorded."""
        return replace(self, last_login_at=at, updated_at=at)

    def change_password_hash(self, *, password_hash: str, at: datetime) -> UserModel:
        """Return the user with a new password hash."""
        if not password_hash.strip():
            raise EntityInvariantError(
                operation="change_password_hash",
                entity="user",
                identifier=str(self.id),
                detail="refusing to store an empty password hash",
            )
        return replace(self, password_hash=password_hash, updated_at=at)


def _require_aware(moment: datetime, *, field_name: str, user_id: UUID) -> None:
    """Reject a naive timestamp.

    A naive timestamp in a multi-device system is a future debugging incident:
    the same instant means different things on different machines, and the
    synchronization ordering that depends on it breaks silently.
    """
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="build_user",
            entity="user",
            identifier=str(user_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
