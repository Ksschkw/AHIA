"""Tests for the outbound resilience primitives.

The primitives protect the process from a slow or broken dependency, so the
tests exercise the failure paths: a breaker that must trip, a bulkhead that must
refuse, a retry that must stay bounded and jittered, and a fallback that must be
typed.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import pytest

from ahia.core.errors import (
    DependencyBusyError,
    DependencyCircuitOpenError,
    DependencyTimeoutError,
    IntegrationError,
    StorageUnavailableError,
)
from ahia.core.resilience import (
    Bulkhead,
    CircuitBreaker,
    CircuitBreakerConfiguration,
    CircuitState,
    ResiliencePolicy,
    RetryPolicy,
    build_policy,
)


class FakeClock:
    """A monotonic clock a test can advance without sleeping."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def build_breaker(
    *,
    failure_threshold: int = 3,
    reset_timeout_seconds: float = 30.0,
    half_open_probe_count: int = 1,
) -> tuple[CircuitBreaker, FakeClock]:
    clock = FakeClock()
    breaker = CircuitBreaker(
        "storage",
        CircuitBreakerConfiguration(
            failure_threshold=failure_threshold,
            reset_timeout_seconds=reset_timeout_seconds,
            half_open_probe_count=half_open_probe_count,
        ),
        clock=clock,
    )
    return breaker, clock


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_breaker_starts_closed_and_admits_calls() -> None:
    breaker, _ = build_breaker()

    assert breaker.state is CircuitState.CLOSED
    breaker.before_call()
    breaker.record_success()

    assert breaker.metrics.successes == 1


@pytest.mark.unit
def test_breaker_opens_after_the_failure_threshold() -> None:
    breaker, _ = build_breaker(failure_threshold=3)

    for _ in range(3):
        breaker.before_call()
        breaker.record_failure()

    assert breaker.state is CircuitState.OPEN
    assert breaker.metrics.state_transitions == 1


@pytest.mark.unit
def test_open_breaker_fails_fast_with_a_typed_error() -> None:
    breaker, _ = build_breaker(failure_threshold=1)
    breaker.record_failure()

    with pytest.raises(DependencyCircuitOpenError) as captured:
        breaker.before_call()

    assert breaker.metrics.short_circuited_calls == 1
    assert "storage" in str(captured.value)
    # The external view names neither the dependency nor the internal counters.
    assert "storage" not in captured.value.external().message


@pytest.mark.unit
def test_breaker_half_opens_after_the_reset_window() -> None:
    breaker, clock = build_breaker(failure_threshold=1, reset_timeout_seconds=30.0)
    breaker.record_failure()
    assert breaker.state is CircuitState.OPEN

    clock.advance(29.0)
    assert breaker.state is CircuitState.OPEN

    clock.advance(2.0)
    assert breaker.state is CircuitState.HALF_OPEN


@pytest.mark.unit
def test_successful_probe_closes_the_breaker() -> None:
    breaker, clock = build_breaker(failure_threshold=1, reset_timeout_seconds=10.0)
    breaker.record_failure()
    clock.advance(11.0)

    breaker.before_call()
    breaker.record_success()

    assert breaker.state is CircuitState.CLOSED
    assert breaker.metrics.state_transitions == 3
    assert breaker.metrics.failures == 1


@pytest.mark.unit
def test_failed_probe_reopens_the_breaker_immediately() -> None:
    breaker, clock = build_breaker(failure_threshold=5, reset_timeout_seconds=10.0)
    for _ in range(5):
        breaker.record_failure()
    clock.advance(11.0)

    breaker.before_call()
    breaker.record_failure()

    assert breaker.state is CircuitState.OPEN


@pytest.mark.unit
def test_half_open_admits_only_the_configured_number_of_probes() -> None:
    breaker, clock = build_breaker(failure_threshold=1, reset_timeout_seconds=5.0)
    breaker.record_failure()
    clock.advance(6.0)

    breaker.before_call()  # first probe admitted
    with pytest.raises(DependencyCircuitOpenError):
        breaker.before_call()  # second probe refused while the first is in flight


