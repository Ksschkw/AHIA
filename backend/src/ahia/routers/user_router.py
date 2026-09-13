"""HTTP transport for the user's own account.

A handler here does exactly three things: parse the request through a schema,
call one service method, and return a response schema. There is no branch beyond
dependency wiring, no database access, no permission decision and no error
conversion - typed errors are mapped centrally by the error handler middleware.

That constraint is what makes the layer testable in isolation and what keeps a
business rule from existing in two places at once.

The routes are also deliberately self-scoped. `{user_id}` never appears in a path
here, so a client cannot ask for another account by changing an identifier. When
administrative endpoints arrive they scope by membership in the service, not by
trusting a path parameter.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Header, Request, status

from ahia.core.authentication import Principal, authenticate
from ahia.schemas.user_schema import UserProfileUpdateSchema, UserResponseSchema
from ahia.services.user_service import UserService

_USER_ROUTER_PREFIX: Final[str] = "/users"
_AUTHORIZATION_HEADER_NAME: Final[str] = "Authorization"

router = APIRouter(prefix=_USER_ROUTER_PREFIX, tags=["users"])


def get_user_service(request: Request) -> UserService:
    """Return the user service for this request."""
    service: UserService = request.app.state.container.user_service
    return service


async def require_principal(
    request: Request,
    authorization: Annotated[str | None, Header(alias=_AUTHORIZATION_HEADER_NAME)] = None,
) -> Principal:
    """Resolve the caller's authenticated identity.

    Authentication only. A principal with no membership is authenticated and
    authorized for nothing, which is the correct state for a person whose
    invitation has not been accepted yet.
    """
    token_service = request.app.state.container.token_service
    return authenticate(authorization, token_service)


PrincipalDependency = Annotated[Principal, Depends(require_principal)]
UserServiceDependency = Annotated[UserService, Depends(get_user_service)]


@router.get(
    "/me",
    response_model=UserResponseSchema,
    summary="Read the authenticated user's own profile",
)
async def read_own_profile(
    principal: PrincipalDependency,
    service: UserServiceDependency,
) -> UserResponseSchema:
    """Return the caller's own profile."""
    user = await service.get_authenticated_user(principal)
    return UserResponseSchema.from_entity(user)


@router.patch(
    "/me",
    response_model=UserResponseSchema,
    summary="Update the authenticated user's own profile",
)
async def update_own_profile(
    payload: UserProfileUpdateSchema,
    principal: PrincipalDependency,
    service: UserServiceDependency,
) -> UserResponseSchema:
    """Apply a partial update to the caller's own profile."""
    user = await service.update_own_profile(principal, changes=payload.to_entity_changes())
    return UserResponseSchema.from_entity(user)


@router.delete(
    "/me",
    response_model=UserResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Deactivate the authenticated user's own account",
)
async def deactivate_own_account(
    principal: PrincipalDependency,
    service: UserServiceDependency,
) -> UserResponseSchema:
    """Deactivate the caller's own account.

    A `DELETE` that deactivates rather than deletes: business history references
    this person, and the response body reports the resulting state so a client
    does not have to guess whether the account is gone or merely inactive.
    """
    user = await service.deactivate_own_account(principal)
    return UserResponseSchema.from_entity(user)
