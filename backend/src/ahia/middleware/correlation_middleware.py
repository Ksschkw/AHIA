"""Correlation ID middleware.

The correlation ID is the entire bridge between a client complaint and an
engineer's log search, so it is established before anything else runs and
returned on every response, including error responses.

An inbound ID is accepted only when it passes the format rules. A caller who
controls the header could otherwise inject control characters, a newline, or a
value large enough to make every log line for that request unusable.

The access log line records the method, the route and the status, and never the
query string: query strings carry tokens and personal data in real traffic, and
an access log is the most widely readable log a service produces.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Final

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ahia.core.errors import (
    clear_correlation_id,
    generate_correlation_id,
    sanitize_correlation_id,
    set_correlation_id,
)
from ahia.core.logging import StructuredLogger, get_logger

_ACCESS_LOGGER_NAME: Final[str] = "ahia.http.access"


class CorrelationIdMiddleware:
    """Bind a correlation ID to the request and return it on the response."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        header_name: str = "X-Correlation-ID",
        logger: StructuredLogger | None = None,
    ) -> None:
        self.app = app
        self.header_name = header_name
        self.logger = (logger or get_logger(_ACCESS_LOGGER_NAME)).bind(component="http")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = Headers(scope=scope).get(self.header_name)
        correlation_id = sanitize_correlation_id(inbound) or generate_correlation_id()
        set_correlation_id(correlation_id)

        state = scope.setdefault("state", {})
        state["correlation_id"] = correlation_id

        started_at = time.monotonic()
        response_status: dict[str, int] = {"status": 0}

        async def send_with_correlation_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_status["status"] = int(message["status"])
                MutableHeaders(scope=message)[self.header_name] = correlation_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_correlation_id)
        finally:
            duration_ms = round((time.monotonic() - started_at) * 1000, 2)
            self.logger.info(
                "http_request_completed",
                http_method=scope.get("method"),
                http_route=scope.get("path"),
                http_status=response_status["status"],
                duration_ms=duration_ms,
            )
            clear_correlation_id()


def configure_access_log_level(settings_log_level: str) -> None:
    """Silence uvicorn's own access logger.

    The application emits a structured access record in the middleware, and two
    access logs in different formats is one log too many.
    """
    logging.getLogger("uvicorn.access").propagate = False
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def extract_correlation_id(scope_or_request: Any) -> str | None:
    """Return the correlation ID attached to a scope or a request.

    Used by the error handler and by anything that needs to report the current
    request's ID without importing the context variable directly.
    """
    state = getattr(scope_or_request, "state", None)
    if state is not None and hasattr(state, "correlation_id"):
        value: Any = state.correlation_id
        return value if isinstance(value, str) else str(value)
    if isinstance(scope_or_request, dict):
        scope_state: Any = scope_or_request.get("state", {})
        candidate: Any = (
            scope_state.get("correlation_id") if isinstance(scope_state, dict) else None
        )
        return candidate if isinstance(candidate, str) else None
    return None
