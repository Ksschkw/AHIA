"""The session cookies a browser holds.

A browser should not have to be told to attach a header to every request. The
token service already issues an access token and a refresh token; this module is
the transport that puts them where a browser can carry them - `HttpOnly`
cookies, so no script on the page can read them, and no client code has to
remember to send anything.

Four attributes are decisions rather than defaults:

- **`HttpOnly`** so an injected script cannot read the session. A token kept in
  `localStorage` is readable by any script that runs on the origin, which turns
  every XSS into a full account takeover.
- **`SameSite=Lax`**, which is what replaces a CSRF token for the common case: a
  cross-site form post does not carry the cookie, so it arrives unauthenticated
  rather than authenticated by somebody else's session.
- **`Secure` in production only.** A `Secure` cookie is not sent over plain HTTP,
  so setting it on a local development server over `http://` would silently
  break every login there.
- **The refresh cookie is scoped to the auth path.** It is only ever needed by
  `/auth/refresh` and `/auth/logout`, and a credential that is sent nowhere else
  cannot leak through any other route's logs or error reports.

The access token is still issued in the response body and still accepted from an
`Authorization` header, because a mobile client, a script and the interactive
documentation have no cookie jar. The cookie is a transport, not a second
authentication mechanism: both paths end at the same token service.
"""

from __future__ import annotations

from typing import Final, Literal, Protocol

from fastapi import Request, Response

from ahia.core.config import AppEnvironment, Settings

#: The access token, sent with every request to the API.
SESSION_COOKIE_NAME: Final[str] = "ahia_session"

#: The refresh token, sent only to the auth endpoints that rotate or end it.
REFRESH_COOKIE_NAME: Final[str] = "ahia_refresh"

#: Where the refresh cookie is valid. Narrow on purpose: an endpoint outside
#: this prefix never receives it.
REFRESH_COOKIE_PATH: Final[str] = "/api/v1/auth"

#: Long enough for the access token's own lifetime and no longer. The browser
#: dropping the cookie early costs one silent refresh, so this is guidance rather
#: than the decision - the token's expiry is.
_ACCESS_COOKIE_MAX_AGE_SECONDS: Final[int] = 60 * 60

_SECONDS_PER_DAY: Final[int] = 24 * 60 * 60


def _is_secure(settings: Settings) -> bool:
    return settings.app_env is AppEnvironment.PRODUCTION


#: Lax, always. It is what stops another origin's form post from arriving with
#: the session attached, which is the CSRF defence for every state-changing
#: request; the only reason to choose anything else would be a cross-site embed
#: this API does not have.
_SAMESITE: Final[Literal["lax"]] = "lax"


class IssuedSessionLike(Protocol):
    """The shape a session must have to be written as cookies.

    Structural rather than an import of `IssuedSession`, because this module is
    cross-cutting and a core module importing a service would be the layering
    broken in the one direction it must never break.
    """

    @property
    def access_token(self) -> str: ...

    @property
    def refresh_token(self) -> str: ...


def session_cookie_names() -> tuple[str, str]:
    """Return the cookie names, so tests and clients do not hard-code them twice."""
    return SESSION_COOKIE_NAME, REFRESH_COOKIE_NAME


def read_access_token(request: Request) -> str | None:
    """Return the access token the request carries in its session cookie."""
    value = request.cookies.get(SESSION_COOKIE_NAME)
    return value or None


def read_refresh_token(request: Request) -> str | None:
    """Return the refresh token the request carries in its refresh cookie."""
    value = request.cookies.get(REFRESH_COOKIE_NAME)
    return value or None


def set_session_cookies(
    response: Response, *, settings: Settings, issued: IssuedSessionLike
) -> None:
    """Write the session cookies for a freshly issued session."""
    access_token = issued.access_token
    refresh_token = issued.refresh_token
    secure = _is_secure(settings)

    response.set_cookie(
        SESSION_COOKIE_NAME,
        access_token,
        max_age=_ACCESS_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=secure,
        samesite=_SAMESITE,
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        max_age=settings.refresh_token_ttl_days * _SECONDS_PER_DAY,
        httponly=True,
        secure=secure,
        samesite=_SAMESITE,
        path=REFRESH_COOKIE_PATH,
    )


def clear_session_cookies(response: Response, *, settings: Settings) -> None:
    """Remove both cookies, matching the attributes they were written with.

    A cookie is identified by name, domain and path: clearing one written with a
    path of `/api/v1/auth` by deleting the path `/` leaves the original in place,
    and the caller believes they are signed out.
    """
    secure = _is_secure(settings)
    response.delete_cookie(
        SESSION_COOKIE_NAME, path="/", httponly=True, secure=secure, samesite=_SAMESITE
    )
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite=_SAMESITE,
    )
