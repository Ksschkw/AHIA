"""Resilience primitives for outbound boundaries.

Applied at every outbound call and only at outbound calls: third-party APIs,
object storage, LLM providers, payment gateways, messaging and caches. A service
calling its own repository is not a failure domain, and wrapping it in a breaker
adds latency while hiding bugs behind "circuit open".

Every outbound dependency gets:

* an explicit, non-infinite timeout
* one circuit breaker per dependency, not per call site
* a bulkhead concurrency limit so one slow dependency cannot exhaust the process
* bounded retry with exponential backoff and jitter, for idempotent operations
  only
* an explicit typed fallback, never a silent ``None``
* structured logs and counters on state change and fallback activation

The primitives are constructed in the composition root and injected. Nothing
here is a module-level singleton, and nothing here is imported by an entity,
schema or router.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from types import TracebackType
from typing import Any, Final, Protocol, TypeVar

from ahia.core.errors import (
    DependencyBusyError,
    DependencyCircuitOpenError,
    DependencyTimeoutError,
    IntegrationError,
)
from ahia.core.logging import StructuredLogger, get_logger

T = TypeVar("T")


DEFAULT_RETRYABLE_ERRORS: Final[tuple[type[BaseException], ...]] = (IntegrationError,)

_RESILIENCE_LOGGER_NAME: Final[str] = "ahia.core.resilience"


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class CircuitState(StrEnum):
    """Breaker states.

    CLOSED passes calls through. OPEN fails them immediately. HALF_OPEN admits a
    bounded number of probes to find out whether the dependency recovered.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(slots=True)
class CircuitBreakerMetrics:
    """Counters emitted alongside the structured logs."""

    successes: int = 0
    failures: int = 0
    short_circuited_calls: int = 0
    state_transitions: int = 0

    def as_log_fields(self) -> dict[str, int]:
        return {
            "successes": self.successes,
            "failures": self.failures,
            "short_circuited_calls": self.short_circuited_calls,
            "state_transitions": self.state_transitions,
        }


@dataclass(frozen=True, slots=True)
class CircuitBreakerConfiguration:
    """Thresholds for one dependency's breaker."""

    failure_threshold: int = 5
    reset_timeout_seconds: float = 60.0
    half_open_probe_count: int = 1

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if self.reset_timeout_seconds <= 0:
            raise ValueError("reset_timeout_seconds must be positive")
        if self.half_open_probe_count < 1:
            raise ValueError("half_open_probe_count must be at least 1")