@pytest.mark.unit
def test_state_change_is_logged_with_counters(caplog: pytest.LogCaptureFixture) -> None:
    breaker, _ = build_breaker(failure_threshold=1)

    with caplog.at_level(logging.WARNING, logger="ahia.core.resilience"):
        breaker.record_failure()

    record = caplog.records[0]
    assert record.getMessage() == "circuit_breaker_state_changed"
    assert record.state == "open"
    assert record.previous_state == "closed"
    assert record.dependency == "storage"


@pytest.mark.unit
@pytest.mark.parametrize(
    "configuration",
    [
        {"failure_threshold": 0},
        {"failure_threshold": 1, "reset_timeout_seconds": 0},
        {"failure_threshold": 1, "half_open_probe_count": 0},
    ],
)
def test_breaker_configuration_is_validated(configuration: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        CircuitBreakerConfiguration(**configuration)


# ---------------------------------------------------------------------------
# Bulkhead
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_bulkhead_limits_concurrency() -> None:
    bulkhead = Bulkhead("storage", max_concurrent_calls=2)

    async with bulkhead, bulkhead:
        assert bulkhead.in_flight == 2
        with pytest.raises(DependencyBusyError):
            async with bulkhead:
                pass

    assert bulkhead.in_flight == 0
    assert bulkhead.metrics.peak_concurrency == 2
    assert bulkhead.metrics.rejected == 1


@pytest.mark.asyncio
@pytest.mark.unit
async def test_bulkhead_releases_on_exception() -> None:
    bulkhead = Bulkhead("storage", max_concurrent_calls=1)

    with pytest.raises(RuntimeError):
        async with bulkhead:
            raise RuntimeError("call failed")

    assert bulkhead.in_flight == 0
    async with bulkhead:
        pass


@pytest.mark.asyncio
@pytest.mark.unit
async def test_bulkhead_can_wait_a_bounded_time() -> None:
    bulkhead = Bulkhead("storage", max_concurrent_calls=1, max_wait_seconds=0.5)

    async def hold_then_release() -> None:
        async with bulkhead:
            await asyncio.sleep(0.05)

    holder = asyncio.create_task(hold_then_release())
    await asyncio.sleep(0.01)
    async with bulkhead:
        pass
    await holder


@pytest.mark.unit
def test_bulkhead_configuration_is_validated() -> None:
    with pytest.raises(ValueError):
        Bulkhead("storage", max_concurrent_calls=0)
    with pytest.raises(ValueError):
        Bulkhead("storage", max_concurrent_calls=1, max_wait_seconds=-1)


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_retry_delay_grows_and_stays_bounded() -> None:
    policy = RetryPolicy(max_attempts=5, base_delay_seconds=0.2, max_delay_seconds=1.0)
    # A fixed seed keeps the assertion deterministic; this is a test fixture,
    # not a security decision.
    random_source = random.Random(1234)  # noqa: S311

    delays = [
        policy.delay_for_attempt(attempt, random_source=random_source) for attempt in range(1, 6)
    ]

    assert all(0 <= delay <= 1.0 for delay in delays)
    assert delays[0] <= 0.2
    assert delays[-1] > delays[0]


@pytest.mark.unit
def test_retry_delay_is_jittered() -> None:
    policy = RetryPolicy(max_attempts=3, base_delay_seconds=1.0, max_delay_seconds=1.0)

    draws = {round(policy.delay_for_attempt(3), 6) for _ in range(20)}

    assert len(draws) > 1, "a fixed delay would synchronise every client after an outage"


@pytest.mark.unit
@pytest.mark.parametrize(
    "configuration",
    [
        {"max_attempts": 0},
        {"max_attempts": 2, "base_delay_seconds": 0},
        {"max_attempts": 2, "base_delay_seconds": 1.0, "max_delay_seconds": 0.5},
    ],
)
def test_retry_configuration_is_validated(configuration: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        RetryPolicy(**configuration)


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


def build_policy_with(
    *,
    timeout_seconds: float = 1.0,
    failure_threshold: int = 3,
    reset_timeout_seconds: float = 30.0,
    max_concurrent_calls: int = 5,
    retry: RetryPolicy | None = None,
    sleep: Any = None,
) -> tuple[ResiliencePolicy, FakeClock]:
    clock = FakeClock()
    breaker = CircuitBreaker(
        "storage",
        CircuitBreakerConfiguration(
            failure_threshold=failure_threshold,
            reset_timeout_seconds=reset_timeout_seconds,
        ),
        clock=clock,
    )
    policy = ResiliencePolicy(
        dependency_name="storage",
        timeout_seconds=timeout_seconds,
        breaker=breaker,
        bulkhead=Bulkhead("storage", max_concurrent_calls=max_concurrent_calls),
        retry=retry,
        _sleep=sleep or asyncio.sleep,
    )
    return policy, clock


@pytest.mark.asyncio
@pytest.mark.unit
async def test_successful_call_returns_the_result_and_records_metrics() -> None:
    policy, _ = build_policy_with()

    async def call() -> str:
        return "stored"

    result = await policy.execute(call, operation="upload_object")

    assert result == "stored"
    assert policy.metrics.successes == 1
    assert policy.breaker.state is CircuitState.CLOSED


@pytest.mark.asyncio
@pytest.mark.unit
async def test_slow_call_times_out_with_a_typed_error() -> None:
    policy, _ = build_policy_with(timeout_seconds=0.05)

    async def slow_call() -> str:
        await asyncio.sleep(1.0)
        return "never"

    with pytest.raises(DependencyTimeoutError) as captured:
        await policy.execute(slow_call, operation="upload_object")

    assert policy.metrics.timeouts == 1
    assert "timeout_seconds=0.05" in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_provider_exception_is_translated_and_never_escapes_raw() -> None:
    policy, _ = build_policy_with(failure_threshold=5)

    class S3ProviderError(Exception):
        """A vendor exception type that must not cross the boundary."""

    async def call() -> str:
        raise S3ProviderError("https://key:supersecret@bucket.example.com failed")

    with pytest.raises(IntegrationError) as captured:
        await policy.execute(call, operation="upload_object")

    assert not isinstance(captured.value, S3ProviderError)
    assert "S3ProviderError" in str(captured.value)
    assert "supersecret" not in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_breaker_opens_through_the_policy_and_fails_fast() -> None:
    policy, _ = build_policy_with(failure_threshold=2)

    async def failing_call() -> str:
        raise StorageUnavailableError(operation="upload_object")

    for _ in range(2):
        with pytest.raises(StorageUnavailableError):
            await policy.execute(failing_call, operation="upload_object")

    with pytest.raises(DependencyCircuitOpenError):
        await policy.execute(failing_call, operation="upload_object")


@pytest.mark.asyncio
@pytest.mark.unit
async def test_idempotent_call_is_retried_up_to_the_limit() -> None:
    attempts = 0
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    policy, _ = build_policy_with(
        retry=RetryPolicy(max_attempts=3, base_delay_seconds=0.1, max_delay_seconds=0.1),
        sleep=record_sleep,
        failure_threshold=10,
    )

    async def flaky_call() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise StorageUnavailableError(operation="upload_object")
        return "stored"

    result = await policy.execute(flaky_call, operation="upload_object", is_idempotent=True)

    assert result == "stored"
    assert attempts == 3
    assert policy.metrics.retries == 2
    assert len(sleeps) == 2


@pytest.mark.asyncio
@pytest.mark.unit
async def test_non_idempotent_call_is_never_retried() -> None:
    attempts = 0
    policy, _ = build_policy_with(
        retry=RetryPolicy(max_attempts=3),
        failure_threshold=10,
    )

    async def failing_write() -> str:
        nonlocal attempts
        attempts += 1
        raise StorageUnavailableError(operation="delete_object")

    with pytest.raises(StorageUnavailableError):
        await policy.execute(failing_write, operation="delete_object", is_idempotent=False)

    assert attempts == 1, "retrying a non-idempotent write is how duplicates are created"
    assert policy.metrics.retries == 0


@pytest.mark.asyncio
@pytest.mark.unit
async def test_non_retryable_error_is_not_retried() -> None:
    attempts = 0
    policy, _ = build_policy_with(retry=RetryPolicy(max_attempts=3), failure_threshold=10)

    async def failing_call() -> str:
        nonlocal attempts
        attempts += 1
        raise ValueError("a programming error, not a transient one")

    with pytest.raises(IntegrationError):
        await policy.execute(
            failing_call,
            operation="upload_object",
            retryable_errors=(StorageUnavailableError,),
        )

    assert attempts == 1


@pytest.mark.asyncio
@pytest.mark.unit
async def test_typed_fallback_is_returned_on_failure() -> None:
    policy, _ = build_policy_with(failure_threshold=5)

    class DegradedUpload:
        is_degraded = True
        degradation_reason = "storage_unavailable"

        def __init__(self) -> None:
            self.storage_key: str | None = None

    async def fallback(error: BaseException) -> DegradedUpload:
        return DegradedUpload()

    async def failing_call() -> DegradedUpload:
        raise StorageUnavailableError(operation="upload_object")

    result = await policy.execute(
        failing_call,
        operation="upload_object",
        fallback=fallback,
    )

    assert result.is_degraded is True
    assert policy.metrics.fallbacks_activated == 1


@pytest.mark.asyncio
@pytest.mark.unit
async def test_fallback_returning_none_fails_loudly() -> None:
    """A fallback that returns None turns a visible failure into an invisible one."""
    policy, _ = build_policy_with(failure_threshold=5)

    async def fallback(error: BaseException) -> Any:
        return None

    async def failing_call() -> Any:
        raise StorageUnavailableError(operation="upload_object")

    with pytest.raises(IntegrationError) as captured:
        await policy.execute(failing_call, operation="upload_object", fallback=fallback)

    assert "fallback returned None" in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_bulkhead_refusal_surfaces_as_a_typed_error() -> None:
    policy, _ = build_policy_with(max_concurrent_calls=1)

    async def slow_call() -> str:
        await asyncio.sleep(0.1)
        return "stored"

    async def occupy() -> None:
        await policy.execute(slow_call, operation="upload_object")

    holder = asyncio.create_task(occupy())
    await asyncio.sleep(0.01)

    with pytest.raises(DependencyBusyError):
        await policy.execute(slow_call, operation="upload_object")

    await holder


@pytest.mark.unit
def test_policy_requires_a_bounded_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        ResiliencePolicy(
            dependency_name="storage",
            timeout_seconds=0,
            breaker=CircuitBreaker("storage", CircuitBreakerConfiguration()),
            bulkhead=Bulkhead("storage", max_concurrent_calls=1),
        )


@pytest.mark.unit
def test_build_policy_wires_every_primitive() -> None:
    policy = build_policy(
        "r2",
        timeout_seconds=5.0,
        breaker_configuration=CircuitBreakerConfiguration(failure_threshold=4),
        max_concurrent_calls=8,
        retry=RetryPolicy(max_attempts=2),
    )

    description = policy.describe()

    assert description["dependency"] == "r2"
    assert description["timeout_seconds"] == 5.0
    assert description["bulkhead_limit"] == 8
    assert description["retry_attempts"] == 2
    assert description["breaker_failure_threshold"] == 4


@pytest.mark.unit
def test_two_dependencies_never_share_a_breaker() -> None:
    """One breaker per dependency: a shared one lets one outage trip the other."""
    first = build_policy(
        "r2",
        timeout_seconds=1.0,
        breaker_configuration=CircuitBreakerConfiguration(failure_threshold=1),
        max_concurrent_calls=2,
    )
    second = build_policy(
        "cloudinary",
        timeout_seconds=1.0,
        breaker_configuration=CircuitBreakerConfiguration(failure_threshold=1),
        max_concurrent_calls=2,
    )

    first.breaker.record_failure()

    assert first.breaker.state is CircuitState.OPEN
    assert second.breaker.state is CircuitState.CLOSED
