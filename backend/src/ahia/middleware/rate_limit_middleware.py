"""Rate limiting middleware.

Rate limiting protects the endpoints where abuse is cheapest for the attacker and
most expensive for the product: authentication, password reset, anything that
sends a message, and anything that costs money.

This is a security control. It is never behind a feature flag, and it fails
closed: if the limiter cannot identify a caller, the caller gets the conservative
global limit rather than no limit.

Scope of the current implementation, stated plainly: the counters live in this
process. A deployment with several API instances therefore enforces the limit per
instance, which is weaker than a shared counter. That is an accepted, documented
limitation for a single-instance deployment; a shared store is the change that
removes it, and nothing else in this module has to move for that to happen.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send

from ahia.core.errors import RateLimitExceededError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.middleware.error_handler_middleware import send_json_response

_RATE_LIMIT_LOGGER_NAME: Final[str] = "ahia.http.rate_limit"


class RateLimitBucket(StrEnum):
    """The endpoint classes that carry their own limit."""

    AUTHENTICATION = "authentication"
    # The name contains "PASSWORD" and the scanner flags it; the value is a
    # bucket label, not a credential.
    PASSWORD_RESET = "password_reset"  # noqa: S105
    WRITE = "write"
    GLOBAL = "global"


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    """One limit: how many requests, over how many seconds."""

    maximum_requests: int
    window_seconds: int = 60

    def __post_init__(self) -> None:
        if self.maximum_requests < 1:
            raise ValueError("maximum_requests must be at least 1")
        if self.window_seconds < 1:
            raise ValueError("window_seconds must be at least 1")


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """The outcome of one check."""

    allowed: bool
    bucket: RateLimitBucket
    remaining: int
    retry_after_seconds: int


@dataclass(slots=True)
class _SlidingWindow:
    """A per-key sliding window of request timestamps."""

    window_seconds: int
    timestamps: deque[float] = field(default_factory=deque)

    def admit(self, now: float, maximum_requests: int) -> tuple[bool, int]:
        cutoff = now - self.window_seconds
        while self.timestamps and self.timestamps[0] <= cutoff:
            self.timestamps.popleft()
        if len(self.timestamps) >= maximum_requests:
            retry_after = max(1, int(self.timestamps[0] + self.window_seconds - now) + 1)
            return False, retry_after
        self.timestamps.append(now)
        return True, 0


class SlidingWindowRateLimiter:
    """An in-process sliding-window limiter with one window set per key.

    A sliding window rather than a fixed one: a fixed window lets a caller send
    the full allowance at the end of one window and again at the start of the
    next, which is exactly the burst the limit exists to stop.
    """

    def __init__(
        self,
        *,
        rules: dict[RateLimitBucket, RateLimitRule],
        maximum_tracked_keys: int = 50_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rules = rules
        self._maximum_tracked_keys = maximum_tracked_keys
        self._clock = clock
        self._windows: dict[tuple[str, RateLimitBucket], _SlidingWindow] = {}

    @property
    def tracked_key_count(self) -> int:
        """Return how many identity-and-bucket windows are being tracked."""
        return len(self._windows)

    def check(self, identity: str, bucket: RateLimitBucket) -> RateLimitDecision:
        """Record one request and decide whether it is allowed."""
        rule = self._rules.get(bucket) or self._rules[RateLimitBucket.GLOBAL]
        now = float(self._clock())

        if len(self._windows) > self._maximum_tracked_keys:
            # Bounded memory: an attacker rotating source addresses must not be
            # able to grow this dictionary without limit.
            self._windows.clear()

        key = (identity, bucket)
        window = self._windows.get(key)
        if window is None:
            window = _SlidingWindow(window_seconds=rule.window_seconds)
            self._windows[key] = window

        allowed, retry_after = window.admit(now, rule.maximum_requests)
        remaining = max(0, rule.maximum_requests - len(window.timestamps))
        return RateLimitDecision(
            allowed=allowed,
            bucket=bucket,
            remaining=remaining,
            retry_after_seconds=retry_after,
        )


#: Paths that carry the authentication limit. Kept as a tuple of fragments
#: rather than a regex so the routing intent is readable at a glance.
_AUTHENTICATION_PATH_FRAGMENTS: Final[tuple[str, ...]] = (
    "/auth/login",
    "/auth/register",
    "/auth/refresh",
    "/auth/token",
)

_PASSWORD_RESET_PATH_FRAGMENTS: Final[tuple[str, ...]] = (
    "/auth/password-reset",
    "/auth/forgot-password",
)

_WRITE_METHODS: Final[frozenset[str]] = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class RateLimitMiddleware:
    """Apply the configured limits before the request reaches a route."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: SlidingWindowRateLimiter,
        trusted_proxy_count: int = 0,
        logger: StructuredLogger | None = None,
    ) -> None:
        self.app = app
        self.limiter = limiter
        self.trusted_proxy_count = trusted_proxy_count
        self.logger = (logger or get_logger(_RATE_LIMIT_LOGGER_NAME)).bind(component="rate_limit")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        method = str(scope.get("method", "GET"))
        bucket = self._bucket_for(path=path, method=method)
        identity = self._identity_for(scope)

        decision = self.limiter.check(identity, bucket)
        if not decision.allowed:
            self.logger.warning(
                "rate_limit_exceeded",
                bucket=decision.bucket.value,
                http_route=path,
                http_method=method,
                # The identity is a client address, which is operational data
                # rather than personal data, and it is what an operator needs to
                # act on a burst.
                client_identity=identity,
                retry_after_seconds=decision.retry_after_seconds,
            )
            error = RateLimitExceededError(
                operation="rate_limit",
                entity="request",
                detail=(
                    f"bucket={decision.bucket.value} identity={identity} "
                    f"retry_after_seconds={decision.retry_after_seconds}"
                ),
            )
            await self._send_rejection(send, error=error, retry_after=decision.retry_after_seconds)
            return

        await self.app(scope, receive, send)

    @staticmethod
    def _bucket_for(*, path: str, method: str) -> RateLimitBucket:
        """Classify a request by the limit it should consume."""
        if any(fragment in path for fragment in _PASSWORD_RESET_PATH_FRAGMENTS):
            return RateLimitBucket.PASSWORD_RESET
        if any(fragment in path for fragment in _AUTHENTICATION_PATH_FRAGMENTS):
            return RateLimitBucket.AUTHENTICATION
        if method in _WRITE_METHODS:
            return RateLimitBucket.WRITE
        return RateLimitBucket.GLOBAL

    def _identity_for(self, scope: Scope) -> str:
        """Return the client identity a limit is counted against.

        A forwarded header is trusted only up to the configured number of
        proxies, because a caller can set `X-Forwarded-For` themselves. Believing
        it unconditionally would let one client present unlimited identities and
        bypass every limit here.
        """
        if self.trusted_proxy_count > 0:
            forwarded = Headers(scope=scope).get("x-forwarded-for")
            if forwarded:
                addresses = [address.strip() for address in forwarded.split(",") if address.strip()]
                if addresses:
                    index = max(0, len(addresses) - self.trusted_proxy_count)
                    return addresses[index]

        client = scope.get("client")
        if isinstance(client, (list, tuple)) and client:
            return str(client[0])
        return "unknown-client"

    async def _send_rejection(
        self,
        send: Send,
        *,
        error: RateLimitExceededError,
        retry_after: int,
    ) -> None:
        """Reject with the same envelope every other error uses.

        Sent through the shared envelope writer rather than a framework response
        object, so a rate-limited request and a failed request are byte-identical
        in shape and neither depends on routing having succeeded.
        """
        await send_json_response(
            send,
            status_code=error.http_status,
            payload=error.external().to_payload(),
            extra_headers={"Retry-After": str(retry_after)},
        )


