"""Tests for the middleware stack.

Middleware is where cross-cutting behaviour either holds for every response or
quietly holds for most of them. Each test drives the middleware with a minimal
ASGI application and inspects the raw messages, so nothing about the assertions
depends on the framework's own behaviour.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from ahia.core.errors import (
    AhiaError,
    NotFoundError,
    RateLimitExceededError,
    generate_correlation_id,
    get_correlation_id,
    require_correlation_id,
)
from ahia.middleware.correlation_middleware import CorrelationIdMiddleware
from ahia.middleware.error_handler_middleware import ErrorHandlerMiddleware
from ahia.middleware.rate_limit_middleware import (
    RateLimitBucket,
    RateLimitMiddleware,
    RateLimitRule,
    SlidingWindowRateLimiter,
    build_default_limiter,
)
from ahia.middleware.security_headers_middleware import (
    DEFAULT_CONTENT_SECURITY_POLICY,
    SecurityHeadersMiddleware,
)


class RecordingSend:
    """Collect the ASGI messages a middleware sends."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def __call__(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    @property
    def start_message(self) -> dict[str, Any]:
        return next(
            message for message in self.messages if message["type"] == "http.response.start"
        )

    @property
    def headers(self) -> dict[str, str]:
        return {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in self.start_message["headers"]
        }

    @property
    def body(self) -> bytes:
        return next(
            (
                message["body"]
                for message in self.messages
                if message["type"] == "http.response.body"
            ),
            b"",
        )

    @property
    def status(self) -> int:
        return int(self.start_message["status"])


async def empty_receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}


def build_scope(
    *,
    path: str = "/api/v1/users/me",
    method: str = "GET",
    headers: list[tuple[bytes, bytes]] | None = None,
    client: tuple[str, int] | None = ("203.0.113.7", 54321),
) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers or [],
        "client": client,
        "server": ("testserver", 443),
    }


