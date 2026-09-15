"""Metrics: the numbers an operator watches, rendered where a platform can read them.

The specification asks for request duration, error count, authorization denial and breaker state in
a
form the platform can scrape. This module is the registry those numbers live in, and the renderer
that
turns them into the text exposition format Prometheus reads.

**The registry is constructed, not imported.** There is no module-level singleton: the composition
root builds one and injects it into the middleware and the route, so two applications in one process
cannot share counters and a test can build one without a running server. That is the same rule the
rest of this codebase follows for connections and clients, applied to numbers.

**Labels are bounded by construction.** A metric labelled with a raw path is a metric with one
series
per identifier a client invents, which is how a metrics store fills up and a scrape times out. The
route label is normalised - identifiers are replaced by their placeholder - so the series count
depends on the API's shape rather than on traffic.

**No personal data and no identifiers reach a label.** A label is written to a monitoring system
with
its own retention and its own access rules, so what goes in is a method, a normalised route, a
status
class and an error code. Never a correlation ID, a tenant, a user or a query string.

**Counters only, and no timers.** A histogram needs buckets chosen per service, and buckets chosen
wrongly are worse than none; the middleware records a count, a total duration and a maximum, which
is
what an operator needs to answer "is this slow, how often, and how slow was the worst". A quantile
is
a decision for whoever owns the deployment's monitoring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

#: Identifiers in a path are replaced by a placeholder so a route label is a route rather than a
#: series per client-invented value. UUIDs first, then long hex, then integers.
_UUID_IN_PATH: Final[re.Pattern[str]] = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_LONG_HEX_IN_PATH: Final[re.Pattern[str]] = re.compile(r"\b[0-9a-fA-F]{16,}\b")
_INTEGER_IN_PATH: Final[re.Pattern[str]] = re.compile(r"(?<=/)\d+(?=/|$)")


def normalise_route(path: str) -> str:
    """Return a path with its identifiers replaced, for use as a metric label."""
    normalised = _UUID_IN_PATH.sub("{id}", path)
    normalised = _LONG_HEX_IN_PATH.sub("{id}", normalised)
    return _INTEGER_IN_PATH.sub("{id}", normalised)


def status_class(status_code: int) -> str:
    """Return the class of a status code: `2xx`, `4xx`, and so on."""
    return f"{status_code // 100}xx"


@dataclass(slots=True)
class RouteMetrics:
    """What was recorded for one route label."""

    requests: int = 0
    total_duration_seconds: float = 0.0
    maximum_duration_seconds: float = 0.0

    def observe(self, *, duration_seconds: float) -> None:
        self.requests += 1
        self.total_duration_seconds += duration_seconds
        self.maximum_duration_seconds = max(self.maximum_duration_seconds, duration_seconds)


@dataclass(slots=True)
class MetricsRegistry:
    """Every counter and total this process reports.

    One instance per application, built in the composition root. The counters are plain dictionaries
    and integers: this process is single-threaded per event loop, the increments are single bytecode
    operations under the GIL, and a lock here would be a lock on the request path for numbers nobody
    reads atomically.
    """

    #: (method, route, status class) -> count
    requests_by_route: dict[tuple[str, str, str], int] = field(default_factory=dict)
    #: (method, route) -> durations
    durations_by_route: dict[tuple[str, str], RouteMetrics] = field(default_factory=dict)
    #: error code -> count, including the ones a client never sees as a distinct status
    errors_by_code: dict[str, int] = field(default_factory=dict)
    #: the permission that was refused -> count
    authorization_denials: dict[str, int] = field(default_factory=dict)
    #: dependency -> state, as the breaker last reported it
    breaker_states: dict[str, str] = field(default_factory=dict)
    #: dependency -> count of calls the breaker refused without trying
    breaker_short_circuits: dict[str, int] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def observe_request(
        self, *, method: str, path: str, status_code: int, duration_seconds: float
    ) -> None:
        """Record one completed request."""
        route = normalise_route(path)
        request_key = (method.upper(), route, status_class(status_code))
        self.requests_by_route[request_key] = self.requests_by_route.get(request_key, 0) + 1
        self.durations_by_route.setdefault((method.upper(), route), RouteMetrics()).observe(
            duration_seconds=duration_seconds
        )

    def record_error(self, *, error_code: str) -> None:
        """Record one failure by its code, which is what a client was told."""
        self.errors_by_code[error_code] = self.errors_by_code.get(error_code, 0) + 1

    def record_authorization_denial(self, *, action: str) -> None:
        """Record one refused authorization decision, by the permission that was missing."""
        self.authorization_denials[action] = self.authorization_denials.get(action, 0) + 1

    def record_breaker_state(self, *, dependency: str, state: str) -> None:
        """Record the current state of one dependency's breaker."""
        self.breaker_states[dependency] = state

    def record_breaker_short_circuit(self, *, dependency: str) -> None:
        """Record one call a breaker refused without attempting it."""
        self.breaker_short_circuits[dependency] = self.breaker_short_circuits.get(dependency, 0) + 1

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self) -> str:
        """Return the metrics in the Prometheus text exposition format.

        Built by hand rather than with a client library: the format is four lines of syntax, the
        dependency would be another pinned package to audit, and a client library that registers
        process-wide collectors is exactly the module-level singleton this codebase forbids.
        """
        lines: list[str] = []

        lines.append("# HELP ahia_http_requests_total Requests completed, by route and class.")
        lines.append("# TYPE ahia_http_requests_total counter")
        for method, route, class_ in sorted(self.requests_by_route):
            count = self.requests_by_route[(method, route, class_)]
            labels = f'method="{method}",route="{route}",status_class="{class_}"'
            lines.append(f"ahia_http_requests_total{{{labels}}} {count}")

        lines.append("# HELP ahia_http_request_duration_seconds_total Total time spent, by route.")
        lines.append("# TYPE ahia_http_request_duration_seconds_total counter")
        for method, route in sorted(self.durations_by_route):
            total = self.durations_by_route[(method, route)].total_duration_seconds
            labels = f'method="{method}",route="{route}"'
            lines.append(f"ahia_http_request_duration_seconds_total{{{labels}}} {total:.6f}")

        lines.append(
            "# HELP ahia_http_request_duration_seconds_max Slowest request seen, by route."
        )
        lines.append("# TYPE ahia_http_request_duration_seconds_max gauge")
        for method, route in sorted(self.durations_by_route):
            maximum = self.durations_by_route[(method, route)].maximum_duration_seconds
            labels = f'method="{method}",route="{route}"'
            lines.append(f"ahia_http_request_duration_seconds_max{{{labels}}} {maximum:.6f}")

        lines.append("# HELP ahia_errors_total Failures by the code a client was told.")
        lines.append("# TYPE ahia_errors_total counter")
        for code in sorted(self.errors_by_code):
            lines.append(f'ahia_errors_total{{code="{code}"}} {self.errors_by_code[code]}')

        lines.append(
            "# HELP ahia_authorization_denials_total Refused decisions, by missing permission."
        )
        lines.append("# TYPE ahia_authorization_denials_total counter")
        for action in sorted(self.authorization_denials):
            count = self.authorization_denials[action]
            lines.append(f'ahia_authorization_denials_total{{action="{action}"}} {count}')

        lines.append(
            "# HELP ahia_circuit_breaker_state Breaker state per dependency: 0 closed, "
            "1 half open, 2 open."
        )
        lines.append("# TYPE ahia_circuit_breaker_state gauge")
        for dependency in sorted(self.breaker_states):
            state = self.breaker_states[dependency]
            value = _BREAKER_STATE_VALUES.get(state, 0)
            lines.append(f'ahia_circuit_breaker_state{{dependency="{dependency}"}} {value}')

        lines.append("# HELP ahia_circuit_breaker_short_circuits_total Calls a breaker refused.")
        lines.append("# TYPE ahia_circuit_breaker_short_circuits_total counter")
        for dependency in sorted(self.breaker_short_circuits):
            count = self.breaker_short_circuits[dependency]
            lines.append(
                f'ahia_circuit_breaker_short_circuits_total{{dependency="{dependency}"}} {count}'
            )

        return "\n".join(lines) + "\n"

    @property
    def content_type(self) -> str:
        """Return the content type the exposition format uses."""
        return "text/plain; version=0.0.4; charset=utf-8"


#: The numeric values the exposition format needs for a state gauge. A label would be more readable
#: and less usable: an alert on "the breaker is open" is an expression on a number.
_BREAKER_STATE_VALUES: Final[dict[str, int]] = {
    "closed": 0,
    "half_open": 1,
    "open": 2,
}