def build_default_limiter(
    *,
    authentication_per_minute: int,
    password_reset_per_hour: int,
    write_per_minute: int,
    global_per_minute: int,
    clock: Callable[[], float] = time.monotonic,
) -> SlidingWindowRateLimiter:
    """Build the limiter from configuration.

    Every limit is configuration rather than a constant, because a limit that
    cannot be changed without a deploy will be changed by an emergency hotfix.
    """
    return SlidingWindowRateLimiter(
        rules={
            RateLimitBucket.AUTHENTICATION: RateLimitRule(
                maximum_requests=authentication_per_minute, window_seconds=60
            ),
            RateLimitBucket.PASSWORD_RESET: RateLimitRule(
                maximum_requests=password_reset_per_hour, window_seconds=3_600
            ),
            RateLimitBucket.WRITE: RateLimitRule(
                maximum_requests=write_per_minute, window_seconds=60
            ),
            RateLimitBucket.GLOBAL: RateLimitRule(
                maximum_requests=global_per_minute, window_seconds=60
            ),
        },
        clock=clock,
    )


def apply_retry_after_header(message_headers: MutableHeaders, seconds: int) -> None:
    """Set the Retry-After header on a response.

    Kept as a function so the header name and formatting appear once.
    """
    message_headers["Retry-After"] = str(seconds)