class CircuitBreaker:
    """One breaker for one dependency.

    Time is injected so a test can drive the reset window without sleeping, and
    the state is derived from the clock rather than from a background timer, so
    there is no task to leak and no window in which the state is stale.
    """

    def __init__(
        self,
        dependency_name: str,
        configuration: CircuitBreakerConfiguration,
        *,
        clock: Callable[[], float] = time.monotonic,
        logger: StructuredLogger | None = None,
    ) -> None:
        self.dependency_name = dependency_name
        self._configuration = configuration
        self._clock = clock
        self._logger = (logger or get_logger(_RESILIENCE_LOGGER_NAME)).bind(
            dependency=dependency_name,
            component="circuit_breaker",
        )
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._half_open_probes_in_flight = 0
        self.metrics = CircuitBreakerMetrics()

    @property
    def configuration(self) -> CircuitBreakerConfiguration:
        return self._configuration

    @property
    def state(self) -> CircuitState:
        """Return the current state, promoting OPEN to HALF_OPEN when due.

        The promotion happens on read so that a dependency which is never called
        again costs nothing to keep healthy.
        """
        if (
            self._state is CircuitState.OPEN
            and self._opened_at is not None
            and self._clock() - self._opened_at >= self._configuration.reset_timeout_seconds
        ):
            self._transition_to(CircuitState.HALF_OPEN, reason="reset_window_elapsed")
        return self._state

    def before_call(self) -> None:
        """Admit a call or fail fast with a typed error.

        Failing fast is the point: the dependency is already known to be
        unhealthy, and piling requests onto it makes recovery slower.
        """
        current_state = self.state

        if current_state is CircuitState.OPEN:
            self.metrics.short_circuited_calls += 1
            self._logger.warning(
                "circuit_breaker_rejected_call",
                state=current_state.value,
                short_circuited_calls=self.metrics.short_circuited_calls,
            )
            raise DependencyCircuitOpenError(
                operation="outbound_call",
                detail=(
                    f"dependency={self.dependency_name} breaker_state=open "
                    f"consecutive_failures={self._consecutive_failures}"
                ),
            )

        if current_state is CircuitState.HALF_OPEN:
            # Only a bounded number of probes are admitted while half-open.
            if self._half_open_probes_in_flight >= self._configuration.half_open_probe_count:
                self.metrics.short_circuited_calls += 1
                raise DependencyCircuitOpenError(
                    operation="outbound_call",
                    detail=(
                        f"dependency={self.dependency_name} breaker_state=half_open "
                        f"probes_in_flight={self._half_open_probes_in_flight}"
                    ),
                )
            self._half_open_probes_in_flight += 1

    def record_success(self) -> None:
        """Record a successful call, closing the breaker."""
        self.metrics.successes += 1
        self._consecutive_failures = 0
        if self._state is CircuitState.HALF_OPEN:
            self._half_open_probes_in_flight = max(0, self._half_open_probes_in_flight - 1)
            self._opened_at = None
            self._transition_to(CircuitState.CLOSED, reason="probe_succeeded")

    def record_failure(self) -> None:
        """Record a failed call, opening the breaker at the threshold."""
        self.metrics.failures += 1
        self._consecutive_failures += 1

        if self._state is CircuitState.HALF_OPEN:
            self._half_open_probes_in_flight = max(0, self._half_open_probes_in_flight - 1)
            self._open(reason="probe_failed")
            return

        if self._consecutive_failures >= self._configuration.failure_threshold:
            self._open(reason="failure_threshold_reached")

    def _open(self, *, reason: str) -> None:
        self._opened_at = self._clock()
        self._transition_to(CircuitState.OPEN, reason=reason)

    def _transition_to(self, new_state: CircuitState, *, reason: str) -> None:
        if new_state is self._state:
            return
        previous_state = self._state
        self._state = new_state
        self.metrics.state_transitions += 1
        if new_state is CircuitState.CLOSED:
            self._consecutive_failures = 0
        self._logger.warning(
            "circuit_breaker_state_changed",
            previous_state=previous_state.value,
            state=new_state.value,
            reason=reason,
            consecutive_failures=self._consecutive_failures,
            **self.metrics.as_log_fields(),
        )


# ---------------------------------------------------------------------------
# Bulkhead
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class BulkheadMetrics:
    """Concurrency counters for one dependency."""

    admitted: int = 0
    rejected: int = 0
    peak_concurrency: int = 0

    def as_log_fields(self) -> dict[str, int]:
        return {
            "admitted": self.admitted,
            "rejected": self.rejected,
            "peak_concurrency": self.peak_concurrency,
        }


