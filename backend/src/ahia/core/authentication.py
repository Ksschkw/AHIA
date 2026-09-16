"""Request authentication.

Turns an `Authorization` header into a `Principal`: an authenticated identity,
nothing more. It deliberately does not resolve a tenant, a role or a permission,
because those are separate facts with separate failure modes, and collapsing them
here is how an authenticated stranger becomes an authorized member.

The principal is the input to every authorization decision. It carries the
subject and the token's identity so a revoked token can be traced and a session
can be ended, and it carries nothing that came from the request body.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from fastapi import Request

from ahia.core.errors import UnauthenticatedError
from ahia.core.security import TokenClaims, TokenService
from ahia.core.session_cookies import read_access_token

_BEARER_PREFIX: Final[str] = "bearer "


@dataclass(frozen=True, slots=True)
class Principal:
    """An authenticated identity.

    ``subject`` is the user identifier from the token. It is a string in the
    token and a UUID here, because a malformed subject is a malformed token, not
    a lookup that returns nothing.
    """

    user_id: UUID
    token_identifier: str
    issued_at: datetime
    expires_at: datetime
    session_id: str | None = None

    def describe_for_audit(self) -> dict[str, str]:
        """Return the fields an audit record needs, and nothing else."""
        description = {"actor_id": str(self.user_id), "token_id": self.token_identifier}
        if self.session_id is not None:
            description["session_id"] = self.session_id
        return description


def extract_bearer_token(authorization_header: str | None) -> str:
    """Return the token from an `Authorization` header.

    Every failure mode raises the same external error: a missing header, a
    different scheme, an empty token and a malformed token are one answer to a
    client. The internal detail says which one it was, because that distinction
    matters to whoever is debugging and not to whoever is probing.
    """
    if authorization_header is None or not authorization_header.strip():
        raise UnauthenticatedError(
            operation="extract_bearer_token",
            entity="authorization_header",
            detail="no Authorization header was supplied",
        )

    if not authorization_header.lower().startswith(_BEARER_PREFIX):
        raise UnauthenticatedError(
            operation="extract_bearer_token",
            entity="authorization_header",
            detail="authorization scheme is not bearer",
        )

    token = authorization_header[len(_BEARER_PREFIX) :].strip()
    if not token:
        raise UnauthenticatedError(
            operation="extract_bearer_token",
            entity="authorization_header",
            detail="bearer scheme presented with an empty token",
        )
    return token


def principal_from_claims(claims: TokenClaims) -> Principal:
    """Build a principal from validated token claims.

    The subject must be a UUID. A token with a non-UUID subject is a token this
    application did not issue, or one that was minted against a different
    identity model, and either way it must not reach a lookup.
    """
    try:
        user_id = UUID(claims.subject)
    except (ValueError, AttributeError, TypeError) as malformed_subject:
        raise UnauthenticatedError(
            operation="principal_from_claims",
            entity="access_token",
            detail="token subject is not a user identifier",
            cause=malformed_subject,
        ) from malformed_subject

    return Principal(
        user_id=user_id,
        token_identifier=claims.token_identifier,
        issued_at=claims.issued_at,
        expires_at=claims.expires_at,
        session_id=claims.session_id,
    )


def authenticate(authorization_header: str | None, token_service: TokenService) -> Principal:
    """Authenticate a request from its `Authorization` header.

    Validation is entirely inside `TokenService`: the signature, the issuer, the
    audience, the expiry and the token type. Duplicating any of it here would
    create a second place to get it wrong.
    """
    token = extract_bearer_token(authorization_header)
    claims = token_service.decode_access_token(token)
    return principal_from_claims(claims)


def authenticate_request(request: Request, token_service: TokenService) -> Principal:
    """Authenticate a browser request from its session cookie, or any request from its header.

    The header is checked first so that a script, the interactive documentation and
    a mobile client keep working unchanged, and so that a caller who deliberately
    presents a token is not silently overridden by a cookie from a previous login.

    A cookie is not a weaker credential here: it carries exactly the same access
    token, and the same validation decides whether it is genuine. The difference
    is only who attaches it - the browser, automatically, rather than every call
    site.
    """
    authorization_header = request.headers.get("authorization")
    if authorization_header:
        return authenticate(authorization_header, token_service)

    token = read_access_token(request)
    if token is None:
        raise UnauthenticatedError(
            operation="authenticate_request",
            entity="session",
            detail=("neither an Authorization header nor a session cookie was presented"),
        )
    claims = token_service.decode_access_token(token)
    return principal_from_claims(claims)
