"""Security headers middleware.

Headers are applied to every response, including error responses and responses
produced by the framework before a route was reached. A header that is only set
on successful responses protects nothing.

The policy is deliberately restrictive: this API returns JSON and file URLs, not
HTML, so no content needs to be allowed to load. The web application sets its own
policy for its own origin.
"""

from __future__ import annotations

from typing import Final

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Applied when configuration supplies nothing. `default-src 'none'` is correct
#: for a JSON API and becomes wrong the moment it serves a page, which is why it
#: is configuration rather than a constant.
DEFAULT_CONTENT_SECURITY_POLICY: Final[str] = (
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
)


class SecurityHeadersMiddleware:
    """Attach the baseline security headers to every HTTP response."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        hsts_max_age_seconds: int = 31_536_000,
        content_security_policy: str = DEFAULT_CONTENT_SECURITY_POLICY,
        enabled: bool = True,
        is_production: bool = False,
    ) -> None:
        self.app = app
        self.hsts_max_age_seconds = hsts_max_age_seconds
        self.content_security_policy = content_security_policy
        self.enabled = enabled
        self.is_production = is_production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.enabled:
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Content-Security-Policy"] = self.content_security_policy
                # A JSON API never needs a browser feature, and denying them all
                # removes a category of client-side attack.
                headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
                # HSTS is only meaningful over TLS, and sending it from a local
                # development server would pin a developer's browser to https
                # for a host they run over http.
                if self.is_production:
                    headers["Strict-Transport-Security"] = (
                        f"max-age={self.hsts_max_age_seconds}; includeSubDomains"
                    )
            await send(message)

        await self.app(scope, receive, send_with_headers)
