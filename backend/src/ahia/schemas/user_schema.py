"""Transport contracts for the user slice.

Pydantic lives here and nowhere else, because the wire format is a transport
concern. The schema answers "is this a well-formed request", and the entity
answers "is this a valid user". Both checks exist: the schema produces a precise
422 for a client, and the entity keeps the invariant true regardless of how it
was constructed.

The response schema is explicit rather than derived from the entity, and that is
deliberate. A derived schema is how a field added to the domain quietly becomes a
field published to every client. Adding a field here is a decision, and a test
asserts that no credential-shaped field can appear in a response.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

from ahia.models.entities.user_model import UserModel

#: The same shapes the domain enforces, expressed for the wire. Kept in step with
#: the entity by a test that feeds the same inputs to both.
_EMAIL_PATTERN: Final[str] = r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"
_PHONE_PATTERN: Final[str] = r"^\+?[0-9\s()\-.]{7,20}$"

#: An email address as it arrives over HTTP.
EmailAddress = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=254,
        pattern=_EMAIL_PATTERN,
    ),
]

#: A phone number as it arrives over HTTP. Separators are accepted because people
#: type them; the entity normalizes them away.
PhoneNumber = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=7, max_length=20, pattern=_PHONE_PATTERN),
]

GivenName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]

FamilyName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]


class UserProfileUpdateSchema(BaseModel):
    """A partial profile update.

    Every field is optional: the request describes what to change, and an omitted
    field means "leave it alone". `extra="forbid"` rejects an unknown field
    instead of ignoring it, so a client that misspells a field learns immediately
    rather than believing it saved something.
    """

    model_config = ConfigDict(extra="forbid")

    first_name: GivenName | None = None
    last_name: FamilyName | None = None
    email: EmailAddress | None = None
    phone: PhoneNumber | None = None

    def to_entity_changes(self) -> dict[str, str | None]:
        """Return the fields the caller actually sent.

        `exclude_unset` is what makes "omitted" different from "explicitly null".
        The distinction matters for contacts: sending no email leaves the address
        alone, and the service refuses a change that would leave the account
        unreachable.
        """
        return self.model_dump(exclude_unset=True)


class UserResponseSchema(BaseModel):
    """The user as a client sees it.

    There is no password hash here, and there never will be: a test asserts that
    no field name in this schema is credential-shaped. Email and phone are
    present because this is the caller's own profile, which they already know.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    first_name: str
    last_name: str | None
    email: str | None
    phone: str | None
    is_active: bool
    is_email_verified: bool
    is_phone_verified: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None

    @classmethod
    def from_entity(cls, user: UserModel) -> UserResponseSchema:
        """Map the domain entity to the response body."""
        return cls(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            phone=user.phone,
            is_active=user.is_active,
            is_email_verified=user.is_email_verified,
            is_phone_verified=user.is_phone_verified,
            created_at=user.created_at,
            updated_at=user.updated_at,
            last_login_at=user.last_login_at,
        )


class UserSummarySchema(BaseModel):
    """A user as another member of the same business sees them.

    Narrower than the self view on purpose: a colleague needs to know who
    recorded a sale, not how to contact them privately. Personal contact details
    are the account holder's to share.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    full_name: str
    is_active: bool

    @classmethod
    def from_entity(cls, user: UserModel) -> UserSummarySchema:
        return cls(id=user.id, full_name=user.full_name, is_active=user.is_active)


def is_credential_shaped_field_name(field_name: str) -> bool:
    """Return True when a field name suggests credential material.

    Used by the response-schema tests so the rule is checked rather than
    remembered. The fragments match the redaction rules in core/logging.
    """
    lowered = field_name.lower()
    return any(
        fragment in lowered
        for fragment in ("password", "secret", "token", "hash", "api_key", "credential")
    )
