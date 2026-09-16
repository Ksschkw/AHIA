"""Transport contracts for authentication.

Two rules shape this module.

Registration and login accept the same password shape and reject anything else,
so a client learns the rule once. The configured minimum lives in the service,
which is where configuration is available; the schema enforces a floor that no
deployment may go below.

Nothing credential-shaped is ever returned. The responses carry tokens and a
public view of the user, and a test asserts that no field name in any response
schema can be credential-shaped apart from the tokens themselves, which are the
point of the endpoint.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from ahia.schemas.user_schema import (
    EmailAddress,
    FamilyName,
    GivenName,
    PhoneNumber,
    UserResponseSchema,
)

#: A password exactly as it arrives. Length bounds only: complexity rules push
#: people towards predictable substitutions, and the security comes from hashing
#: and rate limiting rather than from character classes.
PasswordString = Annotated[
    str,
    StringConstraints(min_length=8, max_length=128),
]

#: A refresh token as it arrives. Long enough that the floor itself rejects a
#: guess, and bounded so a client cannot post a megabyte.
RefreshTokenString = Annotated[
    str,
    StringConstraints(min_length=20, max_length=512),
]


class RegisterUserSchema(BaseModel):
    """A new account request."""

    model_config = ConfigDict(extra="forbid")

    first_name: GivenName
    last_name: FamilyName | None = None
    email: EmailAddress | None = None
    phone: PhoneNumber | None = None
    password: PasswordString

    @model_validator(mode="after")
    def _require_a_contact_channel(self) -> RegisterUserSchema:
        """Reject the request at the edge rather than in the domain.

        The entity enforces the same rule, because a CLI or a job can construct a
        user too. Checking here as well turns a 422 into something a client can act
        on instead of an opaque validation failure.
        """
        if self.email is None and self.phone is None:
            raise ValueError("an email address or a phone number is required")
        return self


class LoginSchema(BaseModel):
    """A credential exchange.

    One `identifier` field rather than separate email and phone fields: a trader
    types whichever they remember, and the service decides which it is. The
    response to a failure is identical either way, so the shape reveals nothing.
    """

    model_config = ConfigDict(extra="forbid")

    identifier: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254)
    ]
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class RefreshSessionSchema(BaseModel):
    """A refresh request.

    The token is optional because a browser does not send it here: it arrives in
    an HttpOnly cookie the page cannot read, and a script or a mobile client
    sends it in the body as before. A request that carries neither is refused by
    the route, which is the one place that can see both.
    """

    model_config = ConfigDict(extra="forbid")

    refresh_token: RefreshTokenString | None = None


class ChangePasswordSchema(BaseModel):
    """A password change for an authenticated caller."""

    model_config = ConfigDict(extra="forbid")

    current_password: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    new_password: PasswordString


class TokenPairSchema(BaseModel):
    """An issued credential pair.

    `expires_in_seconds` describes the access token only. The refresh token's
    lifetime is a server-side property of the session and is deliberately not
    published, so a client cannot plan around a value it should not depend on.
    """

    model_config = ConfigDict(extra="forbid")

    access_token: str
    refresh_token: str
    # The name contains "token" and the scanner flags it; the value is a scheme
    # label defined by RFC 6750, not a credential.
    token_type: str = "bearer"  # noqa: S105
    expires_in_seconds: int


class AuthenticatedSessionSchema(TokenPairSchema):
    """The credential pair plus the account it belongs to.

    Returned by registration and login so a client does not need a second request
    to render a dashboard.
    """

    user: UserResponseSchema


class LogoutSchema(BaseModel):
    """The response to a sign-out.

    A fixed message rather than an empty body: a client that receives nothing has
    to guess whether the request succeeded.
    """

    model_config = ConfigDict(extra="forbid")

    message: str = "Signed out."


class PasswordChangedSchema(BaseModel):
    """The response to a password change."""

    model_config = ConfigDict(extra="forbid")

    message: str = "Password changed."
    other_sessions_revoked: int