class Bulkhead:
    """A per-dependency concurrency limit.

    Used as an async context manager:

        async with bulkhead:
            ...
    """

    def __init__(
        self,
        dependency_name: str,
        *,
        max_concurrent_calls: int,
        max_wait_seconds: float = 0.0,
        logger: StructuredLogger | None = None,
    ) -> None:
        if max_concurrent_calls < 1:
            raise ValueError("max_concurrent_calls must be at least 1")
        if max_wait_seconds < 0:
            raise ValueError("max_wait_seconds may not be negative")
        self.dependency_name = dependency_name
        self.max_concurrent_calls = max_concurrent_calls
        self.max_wait_seconds = max_wait_seconds
        self._semaphore = asyncio.Semaphore(max_concurrent_calls)
        self._in_flight = 0
        self._logger = (logger or get_logger(_RESILIENCE_LOGGER_NAME)).bind(
            dependency=dependency_name,
            component="bulkhead",
        )
        self.metrics = BulkheadMetrics()

    @property
    def in_flight(self) -> int:
        return self._in_flight

    async def __aenter__(self) -> Bulkhead:
        try:
            if self.max_wait_seconds > 0:
                await asyncio.wait_for(self._semaphore.acquire(), timeout=self.max_wait_seconds)
            else:
                # A zero wait means "do not queue": a full bulkhead refuses the
                # call rather than making the caller wait behind a slow
                # dependency.
                if self._semaphore.locked():
                    raise TimeoutError
                await self._semaphore.acquire()
        except TimeoutError as timeout_error:
            self.metrics.rejected += 1
            self._logger.warning(
                "bulkhead_rejected_call",
                in_flight=self._in_flight,
                max_concurrent_calls=self.max_concurrent_calls,
                **self.metrics.as_log_fields(),
            )
            raise DependencyBusyError(
                operation="outbound_call",
                detail=(
                    f"dependency={self.dependency_name} in_flight={self._in_flight} "
                    f"limit={self.max_concurrent_calls}"
                ),
                cause=timeout_error,
            ) from timeout_error

        self._in_flight += 1
        self.metrics.admitted += 1
        self.metrics.peak_concurrency = max(self.metrics.peak_concurrency, self._in_flight)
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._in_flight = max(0, self._in_flight - 1)
        self._semaphore.release()


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded retry with exponential backoff and full jitter.

    Jitter is not decoration. Without it, a dependency that recovers after an
    outage is immediately hit by every client retrying in lockstep.
    """

    max_attempts: int = 3
    base_delay_seconds: float = 0.2
    max_delay_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay_seconds <= 0:
            raise ValueError("base_delay_seconds must be positive")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds may not be below base_delay_seconds")

    def delay_for_attempt(
        self, attempt_index: int, *, random_source: random.Random | None = None
    ) -> float:
        """Return the sleep before retry number ``attempt_index`` (1-based).

        Full jitter: a uniform draw between zero and the exponential ceiling.
        """
        exponential_ceiling = min(
            self.max_delay_seconds, self.base_delay_seconds * (2 ** (attempt_index - 1))
        )
        source = random_source or random
        return source.uniform(0.0, exponential_ceiling)


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------


class DegradedResult(Protocol):
    """Anything a fallback returns must identify itself as degraded.

    Enforced by convention here and by the concrete result types: a fallback
    returns a value which carries ``is_degraded = True`` and a reason, never
    ``None`` and never a fabricated success.
    """

    is_degraded: bool
    degradation_reason: str


#: A typed degradation path for one operation. It receives the failure and
#: returns a degraded value of the same type the successful call would return,
#: so the caller cannot silently receive ``None`` or a fabricated success.
#: A typed degradation path for one operation. It receives the failure and
#: returns a degraded value of the same type a successful call would return,
#: so a caller cannot silently receive None or a fabricated success.
type FallbackProvider[T] = Callable[[BaseException], Awaitable[T]]


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ResilienceMetrics:
    """Aggregate counters for one dependency's policy."""

    calls: int = 0
    successes: int = 0
    failures: int = 0
    timeouts: int = 0
    retries: int = 0
    fallbacks_activated: int = 0

    def as_log_fields(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "successes": self.successes,
            "failures": self.failures,
            "timeouts": self.timeouts,
            "retries": self.retries,
            "fallbacks_activated": self.fallbacks_activated,
        }


