"""Error handling middleware.

The single place an exception becomes an HTTP response, and therefore the single
place that decides what a client learns.

Two views of every failure:
- the client receives an error code, a safe message and the correlation ID
- the log receives the operation, the layer, the entity, the identifier, the
  correlation ID and the chained cause

An unhandled exception produces one uniform envelope. Giving each internal
failure its own code would let a client map the internals of the service from
the outside, which is the reason the codes are coarse.

The unexpected-exception path deliberately does not re-raise: the response has
already been decided, and letting the exception escape would produce a second
response attempt and a framework stack trace in the client's output.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ahia.core.errors import (
    AhiaError,
    AuthorizationError,
    ErrorLayer,
    internal_error_envelope,
    require_correlation_id,
)
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.metrics import MetricsRegistry

_ERROR_LOGGER_NAME: Final[str] = "ahia.http.errors"


class ErrorHandlerMiddleware:
    """Map typed errors to the external envelope, and log the internal view."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        logger: StructuredLogger | None = None,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self.app = app
        self.logger = (logger or get_logger(_ERROR_LOGGER_NAME)).bind(component="error_handler")
        # Optional, so a test can build the middleware without a registry. When one is given, every
        # failure is counted by the code a client was told and every refusal separately: "the error
        # rate went up" and "people are being refused" are different questions.
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_tracking_start(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_tracking_start)
        except AhiaError as error:
            await self._handle_typed_error(
                scope, send, error=error, response_started=response_started
            )
        except Exception as error:  # noqa: BLE001 - the last line of defence
            await self._handle_unexpected_error(
                scope, send, error=error, response_started=response_started
            )

    async def _handle_typed_error(
        self,
        scope: Scope,
        send: Send,
        *,
        error: AhiaError,
        response_started: bool,
    ) -> None:
        external = error.external()
        self.logger.warning(
            "request_failed",
            http_method=scope.get("method"),
            http_route=scope.get("path"),
            http_status=error.http_status,
            error_code=error.error_code,
            error_layer=error.context.layer.value,
            error_operation=error.context.operation,
            error_entity=error.context.entity,
            error_identifier=error.context.identifier,
            error_detail=error.context.describe(),
            error_causes=list(error.context.causes),
        )
        if self.metrics is not None:
            self.metrics.record_error(error_code=error.error_code)
            if isinstance(error, AuthorizationError):
                # Keyed by the use case that refused, which is what an operator acts on:
                # "records are being refused" names nothing, and "cancel_sale is being
                # refused" names a role.
                self.metrics.record_authorization_denial(action=error.context.operation)
        if response_started:  # pragma: no cover - defensive, response already sent
            return
        await send_json_response(send, status_code=error.http_status, payload=external.to_payload())

    async def _handle_unexpected_error(
        self,
        scope: Scope,
        send: Send,
        *,
        error: Exception,
        response_started: bool,
    ) -> None:
        # PLE1205 pattern-matches the stdlib logging signature; this is our own
        # structured wrapper, which takes keyword fields rather than a format string.
        self.logger.exception(  # noqa: PLE1205
            "request_failed_unexpectedly",
            error,
            http_method=scope.get("method"),
            http_route=scope.get("path"),
            error_type=type(error).__name__,
            error_layer=ErrorLayer.TRANSPORT.value,
        )
        if response_started:  # pragma: no cover - defensive, response already sent
            return
        envelope = internal_error_envelope()
        await send_json_response(send, status_code=500, payload=envelope.to_payload())


async def send_json_response(
    send: Send,
    *,
    status_code: int,
    payload: Mapping[str, Any],
    extra_headers: dict[str, str] | None = None,
) -> None:
    """Send a JSON response directly on the ASGI channel.

    Built by hand rather than through a framework response object so the error
    path has no dependency on routing, middleware, request parsing or a scope
    that may already be in a broken state: the whole point is that it works when
    something else did not.

    Used by both the error handler and the rate limiter, so there is exactly one
    implementation of the external envelope on the wire.
    """
    body = json.dumps(payload).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    correlation_id = require_correlation_id()
    start_message: Message = {
        "type": "http.response.start",
        "status": status_code,
        "headers": headers,
    }
    response_headers = MutableHeaders(scope=start_message)
    response_headers["X-Correlation-ID"] = correlation_id
    for header_name, header_value in (extra_headers or {}).items():
        response_headers[header_name] = header_value
    await send(start_message)
    await send({"type": "http.response.body", "body": body})
