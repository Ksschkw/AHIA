"""HTTP transport for authentication.

Five endpoints, each of which parses a request through a schema, calls one
service method and returns a response schema. No branch beyond dependency
wiring, no hashing, no session decision: those live in the service.

Rate limiting is not implemented here. The middleware classifies these paths as
the authentication bucket, so the limit applies before a handler runs and cannot
be forgotten for one route.
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from ahia.core.authentication import Principal
from ahia.routers.user_router import require_principal
from ahia.schemas.auth_schema import (
    AuthenticatedSessionSchema,
    ChangePasswordSchema,
    LoginSchema,
    LogoutSchema,
    PasswordChangedSchema,
    RefreshSessionSchema,
    RegisterUserSchema,
)
from ahia.schemas.user_schema import UserResponseSchema
from ahia.services.auth_service import AuthService, IssuedSession

_AUTH_ROUTER_PREFIX: Final[str] = "/auth"

router = APIRouter(prefix=_AUTH_ROUTER_PREFIX, tags=["auth"])


def get_auth_service(request: Request) -> AuthService:
    """Return the authentication service for this request."""
    service: AuthService = request.app.state.container.auth_service
    return service


AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
PrincipalDependency = Annotated[Principal, Depends(require_principal)]


def build_session_response(issued: IssuedSession) -> AuthenticatedSessionSchema:
    """Serialise an issued session.

    A pure mapping from domain values to the wire shape. It lives here rather
    than on the schema because a schema must not import a service, and rather
    than in the service because a service must not know the wire format.
    """
    return AuthenticatedSessionSchema(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        expires_in_seconds=issued.access_token_expires_in_seconds,
        user=UserResponseSchema.from_entity(issued.user),
    )


@router.post(
    "/register",
    response_model=AuthenticatedSessionSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and sign in",
)
async def register(
    payload: RegisterUserSchema,
    service: AuthServiceDependency,
) -> AuthenticatedSessionSchema:
    """Register a user, returning a session so no second request is needed."""
    issued = await service.register_user(
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        phone=payload.phone,
        password=payload.password,
    )
    return build_session_response(issued)


@router.post(
    "/login",
    response_model=AuthenticatedSessionSchema,
    summary="Exchange credentials for a session",
)
async def login(
    payload: LoginSchema,
    service: AuthServiceDependency,
) -> AuthenticatedSessionSchema:
    """Sign in with an email address or a phone number."""
    issued = await service.authenticate_user(
        identifier=payload.identifier,
        password=payload.password,
    )
    return build_session_response(issued)


@router.post(
    "/refresh",
    response_model=AuthenticatedSessionSchema,
    summary="Rotate a refresh token into a new session",
)
async def refresh(
    payload: RefreshSessionSchema,
    service: AuthServiceDependency,
) -> AuthenticatedSessionSchema:
    """Rotate the presented refresh token.

    The presented token is revoked as part of the exchange, so a token that is
    used twice is recognised as reuse and ends the whole session family.
    """
    issued = await service.refresh_session(refresh_token=payload.refresh_token)
    return build_session_response(issued)


@router.post(
    "/logout",
    response_model=LogoutSchema,
    summary="End the session behind a refresh token",
)
async def logout(
    payload: RefreshSessionSchema,
    service: AuthServiceDependency,
) -> LogoutSchema:
    """Sign out.

    Idempotent: an unknown or already-revoked token still produces success, so a
    client that has lost track of its session can reach a signed-out state.
    """
    await service.revoke_session(refresh_token=payload.refresh_token)
    return LogoutSchema()


@router.post(
    "/password",
    response_model=PasswordChangedSchema,
    summary="Change the authenticated user's password",
)
async def change_password(
    payload: ChangePasswordSchema,
    principal: PrincipalDependency,
    service: AuthServiceDependency,
) -> PasswordChangedSchema:
    """Change the caller's password and end their other sessions."""
    revoked = await service.change_password(
        user_id=principal.user_id,
        current_password=payload.current_password,
        new_password=payload.new_password,
        current_session_id=_session_uuid(principal),
    )
    return PasswordChangedSchema(other_sessions_revoked=revoked)


def _session_uuid(principal: Principal) -> UUID | None:
    """Return the session identifier from the token, when it carries one.

    A token issued before sessions carried the claim has none, in which case every
    session is revoked rather than none: the safe direction for a password change.
    """
    if principal.session_id is None:
        return None
    try:
        return UUID(principal.session_id)
    except ValueError:
        return None