@dataclass(slots=True)
class ResiliencePolicy:
    """Timeout, breaker, bulkhead, retry and fallback for one outbound dependency.

    One policy instance exists per dependency, constructed in the composition
    root. It is not a singleton and it is not shared across unrelated
    dependencies, because a shared breaker would let one unhealthy provider trip
    calls to a healthy one.
    """

    dependency_name: str
    timeout_seconds: float
    breaker: CircuitBreaker
    bulkhead: Bulkhead
    retry: RetryPolicy | None = None
    logger: StructuredLogger = field(default_factory=lambda: get_logger(_RESILIENCE_LOGGER_NAME))
    metrics: ResilienceMetrics = field(default_factory=ResilienceMetrics)
    _sleep: Callable[[float], Awaitable[None]] = field(default=asyncio.sleep, repr=False)

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive; an unbounded call is a bug")

    def describe(self) -> dict[str, Any]:
        """Return the policy shape for startup logging."""
        return {
            "dependency": self.dependency_name,
            "timeout_seconds": self.timeout_seconds,
            "bulkhead_limit": self.bulkhead.max_concurrent_calls,
            "retry_attempts": self.retry.max_attempts if self.retry else 1,
            "breaker_failure_threshold": self.breaker.configuration.failure_threshold,
            "breaker_reset_seconds": self.breaker.configuration.reset_timeout_seconds,
        }

    async def execute(
        self,
        call: Callable[[], Awaitable[T]],
        *,
        operation: str,
        is_idempotent: bool = True,
        retryable_errors: tuple[type[BaseException], ...] = DEFAULT_RETRYABLE_ERRORS,
        fallback: FallbackProvider[T] | None = None,
    ) -> T:
        """Run an outbound call under the full policy.

        ``is_idempotent`` defaults to True because most reads are, but a caller
        performing a mutating operation must pass False, which disables retry.
        Retrying a non-idempotent write is how a duplicate is created.
        """
        logger = self.logger.bind(dependency=self.dependency_name, operation=operation)
        self.metrics.calls += 1

        async with self.bulkhead:
            attempts = self.retry.max_attempts if (self.retry and is_idempotent) else 1

            for attempt in range(1, attempts + 1):
                self.breaker.before_call()
                try:
                    async with asyncio.timeout(self.timeout_seconds):
                        result = await call()
                except TimeoutError as timeout_error:
                    self.metrics.timeouts += 1
                    self.breaker.record_failure()
                    error: BaseException = DependencyTimeoutError(
                        operation=operation,
                        detail=f"dependency={self.dependency_name} "
                        f"timeout_seconds={self.timeout_seconds}",
                        cause=timeout_error,
                    )
                except Exception as call_error:  # noqa: BLE001 - translated below
                    self.breaker.record_failure()
                    error = self._translate(call_error, operation=operation)
                else:
                    self.breaker.record_success()
                    self.metrics.successes += 1
                    return result

                self.metrics.failures += 1
                should_retry = (
                    self.retry is not None
                    and is_idempotent
                    and attempt < attempts
                    and isinstance(error, retryable_errors)
                )
                if should_retry:
                    self.metrics.retries += 1
                    delay = self.retry.delay_for_attempt(attempt)  # type: ignore[union-attr]
                    logger.warning(
                        "outbound_call_retrying",
                        attempt=attempt,
                        max_attempts=attempts,
                        delay_seconds=round(delay, 3),
                        error_type=type(error).__name__,
                    )
                    await self._sleep(delay)
                    continue

                if fallback is not None:
                    self.metrics.fallbacks_activated += 1
                    logger.error(
                        "outbound_call_degraded",
                        attempt=attempt,
                        error_type=type(error).__name__,
                        **self.metrics.as_log_fields(),
                    )
                    degraded = await fallback(error)
                    if degraded is None:
                        # A fallback that returns None turns a visible failure
                        # into an invisible one. Fail loudly instead.
                        raise IntegrationError(
                            operation=operation,
                            detail=(
                                f"dependency={self.dependency_name} "
                                "fallback returned None instead of a typed degraded result"
                            ),
                        ) from error
                    return degraded

                logger.error(
                    "outbound_call_failed",
                    attempt=attempt,
                    error_type=type(error).__name__,
                    **self.metrics.as_log_fields(),
                )
                raise error

        # The loop always returns or raises; this is unreachable but keeps the
        # type checker honest without an assert.
        raise IntegrationError(  # pragma: no cover
            operation=operation,
            detail=f"dependency={self.dependency_name} policy exited without a result",
        )

    def _translate(self, error: BaseException, *, operation: str) -> BaseException:
        """Translate a provider exception into the application hierarchy.

        A provider exception type must never cross this boundary: it names the
        vendor, it may carry a signed URL, and it gives the transport layer
        nothing it can map.
        """
        if isinstance(error, IntegrationError):
            return error
        if isinstance(error, asyncio.CancelledError):
            raise error
        return IntegrationError(
            operation=operation,
            detail=f"dependency={self.dependency_name} provider_error={type(error).__name__}",
            cause=error,
        )


def build_policy(
    dependency_name: str,
    *,
    timeout_seconds: float,
    breaker_configuration: CircuitBreakerConfiguration,
    max_concurrent_calls: int,
    max_wait_seconds: float = 0.0,
    retry: RetryPolicy | None = None,
    logger: StructuredLogger | None = None,
) -> ResiliencePolicy:
    """Construct a policy for one dependency.

    Called from the composition root. Kept as a function rather than a class so
    the wiring of the three primitives stays visible in one place.
    """
    return ResiliencePolicy(
        dependency_name=dependency_name,
        timeout_seconds=timeout_seconds,
        breaker=CircuitBreaker(dependency_name, breaker_configuration, logger=logger),
        bulkhead=Bulkhead(
            dependency_name,
            max_concurrent_calls=max_concurrent_calls,
            max_wait_seconds=max_wait_seconds,
            logger=logger,
        ),
        retry=retry,
        logger=logger or get_logger(_RESILIENCE_LOGGER_NAME),
    )