def ok_application(status: int = 200, body: bytes = b"{}") -> Any:
    async def application(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": body})

    return application


def failing_application(error: BaseException) -> Any:
    async def application(scope: Any, receive: Any, send: Any) -> None:
        raise error

    return application


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_correlation_id_is_generated_and_returned() -> None:
    middleware = CorrelationIdMiddleware(ok_application())
    send = RecordingSend()

    await middleware(build_scope(), empty_receive, send)

    correlation_id = send.headers["x-correlation-id"]
    assert correlation_id
    assert len(correlation_id) == 32


@pytest.mark.asyncio
@pytest.mark.unit
async def test_a_valid_inbound_correlation_id_is_preserved() -> None:
    middleware = CorrelationIdMiddleware(ok_application())
    send = RecordingSend()
    scope = build_scope(headers=[(b"x-correlation-id", b"trace-abcdef1234")])

    await middleware(scope, empty_receive, send)

    assert send.headers["x-correlation-id"] == "trace-abcdef1234"
    assert scope["state"]["correlation_id"] == "trace-abcdef1234"


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.parametrize(
    "inbound",
    [b"short", b"has spaces", b"newline\ninjected", b"A" * 200],
)
async def test_an_unusable_inbound_correlation_id_is_replaced(inbound: bytes) -> None:
    middleware = CorrelationIdMiddleware(ok_application())
    send = RecordingSend()
    scope = build_scope(headers=[(b"x-correlation-id", inbound)])

    await middleware(scope, empty_receive, send)

    returned = send.headers["x-correlation-id"]
    assert returned != inbound.decode("latin-1")
    assert len(returned) == 32


@pytest.mark.asyncio
@pytest.mark.unit
async def test_correlation_context_is_cleared_after_the_request() -> None:
    middleware = CorrelationIdMiddleware(ok_application())

    await middleware(build_scope(), empty_receive, RecordingSend())

    assert get_correlation_id() is None


@pytest.mark.asyncio
@pytest.mark.unit
async def test_access_log_records_route_and_never_the_query_string(
    caplog: pytest.LogCaptureFixture,
) -> None:
    middleware = CorrelationIdMiddleware(ok_application())
    scope = build_scope(path="/api/v1/sales", method="POST")
    scope["query_string"] = b"token=super-secret-token"

    with caplog.at_level(logging.INFO, logger="ahia.http.access"):
        await middleware(scope, empty_receive, RecordingSend())

    record = caplog.records[0]
    assert record.getMessage() == "http_request_completed"
    assert record.http_route == "/api/v1/sales"
    assert "super-secret-token" not in repr(record.__dict__)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_correlation_middleware_passes_websocket_scopes_through() -> None:
    reached: list[str] = []

    async def application(scope: Any, receive: Any, send: Any) -> None:
        reached.append(scope["type"])

    await CorrelationIdMiddleware(application)({"type": "lifespan"}, empty_receive, RecordingSend())

    assert reached == ["lifespan"]


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_security_headers_are_present_on_a_success_response() -> None:
    middleware = SecurityHeadersMiddleware(ok_application(), is_production=True)
    send = RecordingSend()

    await middleware(build_scope(), empty_receive, send)

    assert send.headers["x-content-type-options"] == "nosniff"
    assert send.headers["x-frame-options"] == "DENY"
    assert send.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in send.headers["content-security-policy"]
    assert "max-age=" in send.headers["strict-transport-security"]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_security_headers_are_present_on_an_error_response() -> None:
    """A header set only on success protects nothing."""
    error_middleware = ErrorHandlerMiddleware(failing_application(NotFoundError(operation="x")))
    middleware = SecurityHeadersMiddleware(error_middleware, is_production=True)
    send = RecordingSend()

    await middleware(build_scope(), empty_receive, send)

    assert send.status == 404
    assert send.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_hsts_is_not_sent_outside_production() -> None:
    """Pinning a developer's browser to https for a local host is a footgun."""
    middleware = SecurityHeadersMiddleware(ok_application(), is_production=False)
    send = RecordingSend()

    await middleware(build_scope(), empty_receive, send)

    assert "strict-transport-security" not in send.headers


@pytest.mark.asyncio
@pytest.mark.unit
async def test_security_headers_can_be_disabled_for_a_specific_deployment() -> None:
    middleware = SecurityHeadersMiddleware(ok_application(), enabled=False)
    send = RecordingSend()

    await middleware(build_scope(), empty_receive, send)

    assert "x-content-type-options" not in send.headers


@pytest.mark.asyncio
@pytest.mark.unit
async def test_content_security_policy_is_configurable() -> None:
    middleware = SecurityHeadersMiddleware(
        ok_application(), content_security_policy="default-src 'self'"
    )
    send = RecordingSend()

    await middleware(build_scope(), empty_receive, send)

    assert send.headers["content-security-policy"] == "default-src 'self'"


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.parametrize("path", ["/docs", "/docs/", "/redoc"])
async def test_the_interactive_documentation_gets_a_policy_that_can_render(path: str) -> None:
    """`default-src 'none'` on a page whose purpose is to run a CDN script renders it blank.

    The page still answered 200, so the failure looked like a broken API rather than a header doing
    its job. The documentation paths therefore allow the bundle's origin, and only those paths do.
    """
    middleware = SecurityHeadersMiddleware(ok_application())
    send = RecordingSend()

    await middleware(build_scope(path=path), empty_receive, send)

    policy = send.headers["content-security-policy"]
    assert "https://cdn.jsdelivr.net" in policy
    assert "default-src 'none'" in policy
    assert "frame-ancestors 'none'" in policy


@pytest.mark.asyncio
@pytest.mark.unit
async def test_every_other_path_keeps_the_strict_policy() -> None:
    """The exception is for the documentation, not for anything that happens to be nearby."""
    middleware = SecurityHeadersMiddleware(ok_application())
    send = RecordingSend()

    await middleware(build_scope(path="/api/v1/tenants"), empty_receive, send)

    assert send.headers["content-security-policy"] == DEFAULT_CONTENT_SECURITY_POLICY


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.unit
def test_limiter_allows_up_to_the_limit_then_refuses() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(
        rules={RateLimitBucket.GLOBAL: RateLimitRule(maximum_requests=3, window_seconds=60)},
        clock=clock,
    )

    decisions = [limiter.check("client", RateLimitBucket.GLOBAL) for _ in range(4)]

    assert [decision.allowed for decision in decisions] == [True, True, True, False]
    assert decisions[0].remaining == 2
    assert decisions[3].retry_after_seconds >= 1


@pytest.mark.unit
def test_window_slides_rather_than_resetting_on_a_boundary() -> None:
    """A fixed window would let a caller double the allowance across the edge."""
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(
        rules={RateLimitBucket.GLOBAL: RateLimitRule(maximum_requests=2, window_seconds=60)},
        clock=clock,
    )

    assert limiter.check("client", RateLimitBucket.GLOBAL).allowed is True
    clock.advance(59.0)
    assert limiter.check("client", RateLimitBucket.GLOBAL).allowed is True
    # At the boundary the first request is still inside the window.
    assert limiter.check("client", RateLimitBucket.GLOBAL).allowed is False

    clock.advance(2.0)
    assert limiter.check("client", RateLimitBucket.GLOBAL).allowed is True


@pytest.mark.unit
def test_limits_are_per_identity() -> None:
    limiter = build_default_limiter(
        authentication_per_minute=1,
        password_reset_per_hour=1,
        write_per_minute=1,
        global_per_minute=1,
        public_read_per_minute=1,
    )

    assert limiter.check("first", RateLimitBucket.GLOBAL).allowed is True
    assert limiter.check("first", RateLimitBucket.GLOBAL).allowed is False
    assert limiter.check("second", RateLimitBucket.GLOBAL).allowed is True


@pytest.mark.unit
def test_tracked_keys_are_bounded() -> None:
    """An attacker rotating addresses must not grow the table without limit."""
    limiter = SlidingWindowRateLimiter(
        rules={RateLimitBucket.GLOBAL: RateLimitRule(maximum_requests=5)},
        maximum_tracked_keys=10,
    )

    for index in range(50):
        limiter.check(f"client-{index}", RateLimitBucket.GLOBAL)

    assert limiter.tracked_key_count <= 11


@pytest.mark.asyncio
@pytest.mark.unit
async def test_authentication_paths_consume_the_authentication_limit() -> None:
    middleware = RateLimitMiddleware(
        ok_application(),
        limiter=build_default_limiter(
            authentication_per_minute=2,
            password_reset_per_hour=5,
            write_per_minute=100,
            public_read_per_minute=1_000,
            global_per_minute=100,
        ),
    )
    scope = build_scope(path="/api/v1/auth/login", method="POST")

    await middleware(scope, empty_receive, RecordingSend())
    await middleware(scope, empty_receive, RecordingSend())
    send = RecordingSend()
    await middleware(scope, empty_receive, send)

    assert send.status == 429


@pytest.mark.asyncio
@pytest.mark.unit
async def test_rate_limit_rejection_uses_the_standard_envelope() -> None:
    middleware = RateLimitMiddleware(
        ok_application(),
        limiter=build_default_limiter(
            authentication_per_minute=1,
            password_reset_per_hour=1,
            write_per_minute=1,
            public_read_per_minute=1_000,
            global_per_minute=1,
        ),
    )
    scope = build_scope(path="/api/v1/products", method="POST")

    await middleware(scope, empty_receive, RecordingSend())
    send = RecordingSend()
    await middleware(scope, empty_receive, send)

    payload = json.loads(send.body)

    assert send.status == 429
    assert set(payload["error"]) == {"code", "message", "correlation_id"}
    assert payload["error"]["code"] == "RATE_LIMITED"
    assert send.headers["retry-after"]
    assert send.headers["x-correlation-id"]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_reads_consume_the_global_limit_not_the_write_limit() -> None:
    middleware = RateLimitMiddleware(
        ok_application(),
        limiter=build_default_limiter(
            authentication_per_minute=1,
            password_reset_per_hour=1,
            write_per_minute=1,
            public_read_per_minute=1_000,
            global_per_minute=5,
        ),
    )
    scope = build_scope(path="/api/v1/products", method="GET")

    for _ in range(5):
        send = RecordingSend()
        await middleware(scope, empty_receive, send)
        assert send.status == 200


@pytest.mark.asyncio
@pytest.mark.unit
async def test_forwarded_header_is_trusted_only_up_to_the_configured_proxy_count() -> None:
    """A caller can set X-Forwarded-For, so believing it unconditionally is a bypass."""
    middleware = RateLimitMiddleware(
        ok_application(),
        limiter=build_default_limiter(
            authentication_per_minute=1,
            password_reset_per_hour=1,
            write_per_minute=1,
            public_read_per_minute=1_000,
            global_per_minute=1,
        ),
        trusted_proxy_count=1,
    )
    scope = build_scope(headers=[(b"x-forwarded-for", b"198.51.100.1, 203.0.113.9")])

    first = RecordingSend()
    await middleware(scope, empty_receive, first)
    second = RecordingSend()
    await middleware(scope, empty_receive, second)

    assert first.status == 200
    assert second.status == 429


@pytest.mark.asyncio
@pytest.mark.unit
async def test_without_a_trusted_proxy_the_socket_address_is_used() -> None:
    middleware = RateLimitMiddleware(
        ok_application(),
        limiter=build_default_limiter(
            authentication_per_minute=1,
            password_reset_per_hour=1,
            write_per_minute=1,
            public_read_per_minute=1_000,
            global_per_minute=1,
        ),
        trusted_proxy_count=0,
    )
    spoofed = build_scope(headers=[(b"x-forwarded-for", b"198.51.100.1")])

    first = RecordingSend()
    await middleware(spoofed, empty_receive, first)
    second = RecordingSend()
    await middleware(spoofed, empty_receive, second)

    assert second.status == 429, "the spoofed header must not create a new identity"


@pytest.mark.unit
def test_rule_rejects_an_impossible_configuration() -> None:
    with pytest.raises(ValueError):
        RateLimitRule(maximum_requests=0)
    with pytest.raises(ValueError):
        RateLimitRule(maximum_requests=1, window_seconds=0)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_typed_error_becomes_the_standard_envelope() -> None:
    middleware = ErrorHandlerMiddleware(
        failing_application(
            NotFoundError(
                operation="fetch_product",
                entity="product",
                identifier="8f3a",
                detail="no row matched",
            )
        )
    )
    send = RecordingSend()

    await middleware(build_scope(), empty_receive, send)

    payload = json.loads(send.body)

    assert send.status == 404
    assert payload["error"]["code"] == "NOT_FOUND"
    assert payload["error"]["correlation_id"]
    assert "no row matched" not in send.body.decode()
    assert "fetch_product" not in send.body.decode()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_typed_error_logs_the_internal_view(caplog: pytest.LogCaptureFixture) -> None:
    middleware = ErrorHandlerMiddleware(
        failing_application(
            NotFoundError(
                operation="fetch_product",
                entity="product",
                identifier="8f3a",
                detail="no row matched (tenant_id, product_id)",
            )
        )
    )

    with caplog.at_level(logging.WARNING, logger="ahia.http.errors"):
        await middleware(build_scope(), empty_receive, RecordingSend())

    record = caplog.records[0]
    assert record.getMessage() == "request_failed"
    assert record.error_operation == "fetch_product"
    assert record.error_entity == "product"
    assert record.error_identifier == "8f3a"
    assert record.error_layer == "persistence"
    assert "no row matched" in record.error_detail


@pytest.mark.asyncio
@pytest.mark.unit
async def test_unexpected_error_is_opaque_and_uniform() -> None:
    middleware = ErrorHandlerMiddleware(
        failing_application(RuntimeError("connection to db.internal:5432 refused"))
    )
    send = RecordingSend()

    await middleware(build_scope(), empty_receive, send)

    payload = json.loads(send.body)
    rendered = send.body.decode()

    assert send.status == 500
    assert payload["error"]["code"] == "INTERNAL_ERROR"
    assert "db.internal" not in rendered
    assert "RuntimeError" not in rendered
    assert "Traceback" not in rendered


@pytest.mark.asyncio
@pytest.mark.unit
async def test_unexpected_error_is_logged_with_its_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    middleware = ErrorHandlerMiddleware(failing_application(ValueError("bad internal state")))

    with caplog.at_level(logging.ERROR, logger="ahia.http.errors"):
        await middleware(build_scope(), empty_receive, RecordingSend())

    record = caplog.records[0]
    assert record.getMessage() == "request_failed_unexpectedly"
    assert record.error_type == "ValueError"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_two_failures_do_not_share_a_correlation_id() -> None:
    """The real stack order: correlation in front, error handling behind it."""
    middleware = CorrelationIdMiddleware(
        ErrorHandlerMiddleware(failing_application(RuntimeError("boom")))
    )

    first = RecordingSend()
    await middleware(build_scope(), empty_receive, first)
    second = RecordingSend()
    await middleware(build_scope(), empty_receive, second)

    first_id = json.loads(first.body)["error"]["correlation_id"]
    second_id = json.loads(second.body)["error"]["correlation_id"]

    assert first_id != second_id
    assert first_id == first.headers["x-correlation-id"]
    assert second_id == second.headers["x-correlation-id"]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_successful_response_is_untouched() -> None:
    middleware = ErrorHandlerMiddleware(ok_application(status=201, body=b'{"id": "8f3a"}'))
    send = RecordingSend()

    await middleware(build_scope(), empty_receive, send)

    assert send.status == 201
    assert send.body == b'{"id": "8f3a"}'


@pytest.mark.asyncio
@pytest.mark.unit
async def test_rate_limit_error_is_mapped_by_the_error_handler_too() -> None:
    """A typed error raised anywhere in the stack reaches the same envelope."""
    middleware = ErrorHandlerMiddleware(
        failing_application(RateLimitExceededError(operation="rate_limit", detail="bucket=global"))
    )
    send = RecordingSend()

    await middleware(build_scope(), empty_receive, send)

    assert send.status == 429
    assert json.loads(send.body)["error"]["code"] == "RATE_LIMITED"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_error_envelope_always_carries_a_correlation_id() -> None:
    middleware = ErrorHandlerMiddleware(failing_application(AhiaError(operation="anything")))
    send = RecordingSend()

    await middleware(build_scope(), empty_receive, send)

    payload = json.loads(send.body)

    assert payload["error"]["correlation_id"] == send.headers["x-correlation-id"]
    assert payload["error"]["correlation_id"] == require_correlation_id_in_scope()


def require_correlation_id_in_scope() -> str:
    """Return the correlation ID bound by the error handler.

    The error handler binds one when none is present, so this is never empty.
    """
    return require_correlation_id()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_generated_correlation_ids_are_unique_across_requests() -> None:
    identifiers = {generate_correlation_id() for _ in range(100)}

    assert len(identifiers) == 100


@pytest.mark.unit
def test_the_public_shop_carries_its_own_limit() -> None:
    """The one surface an anonymous caller reaches does not share the global budget.

    A shop page is cheap to serve and easy to scrape, and the limit on it is a security control:
    it is not behind a feature flag and it fails closed to the conservative global rule when the
    caller cannot be identified.
    """
    limiter = build_default_limiter(
        authentication_per_minute=1_000,
        password_reset_per_hour=1_000,
        write_per_minute=1_000,
        global_per_minute=1_000,
        public_read_per_minute=2,
    )

    assert limiter.check("shopper", RateLimitBucket.PUBLIC_READ).allowed is True
    assert limiter.check("shopper", RateLimitBucket.PUBLIC_READ).allowed is True
    assert limiter.check("shopper", RateLimitBucket.PUBLIC_READ).allowed is False
    assert limiter.check("shopper", RateLimitBucket.GLOBAL).allowed is True, (
        "the shop's budget is separate from the global one"
    )


@pytest.mark.unit
def test_the_public_routes_are_classified_into_the_public_bucket() -> None:
    """A path that reaches the shop without consuming the shop's budget is not limited at all."""
    assert (
        RateLimitMiddleware._bucket_for(path="/shop/obi-electronics", method="GET")
        is RateLimitBucket.PUBLIC_READ
    )
    assert (
        RateLimitMiddleware._bucket_for(path="/share/invoice/abc", method="GET")
        is RateLimitBucket.PUBLIC_READ
    )
    assert (
        RateLimitMiddleware._bucket_for(path="/api/v1/tenants/x/products", method="GET")
        is RateLimitBucket.GLOBAL
    )
