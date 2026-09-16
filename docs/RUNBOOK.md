# Runbook

What to do when this service is running somewhere other than a laptop. Startup, migrations,
rollback, secret rotation, breaker trips, and how to trace one failing request from a client's report
back to a log line.

The environment variable reference is `docs/PREREQUISITES.md`; this document assumes the variables
exist and is about operating them. Nothing here is a substitute for the check gate: `make check` is
what decides whether a revision is releasable.

---

## 1. What runs

| Piece | Command | Notes |
|---|---|---|
| API | `uvicorn ahia.main:app --host 0.0.0.0 --port 8000` | No autoreload outside development |
| Migrations | `alembic upgrade head` | Once per release, before the API is started |
| Low-stock job | `python -m ahia.jobs.low_stock_alerts` | Scheduled, hourly or daily; exit code is the alert |

The API opens no connection at import time: the container is built in the lifespan, so a migrator, a
test or a CLI can import the application without touching the database. That also means startup
succeeds while the database is down, and the readiness probe is what keeps the instance out of
rotation - a liveness probe that checked the database would turn a database outage into a restart
loop instead.

**One process, one pool.** Pool size is `DATABASE_POOL_SIZE` plus `DATABASE_MAX_OVERFLOW` per
instance. Scale the instance count against the database's connection limit, not against the CPU
count: an instance that cannot get a connection is an instance that answers 503 on the readiness
probe.

---

## 2. Deploy

1. **Migrate first, then start the new code.** The other order works only until a release that
   needs a column. `alembic upgrade head` uses `DATABASE_MIGRATION_URL` when it is set, and
   `DATABASE_URL` otherwise.
   - Production needs the migration to run as a role that may create policies and tables. The
     application role may be the same one; the Row-Level Security migration sets
     `FORCE ROW LEVEL SECURITY`, so the policies bind the owner as well.
2. **Start the API.** It refuses to start on invalid configuration rather than serving with a
   half-configured container. In `APP_ENV=production` it specifically refuses: a non-JSON log
   format, `DATABASE_REQUIRE_SSL` other than `true`, `LOG_LEVEL=DEBUG`, CORS with a wildcard origin
   while credentials are enabled, a `DATABASE_URL` that is not `postgresql+asyncpg://`, missing
   credentials for the *active* storage provider (and only that one), a `JWT_SECRET` or
   `REFRESH_TOKEN_PEPPER` shorter than the production minimum, and a media size policy where
   `MAX_PRODUCT_IMAGE_SIZE_MB` exceeds `MAX_UPLOAD_SIZE_MB`.
3. **Confirm the revision is live.** `GET /health` returns `{"status": "ok", "name": ..., "version":
   ...}` from the process that answers. A load balancer still holding an old instance answers with
   the old version, which is how a "fixed" deployment turns out to be half-deployed.
4. **Confirm readiness.** `GET /ready` answers `{"status": "ready"}` when the database answers, and
   503 `{"status": "not_ready"}` otherwise. It checks the database only: object storage and
   messaging are optional dependencies, and their unavailability must not remove an instance from
   rotation.
5. **Read the startup log once.** Every feature flag is logged at INFO with its resolved value, one
   line per flag, and `application_started` marks the boundary. If the system behaves differently
   from what was intended, this is the first thing to read rather than the last.

---

## 3. Migrations

- **Apply:** `alembic upgrade head`.
- **One step back:** `alembic downgrade -1`. Every revision has a working `downgrade`; the migration
  baseline test takes the whole chain down to an empty database and back up on every build.
- **Never edit an applied revision.** A revision that has run somewhere is immutable; the next
  revision corrects it.
- **Migrations must be backwards compatible for one release** if you want to roll the application
  back without rolling the schema back: add columns as nullable or with a default, drop them in a
  later release, and never rename in place.
- **A data migration that touches a business-owned table must say so.** Row-Level Security is on for
  twenty tables; a migration that reads or writes one of them needs either the scope set
  (`SELECT set_config('app.current_tenant', '<uuid>', true)`) or an explicit
  `ALTER TABLE ... NO FORCE ROW LEVEL SECURITY` for the duration. DDL - creating a table or a
  policy - is not affected.
- **A new business-owned table needs its policy in the migration that creates it**, plus its name in
  `TENANT_SCOPED_TABLES` in `tests/migrations/test_row_level_security.py`. A table with a
  `tenant_id` column and no policy is a table where a forgotten filter is silent again.

---

## 4. Rollback

**Application rollback is the common case** and is safe when the release's migrations were backwards
compatible: deploy the previous image, leave the schema alone. Data written by the new code may be
ignored by the old code, which is exactly why columns are added rather than renamed.

**Schema rollback is the incident case.** `alembic downgrade -1` reverses one revision; repeat for
each. Before doing it, answer two questions:

1. *What does the downgrade drop?* Read the revision's `downgrade` before running it. Dropping a
   table is not recoverable from the application's side; the backup is.
2. *Is the data replaceable?* `inventory_movements`, `ledger_entries` and `audit_events` are
   append-only by database trigger: no update, no delete, and a downgrade that drops them destroys
   the only copy. Take a database snapshot first; the snapshot is the rollback plan for those.

