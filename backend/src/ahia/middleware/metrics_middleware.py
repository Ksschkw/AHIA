"""Request metrics middleware.

Records one observation per completed request: the route, the status class and how long it took.
The registry is injected - built in the composition root and handed to this middleware - so nothing
here is process-global and a test can build its own.

**The route label is normalised, and the query string is dropped.** A metric labelled with a raw
path has one series per identifier a client invents; a query string is worse, because it carries
tokens and personal data into a monitoring system with its own retention and its own readers. What
is recorded is the method, the path with identifiers replaced, and the status class - the same
three things the access log records, for the same reasons.

**A request that raises is still observed.** The status is taken from the response when one was
sent, and recorded as a 500 when the application failed before sending anything: a middleware that
only counts clean responses under-reports exactly when an operator needs the number.
"""

from __future__ import annotations

import time
from typing import Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ahia.core.metrics import MetricsRegistry

#: What a request that never produced a response is recorded as. It is the status the error handler
#: would have sent, so the metric and the log agree.
_FAILED_STATUS_CODE: Final[int] = 500


class MetricsMiddleware:
    """Records request count, duration and status class per route."""

    def __init__(self, app: ASGIApp, *, registry: MetricsRegistry) -> None:
        self._app = app
        self._registry = registry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        started = time.perf_counter()
        status_code = _FAILED_STATUS_CODE

        async def observe(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self._app(scope, receive, observe)
        finally:
            # In a `finally` because a request that raised still consumed time and still failed:
            # a metric that only counts successes reports a healthy service during an outage.
            self._registry.observe_request(
                method=str(scope.get("method", "UNKNOWN")),
                path=str(scope.get("path", "/")),
                status_code=status_code,
                duration_seconds=time.perf_counter() - started,
            )
