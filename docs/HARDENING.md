# Hardening

What this service does to stay safe and observable in production, and what a deployment has to do
around it. Each section names the code that enforces it, so a reader can check the claim rather than
believe it.

---

## 1. Rate limiting

Limits are enforced by `middleware/rate_limit_middleware.py`, before a request reaches a route. Every
limit is configuration, because a limit that cannot be changed without a deploy is changed by an
emergency hotfix.

| Class | Paths | Default | Why |
|---|---|---|---|
| Authentication | `/auth/login`, `/auth/register`, `/auth/refresh`, `/auth/token` | 10/min | The cheapest place to guess a password. |
| Message sending | `/auth/password-reset`, `/auth/forgot-password`, `/invitations` | 5/hour | Each request sends a message to somebody who did not ask for it at that moment. |
| Write | every `POST`, `PUT`, `PATCH`, `DELETE` | 120/min | A mutating endpoint limited only globally is not limited. |
| Public shop | `/shop/`, `/share/` | 120/min | The one surface an anonymous caller reaches; cheap to serve and easy to scrape. |
| Global | everything else | 600/min | The floor under every request. |

**Counters are per process.** A deployment with several API instances enforces each limit per
instance, which is weaker than a shared counter. That is an accepted, documented limitation for a
single-instance deployment; a shared store is the change that removes it, and nothing else in the
middleware has to move.

**The limiter fails closed.** A request whose identity cannot be determined gets the conservative
global limit rather than no limit, and `X-Forwarded-For` is trusted only up to the configured number
of proxies, so a client cannot present unlimited identities.

**The review is a test.** `tests/middleware/test_rate_limit_coverage.py` walks every registered route
and fails the build when a write route lands in the global bucket, when one of the named classes has
no routes, or when a bucket has no configured limit.

---

## 2. Metrics

`GET /metrics` renders the Prometheus text exposition format from a registry built per application
(`core/metrics.py`), so nothing is process-global and two applications in one process cannot share
counters.

Recorded: request count by route and status class, total and maximum duration per route, failures by
the code a client was told, authorization denials by the use case that refused, and circuit-breaker
state and short circuits per dependency.

**The endpoint is closed until somebody opens it.** It answers only when `METRICS_AUTH_TOKEN` is
configured, and then only to a caller presenting it as a bearer token, compared with
`hmac.compare_digest`. Unconfigured, the path answers as if it did not exist. Route the path to your
monitoring network as well: the token is the second line, not the only one.

**Labels are bounded.** A path label has its UUIDs, long hex values and integers replaced by `{id}`,
so the series count depends on the API's shape rather than on traffic. No correlation ID, tenant
identifier, user identifier or query string reaches a label; a label is written to a system with its
own retention and its own readers.

**Rotation.** A scraper is configured with the token, so rotation is two steps: add the new token to
the scraper, set it here, then remove the old one.

---

## 3. Error reporting

Every failure produces two views joined by a correlation ID.

- **Internal** (`logs`, `error.context`): operation, entity, identifier, layer, correlation ID, the
  value that failed validation, the dependency that timed out, chained causes.
- **External** (the response body): an error code, a correlation ID, and a message that says nothing
  about stack traces, SQL, file paths, internal service names, or whether a record exists.

`GET /health` and `GET /ready` report liveness and readiness and nothing else: no versions, no
connection strings, no dependency list.

**Redaction lives in the logger**, not at each call site: `core/logging.py` applies the rules, so a
call site that logs a field the rules forbid still produces a redacted line.

---

## 4. What is not yet in place

Stated here rather than left to be discovered:

- **Row-Level Security** on the highest-risk tables is planned and not implemented. The plan and its
  preconditions are in this document as they land.
- **Per-process rate limiting** as described above.
- **No server-side message sending.** The WhatsApp integration builds a click-to-chat link that the
  client opens; nothing in this service sends a message on a business's behalf yet. When one lands, it
  belongs in the message-sending rate-limit class.
- **In-flight breaker metrics** reporting: breakers record state and short circuits, not latency
  histograms per dependency.