**Rolling back the Row-Level Security revision** (`56912421e4aa`) drops the policies and disables
RLS. The application keeps filtering by `tenant_id`, so this is a degradation to one line of defence,
not an outage - and it is worth doing if the policies are the suspected cause of empty responses,
because the symptom of a wrong scope is a successful empty result rather than an error.

---

## 5. Secrets

Rotate by changing the value in the secret store, restarting the API, and verifying the readiness
probe. Never place a secret in a URL, a log line, a ticket or a metric label.

| Secret | What it protects | Rotating it invalidates | Notes |
|---|---|---|---|
| `JWT_SECRET` | Access token signatures, refresh token signatures | Every access token: clients re-authenticate. Refresh tokens stay valid because they are verified against a stored digest, not the signature | 32+ characters in production; two-step rotation is not possible without dual-key verification, so plan a short re-login window |
| `REFRESH_TOKEN_PEPPER` | The digest stored for every bearer credential | **All refresh tokens, all pending membership invitations, and all share links.** Users are logged out and must sign in again; invitations must be re-sent; shared invoice and report links stop opening | The single most disruptive rotation. Verify by signing in on a known account afterwards |
| `DATABASE_URL` password | The application's database role | Nothing, if the old password is retired after the new one is live | The role must not be a superuser and must not bypass RLS in production, or the policies protect nothing. The URL must be `postgresql+asyncpg://` and `DATABASE_REQUIRE_SSL=true` |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | Object storage | Nothing | Rotate the key pair at the provider, update both variables, restart. `STORAGE_PROVIDER=r2` requires both non-empty or the service will not start |
| `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | Object storage when `STORAGE_PROVIDER=cloudinary` | Nothing | Required only when Cloudinary is the active provider |
| `METRICS_AUTH_TOKEN` | `GET /metrics` | The scraper's access until it is updated | Rotate in two steps: configure the new token in the scraper, then here, then remove the old one. Without a token the endpoint answers as if it did not exist |

`backend/.env` is gitignored and must stay that way. `.env.example` holds placeholders only.

---

## 6. Health, metrics and what to watch

| Path | Purpose | Notes |
|---|---|---|
| `GET /health` | Liveness | Never touches a dependency on purpose |
| `GET /ready` | Readiness | The database only; 503 when it is unreachable |
| `GET /metrics` | Prometheus exposition | Closed unless `METRICS_AUTH_TOKEN` is configured, then bearer-token only, compared with `hmac.compare_digest` |

Series that answer most questions:

- `ahia_http_requests_total{route,class}` - traffic and status classes per route.
- `ahia_http_request_duration_seconds_max{route}` - the slowest request seen since start.
- `ahia_errors_total{code}` - failures by the code a client was told.
- `ahia_authorization_denials_total{action}` - refused decisions by missing permission. A rise here
  is either a client bug or somebody probing; the log line beside it names principal, resource and
  outcome.
- `ahia_circuit_breaker_state{dependency}` - 0 closed, 1 half-open, 2 open.
- `ahia_circuit_breaker_short_circuits_total{dependency}` - calls refused without being attempted.

Route labels have UUIDs, long hex values and integers replaced by `{id}`, so the series count depends
on the API's shape rather than on traffic. No correlation ID, tenant or user identifier reaches a
label.

---

## 7. A breaker trip

**Symptom:** requests to a feature that depends on object storage fail fast with a 503 and the log
carries `circuit_breaker_rejected_call` with `breaker_state=open`; the dependency's
`ahia_circuit_breaker_state` gauge reads 2.

**What happened:** one dependency (object storage, or an outbound HTTP call) failed
`STORAGE_CIRCUIT_FAILURE_THRESHOLD` times in a row, so the breaker stopped attempting it for
`STORAGE_CIRCUIT_RESET_SECONDS`, then admitted a bounded number of probes.

**What to do:**

1. Look at the *dependency*, not the breaker. The breaker is reporting a fact about the provider:
   credentials revoked, bucket deleted, network path blocked, provider incident.
2. Fix the dependency. The breaker closes on the first successful probe after the reset window; a
   restart is not required and does not help.
3. If the retry policy is the problem, check `STORAGE_RETRY_MAX_ATTEMPTS`. Retries are bounded with
   exponential backoff and jitter, and only ever applied to idempotent operations - a non-idempotent
   write is never retried, because a duplicate payment is worse than a failed one.
4. **Do not** raise the timeout or threshold to hide it, and never disable TLS or certificate
   validation as a workaround. A certificate that does not validate is an attack, not a nuisance.

Half-open admits one in-flight probe at a time and refuses further calls until that probe reports. The
probe count is a property of the breaker, not an environment variable, so it does not vary by
deployment. If the state looks stuck at half-open, it means a probe never reported - look for a hung
worker on that instance.

---

## 8. Tracing one failing request

Every response carries a correlation ID, generated at the transport boundary or taken from the
inbound `X-Correlation-ID` header after it is validated against a strict character set and length
bound. A caller cannot inject control characters or an enormous value into every log line.

**From a client report:**

1. Ask for the correlation ID. It is in the client's error screen and in the response body:
   `{"error": {"code": ..., "message": ..., "correlation_id": ...}}`.
2. Grep the logs for it. Every line written while handling that request carries the field, in JSON.

```
jq 'select(.correlation_id == "<id>")' service.log
```

3. The first line with `layer=service` or `layer=crud` in the chain is usually the cause; the last is
   usually the symptom. `error_type` and `operation` name the failing call, and the cause chain is
   preserved rather than flattened.

**What the client never sees**, and therefore what you must read from the logs: stack traces, SQL,
table and column names, file paths, hostnames, internal service names, and whether a user, email or
resource exists. The external body has three fields and no more - a fourth is how an internal detail
escapes.

**If the correlation ID is absent from the response**, the failure happened outside the correlation
middleware or before it: look for a proxy error, a TLS handshake failure, or an instance that never
started.

---

## 9. Empty responses, and Row-Level Security

**Symptom:** an endpoint answers `200` with an empty list or an empty page, for a business that
plainly has data.

This is the one failure mode the policies create, and it is why this section exists: a missing or
wrong scope is a *successful* empty result, not an error. Checklist:

1. Is the request authenticated and routed through a tenant-scoped path? A path that never resolves a
   `TenantContext` also never binds a scope.
2. Is the row in the business the caller is authorized for? The scope comes from the resolved
   membership, not from the identifier in the URL.
3. Does the table have a policy, and is the name in the migration's list? A table with a
   `tenant_id` column and no policy returns everything, which is the other failure.
4. Confirm the database agrees: `SELECT current_setting('app.current_tenant', true);` inside a
   transaction should return the business's UUID, or an empty string when no scope is bound. The
   policies treat both empty and unset as "no scope", which is why the predicate uses
   `nullif(..., '')`.

Public paths - the shop address and a share link - resolve the business first and then read inside
its scope, in a second transaction. If a public page renders an empty catalogue while the data
exists, the resolution step is the place to look.

---

## 10. Rate limits, and what a throttled client sees

| Class | Default | Applies to |
|---|---|---|
| `AUTHENTICATION` | 10/min | Login, signup, token refresh |
| `MESSAGE_SENDING` | 5/hour | Password reset, invitations |
| `WRITE` | 120/min | Create, update, delete |
| `PUBLIC_READ` | 120/min | `/shop/`, `/share/` |
| `GLOBAL` | 600/min | Everything else |

A throttled request answers `429` with a `Retry-After` header and the same three-field error envelope
every other failure uses, correlation ID included, so a support ticket is still traceable. Counters are
per process: with several instances, the effective limit is the sum, and a client that trips one
instance is not globally blocked. **Never** disable or weaken a limit to resolve a support complaint;
raise the configured number, which is a deployment decision with a record.

Security controls are not feature flags. Authentication, authorization, input validation and rate
limiting are always on, and no configuration disables them.

---

## 11. The scheduled low-stock evaluation

```
python -m ahia.jobs.low_stock_alerts
```

- Exit `0`: every business was evaluated.
- Exit `1`: at least one business failed; the summary names each one and the reason. One business's
  failure never stops the others, which is why a single failure is a report rather than an abort.
- Exit `2`: the job was given arguments. It takes none.

The job binds each business as its Row-Level Security scope in turn, and the dedupe key is per
recipient per product per day, so running it more often raises no additional notifications. It prints
a plain-ASCII summary; there are no emoji anywhere in the output by design.

---

## 12. Common incidents

| Symptom | First check | Action |
|---|---|---|
| Readiness 503 on every instance | Database reachable? Connection limit reached? | Fix the database or the pool size; do not restart in a loop |
| 502 from the load balancer, `/health` fine | Is the instance listening, and are the routes mounted? | Read the startup log; a config error is refused at boot, not at first request |
| 429 for one client only | Which class, and is the client retrying without backoff? | Raise the configured limit deliberately, or fix the client |
| 500 with `INTERNAL_ERROR` | Grep the correlation ID; the code is deliberately generic | Fix the cause; the external message will not change |
| 401 for every client after a deploy | `JWT_SECRET` changed? | Expected on rotation: clients re-authenticate. If unintended, restore the previous secret |
| Share links stopped opening | Was `REFRESH_TOKEN_PEPPER` rotated? | Expected: links are stored as peppered digests. Re-issue them |
| Empty lists after enabling Row-Level Security | Section 9 | Fix the scope; do not disable the policies to work around it |
| Storage uploads failing fast | `ahia_circuit_breaker_state{dependency="storage"}` | Section 7 |

---

## 13. Never

- Never run production with `APP_ENV=development`. It disables the documentation URLs' protection by
  publishing them, and skips the production configuration checks above.
- Never disable TLS or certificate verification, including "temporarily" and including in tests.
- Never put a secret in a URL, a query string, a log line or a metric label.
- Never run migrations against a database whose snapshot you are not willing to restore.
- Never gate a security control behind a flag, or add a flag without a removal condition.
- Never commit `backend/.env`, and never put a real value in `.env.example`.
