# AHIA - Task Plan (Milestones, Sub-milestones, Micro-milestones)

Status: living execution plan
Source of truth for scope: `PRODUCT_INITIAL_DEFINITION/` (project specification,
database and domain specification, backend scaffold specification)
Companion document: `docs/PREREQUISITES.md`

---

## How this file works

Three levels of granularity.

- A **milestone** (M0, M1, ...) is a coherent capability that can be
  demonstrated end to end.
- A **sub-milestone** (M0.1, M0.2, ...) is a deliverable inside a milestone,
  usually a layer, a module or a workflow.
- A **micro-milestone** (M0.1.1, M0.1.2, ...) is the smallest unit of work that
  is worth its own commit. Every micro-milestone produces working, reviewed,
  check-passing files.

Rule: **one micro-milestone equals one commit.** Nothing is committed that does
not pass `make check`. Nothing is marked done that is not committed.

Status markers:

- `[ ]` not started
- `[~]` in progress or partially landed
- `[x]` done, committed and passing checks
- `[-]` deliberately deferred, with the reason recorded inline

### Commit convention

```text
<type>(<scope>): <imperative summary under 72 characters>

<body: what changed, why it changed, what the reviewer should check,
      which invariants from the specifications this implements>

<footer: references to the micro-milestone, for example "Task: M1.2.1">
```

Allowed types: `feat`, `fix`, `docs`, `test`, `chore`, `refactor`, `perf`,
`build`, `ci`, `security`.

Hard rules for every commit in this repository:

1. Author is `Ksschkw <kookafor893@gmail.com>` and nobody else.
2. No `Co-authored-by` trailer, ever.
3. No emojis and no non-ASCII characters in the message.
4. The body states what was implemented and which specification invariant it
   satisfies. "wip" and "fixes" are not acceptable bodies.
5. The commit references its micro-milestone identifier.

### Definition of done for a micro-milestone

1. The code is real and runnable. No `TODO: implement` stubs, no placeholder
   returns, no commented-out code.
2. Tests exist at the layer being changed, mocking only the layer beneath it.
3. `make check` passes: lint, format check, type check, ASCII guard, tests,
   architecture contracts, secret scan, dependency audit.
4. The architecture rules hold: no outward imports, no logic in transport, no
   database driver outside the persistence boundary, no `os.getenv` outside
   `core/config.py`.
5. This task file is updated to `[x]` in the same commit.

### Definition of done for a milestone

The milestone exit criteria are demonstrated by an executable check, not by an
assertion in a commit message.

---

## Milestone index

| Milestone | Title | Status | Depends on |
|---|---|---|---|
| M0 | Repository and developer tooling foundation | `[x]` | - |
| M1 | Core cross-cutting infrastructure | `[x]` | M0 |
| M2 | User demonstrative vertical slice | `[x]` | M1 |
| M3 | Authentication and sessions | `[x]` | M2 |
| M4 | Tenant slice | `[x]` | M3 |
| M5 | Membership and staff administration | `[x]` | M4 |
| M6 | Roles, permissions and deny-by-default authorization | `[x]` | M5 |
| M7 | Devices and session management | `[x]` | M6 |
| M8 | Alembic migration baseline (M8.1.4 delivered in M9) | `[x]` | M6 |
| M9 | Catalog: categories, products, images, storage | `[x]` | M8 |
| M10 | Inventory ledger and projections | `[x]` | M9 |
| M11 | Customers | `[x]` | M9 |
| M12 | Sales, payments, ledger, transactional integrity | `[x]` | M10, M11 |
| M13 | Expenses | `[x]` | M12 |
| M14 | Audit trail | `[x]` | M6 |
| M15 | Offline synchronization and idempotency | `[x]` | M12 |
| M16 | Public storefront, sharing, WhatsApp click-to-chat, QR | `[x]` | M9 |
| M17 | Reports, insights, low-stock alerts, notifications | `[x]` | M12 |
| M18 | Hardening, observability, deployment | `[ ]` | M16 |
| M19 | Web application bootstrap (Next.js) | `[ ]` | M16 |
| M20 | Mobile application bootstrap (React Native + Expo) | `[ ]` | M15 |

Deferred by design, not planned here: AI forecasting, community/network module,
supplier marketplace, fleet tracking, automated bank integrations, full WhatsApp
Business API, native desktop shell.

---

## M0 - Repository and developer tooling foundation

Goal: a developer can clone the repository, run one command, and get a green
build with enforceable architecture, secret scanning and dependency auditing.

Exit criteria: `make check` runs from a clean clone and fails the build on an
architecture violation, a committed secret, a non-ASCII engineering artifact, a
lint error and a failing test. CI runs the same command.

### M0.1 Repository skeleton and hygiene

- [x] M0.1.1 Root `.gitignore` covering Python, virtualenvs, env files, Node,
      Expo, build output, coverage and editor state. Committed with the backend
      scaffold so that no generated file can be staged accidentally.
- [x] M0.1.2 Root `README.md`: what AHIA is, the repository layout, the five
      layers in one table, the command index, and a pointer to the
      specification documents and this file.
- [x] M0.1.3 `.editorconfig` and `.gitattributes` so line endings, encoding and
      indentation are identical on every machine. UTF-8 without BOM, LF endings,
      which is what the ASCII guard expects.
- [x] M0.1.4 `docs/ARCHITECTURE.md`: the layer table mapped onto AHIA's
      directories, the allowed dependency arrows, the cross-cutting rules, the
      decisions already locked in the specification, and the decision log that
      future architectural changes append to.

### M0.2 Backend Python project

- [x] M0.2.1 `backend/pyproject.toml`: project metadata, `src` layout, pinned
      dependency floors, and tool configuration for ruff, mypy, pytest and
      coverage in one file.
- [x] M0.2.2 `backend/scripts/bootstrap_backend.sh`: creates `backend/.venv`,
      upgrades pip, installs the lockfile, installs the package in editable
      mode, and is safe to re-run.
- [x] M0.2.3 Lockfile: exact pins for runtime and development dependencies,
      generated by a resolver and committed. Re-generation is an explicit
      command, never an implicit side effect.
- [x] M0.2.4 Package skeleton: `backend/src/ahia/` with `__init__.py` exposing
      `__version__`, plus empty-but-real `models/entities`, `schemas`, `crud`,
      `services`, `routers`, `core`, `middleware`, `integrations/storage`,
      `integrations/whatsapp` packages, each with a docstring stating its layer
      responsibility.

### M0.3 Configuration contract

- [x] M0.3.1 `backend/.env.example`: every variable from
      `docs/PREREQUISITES.md` section 3 with placeholder values only, grouped by
      concern, with the secret values obviously fake.
- [x] M0.3.2 `.gitignore` coverage proof: a test that asserts `.env`,
      `.env.local` and key material patterns are ignored, so the guarantee is
      executable rather than aspirational.

### M0.4 Code hygiene enforcement

- [x] M0.4.1 `backend/scripts/check_ascii.py`: fails on emoji, box drawing,
      decorative symbols and any non-ASCII character in engineering artifacts,
      with a scoped, explicit allowlist for test fixtures that intentionally
      contain Unicode user data.
- [x] M0.4.2 Banned-identifier check: rejects `data`, `info`, `manager`,
      `helper`, `utils`, `common`, `misc`, `temp`, `tmp`, `process`, `handle`,
      `do`, `thing` as standalone module, class or file names, with the
      narrow exceptions the preset allows.
- [x] M0.4.3 Tests for both guards: a passing tree and planted violations that
      must be detected, so the guard cannot silently rot.

### M0.5 Architecture enforcement

- [x] M0.5.1 `backend/import-linter.ini`: layered contracts for entities,
      schemas, crud, services, routers, core, middleware and integrations,
      forbidding every outward import listed in the scaffold specification.
- [x] M0.5.2 `backend/tests/architecture/test_layer_contracts.py`: runs the
      contracts inside pytest so an architecture violation fails the ordinary
      test command, not only a separate tool invocation.

### M0.6 Secret and dependency scanning

- [x] M0.6.1 `gitleaks` installed into a workspace tool directory by a script
      that verifies a pinned checksum, since this workstation's system paths are
      read-only.
- [x] M0.6.2 `.gitleaks.toml`: default rule set plus an explicit allowlist for
      the placeholder values in `.env.example` and the local-only development
      password documented in `docs/PREREQUISITES.md`.
- [x] M0.6.3 `backend/scripts/scan_secrets.sh`: scans the working tree and,
      when asked, the full git history; exits non-zero on any finding.
- [x] M0.6.4 Dependency audit: `pip-audit` wired into the check command, with a
      committed ignore file for findings that have a documented, time-boxed
      justification.

### M0.7 Pre-commit hooks

- [x] M0.7.1 `backend/.pre-commit-config.yaml`: trailing whitespace, end of
      file, YAML/TOML validity, large file guard, private key guard, ruff,
      ASCII guard, architecture check and gitleaks.
- [x] M0.7.2 Hook installation and verification: install into the repository
      hooks directory and prove the hooks run by executing them against the
      tree.

### M0.8 One reproducible developer command

- [x] M0.8.1 `Makefile`: `setup`, `lint`, `format`, `typecheck`, `test`,
      `arch`, `secrets`, `audit`, `ascii`, `check`, `run`, `migrate`, `revision`
      targets, each a thin wrapper over a real script or tool with no hidden
      logic.
- [x] M0.8.2 `backend/scripts/dev_check.sh`: runs every gate in a fixed order,
      prints a plain-ASCII summary (`[OK]`, `[FAIL]`) and returns the correct
      exit code.

### M0.9 Continuous integration

- [x] M0.9.1 `.github/workflows/backend-check.yml`: PostgreSQL service
      container, Python 3.12, locked install, `make check`, with a critical
      dependency-audit finding failing the build.

### M0.10 Containers

- [x] M0.10.1 `backend/Dockerfile`: multi-stage build, non-root runtime user,
      no secrets in the image, `uvicorn ahia.main:app` as the process.
- [x] M0.10.2 `backend/.dockerignore`: excludes virtualenvs, tests, caches,
      env files and documentation from the build context.
- [x] M0.10.3 `backend/docker-compose.dev.yml`: local PostgreSQL service for a
      developer who prefers a container to a system database, with a named
      volume and a health check.

---

## M1 - Core cross-cutting infrastructure

Goal: every layer can depend on a typed, tested, injected core; no module reads
the environment directly and no module constructs its own clients.

Exit criteria: the application starts, answers `/health` and `/ready`, emits
structured logs with a correlation ID, redacts secrets, centralizes feature flag
declarations, exposes resilience primitives and a composition root, and every
core module has tests.

M1 also delivers the storage and media capability (M1.11 through M1.17), because
that is where the ports, the configuration and the composition root live. The
capability is provider-neutral: Cloudflare R2 and Cloudinary both implement one
storage port, the active provider is a configuration value, and no business
service branches on it. Media optimization and tenant quota enforcement are
server-side and configuration-driven, not provider features.

### M1.1 Configuration

- [x] M1.1.1 `core/config.py`: typed settings object built from environment
      variables, with validation, environment profiles (`development`, `test`,
      `production`) and no module-level mutable global.
- [x] M1.1.2 Feature flag registry in `core/config.py`: name, type, default,
      description, date added and removal condition for each flag declared in
      `docs/PREREQUISITES.md` section 4.
- [x] M1.1.3 Startup flag logging: exactly one INFO line per flag at
      application start, and a check that no security control is flag-gated.
- [x] M1.1.4 Tests: missing required variable fails loudly, defaults are safe,
      production rejects console log format and disabled TLS, and the flag
      registry is internally consistent.

### M1.2 Error architecture

- [x] M1.2.1 `core/errors.py` base hierarchy: one root error, layer-tagged
      subclasses (`EntityError`, `SchemaError`, `PersistenceError`,
      `DomainError`, `TransportError`, `IntegrationError`), and the typed
      `NotFoundError`, `ConflictError`, `AuthorizationError`,
      `AuthenticationError`, `ValidationError`, `DependencyUnavailableError`.
- [x] M1.2.2 Correlation ID: context variable, generator, inbound validation
      rules (length, character set) and accessor used by every layer.
- [x] M1.2.3 External envelope mapping: one table from error type to HTTP
      status, external code and safe message. Internal detail never crosses.
- [x] M1.2.4 Tests: internal errors carry operation, entity, identifier, layer,
      correlation ID and cause chain; external payloads contain exactly the
      code, safe message and correlation ID; a leak test asserts that no stack
      trace, SQL fragment, path, hostname or dependency exception appears.

### M1.3 Structured logging

- [x] M1.3.1 `core/logging.py` JSON formatter: timestamp, level, logger,
      correlation ID, operation, layer, and safe identifiers.
- [x] M1.3.2 Redaction: passwords, hashes, tokens, API keys, authorization
      headers, cookies and configured secret fields are redacted by the logger
      itself, not by call sites.
- [x] M1.3.3 Request-scoped logger: a bound adapter that carries correlation ID,
      tenant, actor and device without callers repeating them.
- [x] M1.3.4 Tests: redaction of nested and case-varied keys, correlation ID
      presence in every record, and no secret ever appearing in a formatted
      record.

### M1.4 Resilience primitives

- [x] M1.4.1 Timeout wrapper for outbound calls, with a typed timeout error.
- [x] M1.4.2 Circuit breaker: closed, open and half-open states; failure
      threshold, reset window and probe count from configuration; one breaker
      per dependency; state transitions emit a metric and a structured log.
- [x] M1.4.3 Bulkhead: per-dependency concurrency limit and queue behavior.
- [x] M1.4.4 Retry policy: bounded attempts, exponential backoff with jitter,
      idempotency guard that refuses to retry a non-idempotent operation.
- [x] M1.4.5 Fallback contract: a typed degraded result, never `None`, never a
      silent success.
- [x] M1.4.6 Tests: breaker trips and recovers, retries are bounded and
      jittered, timeout fires, bulkhead rejects past the limit, fallback is
      typed, and no breaker exists around in-process calls.

### M1.5 Security primitives

- [x] M1.5.1 Argon2id password hashing and verification with configured cost
      parameters and constant-time comparison.
- [x] M1.5.2 JWT access token encode and decode with issuer, audience,
      expiry, algorithm allowlist and clock-skew handling.
- [x] M1.5.3 Refresh token generation, hashing with a pepper, and constant-time
      verification; cryptographically secure public token generator.
- [x] M1.5.4 Tests: wrong password, unknown user timing behavior, expired,
      tampered, wrong-issuer and wrong-audience tokens are all rejected.

### M1.6 Database lifecycle

- [x] M1.6.1 `core/database.py`: async engine and session factory built from
      configuration, with pool size, overflow, pool timeout, statement timeout
      and TLS enforcement.
- [x] M1.6.2 Session dependency: one session per request, committed or rolled
      back exactly once, closed on exit.
- [x] M1.6.3 Unit of work port and SQLAlchemy implementation: services declare
      transactional intent without importing a database driver.
- [x] M1.6.4 Declarative base with a naming convention for constraints and
      indexes so Alembic autogenerate produces stable, reviewable names.
- [x] M1.6.5 Tests: engine configuration reflects settings, sessions do not
      leak, rollback on error, and the unit of work commits once.

### M1.7 Tenant context and authorization policy

- [x] M1.7.1 `core/tenant_context.py`: immutable context carrying user,
      tenant, membership, role, permissions and device, with explicit
      helpers that make the difference between "requested tenant" and
      "authorized tenant" obvious.
- [x] M1.7.2 Permission registry: one module per domain
      (`product_permissions`, `inventory_permissions`, `sales_permissions`,
      `customer_permissions`, `expense_permissions`, `storefront_permissions`,
      `staff_permissions`, `report_permissions`) plus `permissions_registry`
      exposing the full code set and the system role bundles.
- [x] M1.7.3 `require_permission` policy: deny-by-default, checks against the
      authorized context only, logs every decision with principal, tenant,
      resource, action and outcome, and fails closed when the permission set
      cannot be resolved.
- [x] M1.7.4 Tests: missing permission denies, unrelated role denies, owner
      bundle allows configured codes, and every decision produces a log record.

### M1.8 Composition root

- [x] M1.8.1 `core/container.py`: constructs configuration, engine, session
      factory, unit of work, repositories, services, integrations and
      resilience policies in one place.
- [x] M1.8.2 Lifespan resource management: create on startup, dispose on
      shutdown, expose readiness state, and fail startup loudly if a required
      resource is unavailable.
- [x] M1.8.3 Tests: container builds in test profile, no module-level
      singleton state, resources are disposed, and a missing dependency fails
      at startup rather than at first request.

### M1.9 Middleware

- [x] M1.9.1 `middleware/correlation_middleware.py`: read or generate the
      correlation ID, validate inbound format, expose it on the request state
      and the response, and bind it into the logger.
- [x] M1.9.2 `middleware/security_headers_middleware.py`: HSTS, CSP,
      `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` on every
      response, including error responses.
- [x] M1.9.3 `middleware/rate_limit_middleware.py`: per-identity and per-route
      limits for authentication, password reset, writes and expensive
      endpoints; never disabled by a flag; returns a typed 429 through the
      standard envelope.
- [x] M1.9.4 `middleware/error_handler_middleware.py`: one place mapping typed
      errors to status and envelope, logging full internal context, returning
      nothing internal to the client, and handling unexpected exceptions
      without leaking.
- [x] M1.9.5 Tests: header presence on success and failure, correlation ID
      round trip, rate limit trips and recovers, and error mapping for every
      typed error.

### M1.10 Application assembly

- [x] M1.10.1 `main.py` app factory: settings, container, middleware
      registration, router registration under `/api/v1`, exception handlers.
- [x] M1.10.2 Lifespan wiring: startup logging of environment, version and
      flags; clean shutdown.
- [x] M1.10.3 Health endpoints: `GET /health` for liveness and `GET /ready`
      for critical dependency readiness, exposing no internals.
- [x] M1.10.4 Tests: app imports without side effects, health and ready
      answer, unknown route returns the standard error envelope, and no
      configuration is read outside `core/config.py` (enforced by an AST test).

### M1.11 Storage port and provider configuration

- [x] M1.11.1 `core/ports/storage_port.py`: the provider-neutral capability.
      Operations AHIA actually needs - upload, delete, exists, delivery URL,
      image upload - over provider-neutral value objects carrying storage key,
      delivery reference, MIME type, size in bytes, width, height and checksum.
      No Cloudinary public identifier and no bucket name appears in the
      contract.
- [x] M1.11.2 Storage configuration in `core/config.py`: `STORAGE_PROVIDER`
      (`r2` or `cloudinary`), the shared media limits, the per-tenant quota, and
      the provider-specific credential blocks. Credentials for the inactive
      provider are neither required nor validated, and an unsupported provider
      value fails startup with a message naming the accepted values.
- [x] M1.11.3 Tests: both providers selectable from configuration, unknown
      provider rejected, inactive provider credentials absent without error,
      active provider credentials missing fails loudly, and no provider secret
      ever appears in a configuration representation or a log record.

### M1.12 Media processing capability

- [x] M1.12.1 `core/ports/media_port.py`: the provider-neutral processing
      capability - inspect and optimize - returning the processed bytes, the
      detected MIME type, the final dimensions, the byte size and a checksum.
- [x] M1.12.2 `integrations/media/image_processor.py`: server-side validation
      and optimization. Rejects a content type outside the allowlist, rejects a
      declared type that does not match the decoded image, rejects an oversized
      byte length, rejects a decompression bomb, resizes images larger than the
      configured maximum without ever upscaling, re-encodes to the configured
      target format at the configured quality, and strips EXIF, GPS and device
      metadata.
- [x] M1.12.3 Startup validation that the configured target encoder is actually
      available in the runtime. A configuration that cannot be honoured fails
      loudly rather than silently producing a different format.
- [x] M1.12.4 Tests: oversized bytes rejected, oversized dimensions resized to
      the configured bound with the aspect ratio preserved, small images never
      upscaled, disallowed content types rejected, a file whose bytes disagree
      with its declared type rejected, metadata absent from the output, output
      format honoured, and the byte size measured after processing is the size
      used for quota accounting.

### M1.13 Cloudflare R2 adapter

- [x] M1.13.1 `integrations/storage/r2_client.py` implementing the storage
      port against the S3-compatible API, with the object key constructed from
      server-side identifiers under the documented
      `tenants/{tenant_id}/...` hierarchy.
- [x] M1.13.2 Resilience at the outbound boundary: explicit timeout, a circuit
      breaker dedicated to R2, a concurrency bulkhead, bounded retry for
      idempotent operations only, a typed degraded result, and observability on
      breaker state change.
- [x] M1.13.3 Delivery URL construction: public base URL when configured,
      short-lived signed URL otherwise, never a permanent public URL for a
      private asset.
- [x] M1.13.4 Tests against a stubbed S3 client: upload returns
      provider-neutral metadata, delete is idempotent, exists reports correctly,
      a provider failure produces a typed application error and not a raw
      provider exception, and the breaker opens and recovers.

### M1.14 Cloudinary adapter

- [x] M1.14.1 `integrations/storage/cloudinary_client.py` implementing the same
      port, translating the neutral storage key to a Cloudinary public ID
      entirely inside the adapter and translating Cloudinary errors to the
      shared error hierarchy.
- [x] M1.14.2 `core/ports/storage_port.py` delivery contract extended so a
      provider may honour a requested presentation width. The Cloudinary
      adapter encodes that as a transformation; the R2 adapter returns the
      stored object. Services pass a width, not a transformation.
- [x] M1.14.3 Same resilience policy and the same error translation as the R2
      adapter.
- [x] M1.14.4 Tests: the shared contract suite passes for Cloudinary, a
      Cloudinary failure produces a typed application error, and no Cloudinary
      identifier or transformation string appears outside the adapter.

### M1.15 Storage factory and composition wiring

- [x] M1.15.1 `integrations/storage/storage_factory.py`: builds the adapter for
      the configured provider. The selection is the only place in the codebase
      that branches on the provider value.
- [x] M1.15.2 Composition root wiring: the storage capability, the media
      processing capability and their resilience policies are constructed once
      and injected where needed.
- [x] M1.15.3 Tests: switching `STORAGE_PROVIDER` returns a different adapter
      type with no change to any service, the factory rejects an unknown
      provider, and no service module imports a provider adapter (asserted by
      the architecture contracts, not by convention).

### M1.16 Storage contract test suite

- [x] M1.16.1 One shared, provider-agnostic behavioural suite executed against
      both adapters, so a divergence between providers is a test failure rather
      than a production surprise.
- [x] M1.16.2 Security assertions: another tenant's storage key is never
      reachable through the port's public operations, and a storage failure
      surfaces as a safe external error with the internal detail confined to the
      log.

### M1.17 Tenant storage quota accounting

- [x] M1.17.1 `tenant_storage_usage` entity and persistence: bytes used, a
      monotonic version and an update timestamp, one row per tenant.
- [x] M1.17.2 `services/storage_quota_service.py`: reserve, commit and release
      operations that are safe under concurrency. Reservation takes a row lock
      so two simultaneous uploads from two devices cannot both pass the check
      and over-allocate.
- [x] M1.17.3 Quota policy: the ceiling is configuration, the check happens
      before the bytes are persisted, and the accounting is updated only after
      successful persistence. A failed upload releases its reservation.
- [x] M1.17.4 Tests: a reservation that would exceed the quota is rejected with
      a typed error, concurrent reservations cannot both succeed when only one
      fits, a failed upload releases the reservation, and the accounting
      converges to the real stored total.

---

## M2 - User demonstrative vertical slice

Goal: prove the architecture end to end with one real entity before multiplying
it, including `GET /api/v1/users/me`.

Exit criteria: an authenticated request flows transport to service to
persistence to entity and back, with a correlation ID, typed error handling and
layer-appropriate tests.

### M2.1 Entity

- [x] M2.1.1 `models/entities/user_model.py`: frozen domain object with
      identity, contact, name, lifecycle fields and domain invariants
      (identifier stability, at least one contact channel, normalized phone,
      active-state transitions). No framework import.
- [x] M2.1.2 Entity tests: construction invariants, normalization, equality,
      immutability, and rejection of invalid values.

### M2.2 Schema

- [x] M2.2.1 `schemas/user_schema.py`: `UserCreateSchema`,
      `UserUpdateSchema`, `UserResponseSchema` with allowlist validation,
      field length limits and explicit serialization rules. No business rules.
- [x] M2.2.2 Schema tests: valid input, missing fields, oversized input,
      malformed email and phone, unknown field rejection, and response shape.

### M2.3 Persistence

- [x] M2.3.1 `crud/user_crud.py`: SQLAlchemy record owning the `users` table,
      the row-to-entity mapper, and `get_by_id`, `get_by_email`,
      `get_by_phone`, `create`, `update`, `deactivate`. Returns entities, never
      records.
- [x] M2.3.2 CRUD tests: mapping both directions, unique constraint behavior,
      tenant-independent lookups by identity, and no business decisions in the
      file.

### M2.4 Service

- [x] M2.4.1 `services/user_service.py`: `get_authenticated_user`,
      `update_user_profile`, `deactivate_user` with authorization checks at the
      service layer, unit-of-work usage, and structured logging with
      correlation ID.
- [x] M2.4.2 Service tests with the CRUD layer mocked: authorization denial,
      not-found mapping, successful profile update, and audit logging.

### M2.5 Transport

- [x] M2.5.1 `routers/user_router.py`: `GET /api/v1/users/me` and
      `PATCH /api/v1/users/me`, both parse, call one service method and return
      a schema. No branching beyond dependency wiring.
- [x] M2.5.2 Router tests with the service mocked: response shape, status
      codes, unauthenticated access, and confirmation that the handler performs
      no business logic.

### M2.6 Wiring and smoke

- [x] M2.6.1 Wire the User slice into the composition root and register the
      router; add a smoke test that starts the application against the test
      database.
- [x] M2.6.2 `docs/` endpoint reference for the slice, including the error
      envelope and the correlation ID header.

### M2.7 Cross-cutting verification

- [x] M2.7.1 Security test: the external error response for a failed request
      contains no stack trace, SQL, path, hostname or dependency name.
- [x] M2.7.2 Architecture test additions for the new modules, and a
      confirmation run of `make check` recorded in the commit message.

---

## M3 - Authentication and sessions

Goal: real identity. Email/password registration and login, short-lived access
tokens, rotating refresh tokens, logout, and rate limiting on every credential
endpoint.

- [x] M3.1.1 `SessionModel` entity and `session_crud.py` persistence for
      refresh token hashes, device binding, expiry and revocation.
- [x] M3.1.2 `auth_schema.py` request and response contracts.
- [x] M3.1.3 `auth_service.py`: `register_user`, `authenticate_user`,
      `refresh_session`, `revoke_session`, `change_password` with constant-time
      failure behavior and identical external errors for unknown user and wrong
      password.
- [x] M3.1.4 `auth_router.py`: `POST /api/v1/auth/register`,
      `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh`,
      `POST /api/v1/auth/logout` with strict rate limits.
- [x] M3.1.5 Authentication dependency: bearer token to authenticated
      principal, denying malformed, expired, wrong-issuer and wrong-audience
      tokens with a single external message.
- [x] M3.1.6 Tests: registration, duplicate registration policy, login
      success and failure, refresh rotation and reuse detection, logout
      revocation, rate limit behavior, and no-existence-disclosure.
- [x] M3.1.7 Security tests: token tampering, algorithm confusion, replay of a
      rotated refresh token, and credential stuffing throttling.

M3 exit criteria: a client can register, log in, call `/users/me`, refresh and
log out; every credential endpoint is rate limited; no response reveals whether
an account exists.

---

## M4 - Tenant slice

Goal: a business exists as a tenant with a globally unique public slug.

- [x] M4.1.1 `tenant_model.py` with slug invariants and lifecycle rules.
- [x] M4.1.2 `tenant_schema.py` with slug format validation and reserved-word
      rejection.
- [x] M4.1.3 `tenant_crud.py`: persistence with global slug uniqueness.
- [x] M4.1.4 `tenant_service.py`: `create_tenant`, `update_tenant_profile`,
      `get_tenant`, `deactivate_tenant`, with slug allocation and conflict
      handling.
- [x] M4.1.5 `tenant_router.py`: `POST /api/v1/tenants`, `GET /api/v1/tenants`,
      `GET /api/v1/tenants/{tenant_id}`, `PATCH /api/v1/tenants/{tenant_id}`.
- [x] M4.1.6 Tests: slug collisions, reserved slugs, cross-tenant access
      denial, tenant list scoping to memberships.
- [x] M4.1.7 Tenant-context resolution: requested tenant is a hint, membership
      is the proof; denial is deny-by-default.

---

## M5 - Membership and staff administration

- [x] M5.1.1 `tenant_membership_model.py` with status lifecycle (`invited`,
      `active`, `suspended`, `removed`) and uniqueness invariant.
- [x] M5.1.2 `tenant_membership_schema.py`.
- [x] M5.1.3 `tenant_membership_crud.py`.
- [x] M5.1.4 `tenant_membership_service.py`: `invite_tenant_member`,
      `activate_membership`, `change_member_role`, `suspend_member`,
      `remove_member`, each authorizing `staff.*` permissions.
- [x] M5.1.5 `tenant_membership_router.py` for the staff endpoints.
- [x] M5.1.6 Invitation token entity and flow that never requires an owner to
      share a password.
- [x] M5.1.7 Tests: last-owner protection, self-removal policy, duplicate
      membership, inactive membership denial, cross-tenant denial.

---

## M6 - Roles, permissions and authorization

- [x] M6.1.1 `permission_model.py`, `role_model.py`, `role_permission_model.py`
      as pure entities.
- [x] M6.1.2 Persistence for the three entities, one file each.
- [x] M6.1.3 Permission registry seeding: system permissions from
      `core/permissions/`, system roles (OWNER, MANAGER, SALES, INVENTORY) as
      permission bundles.
- [x] M6.1.4 `permission_service.py`: `resolve_permissions_for_membership`,
      `list_roles`, `list_permissions`, `update_role_permissions` with
      server-authoritative decisions.
- [x] M6.1.5 `role_service.py` and `permission_router.py`.
- [x] M6.1.6 Data migration/seeding path that installs the registry
      idempotently.
- [x] M6.1.7 Tests: role bundle correctness, permission escalation attempt,
      custom role behavior if enabled, and a cross-tenant role isolation test.

---

## M7 - Devices and session management

- [x] M7.1.1 `device_model.py` and persistence with
      `UNIQUE(tenant_id, device_identifier)`.
- [x] M7.1.2 Device registration and heartbeat endpoints.
- [x] M7.1.3 Device revocation: revoked devices are rejected by sync and by
      session validation.
- [x] M7.1.4 `device_service.py` and `device_router.py` wired to
      `staff.*`/`devices.*` permissions as appropriate.
- [x] M7.1.5 Tests: revoked device denied, unknown device denied, device cannot
      grant permissions, tenant scoping.

---

## M8 - Alembic migration baseline

- [x] M8.1.1 Alembic environment configured for async engine, settings-driven
      URL and naming conventions from the metadata base. The URL is never stored
      in `alembic.ini`; `alembic/env.py` reads it from application settings and
      imports every persistence module through `crud/table_registry.py` so
      autogenerate cannot propose dropping a table it never saw.
- [x] M8.1.2 Foundation migration: `users`, `user_sessions`, `tenants`,
      `tenant_memberships`, `membership_invitations`, `devices`, `permissions`,
      `roles`, `role_permissions`, `tenant_storage_usage`, with the indexes and
      constraints the database specification calls for. Seeding is deliberately
      absent: the permission registry is provisioning data, applied idempotently at
      startup, not migration data. Foreign keys on the pre-existing tables were
      declared in `crud/` first, so the migration reflects the models rather than
      inventing a schema of its own.
- [x] M8.1.3 Migration verification test in `tests/migrations/`: upgrade from an
      empty schema to head, downgrade to base, upgrade again, plus a no-drift
      assertion - an autogenerate comparison against the models must find nothing -
      and a check that `alembic.ini` holds no credential.
- [x] M8.1.4 DELIVERED IN M9, which is where it was deferred to. The composite keys
      arrived with the tables that need them: `products` references
      `categories(id, tenant_id)`, product images reference `products(id, tenant_id)`,
      and `products(id, tenant_id)` is the anchor the sales tables will reference in
      M12. Each is covered by a test that the database itself refuses a cross-tenant
      reference, and by a test that the anchor a key depends on is actually declared.

### M8 - progress log

- PostgreSQL refuses to create a foreign key to a table that was never imported,
  which is why `crud/table_registry.py` walks the package instead of relying on a
  hand-maintained import list: an omission there produces a migration that drops a
  table nobody meant to touch.
- The baseline was verified twice, and both verifications are tests rather than
  notes: the round trip (empty to head, head to base, base to head) and the drift
  check (`compare_metadata` against `Base.metadata` must return no differences).
- Foreign keys landed as their own change, with the fixtures that needed parent
  rows, because a foreign key is a schedule: the schema change and the test change
  have to arrive together or the suite is red in between.
- Reporting an integrity failure: the database reports duplicates, missing parent
  rows and check violations through one exception class. `crud/integrity_violations.py`
  classifies by SQLSTATE once, so a missing parent is a typed NotFoundError rather
  than a fabricated "already exists" - the previous message would have sent an
  operator looking for a duplicate that never existed.

---

## M9 - Catalog: categories, products, images, R2 storage

- [x] M9.1.1 `category_model.py`, `category_schema.py`, `category_crud.py`,
      `category_service.py`, `category_router.py`. Complete, with the table's own
      migration revision (`ab9af68b0824`) and tests at every layer. Categories are
      governed by `products.*`: the specification declares no `categories.*`
      permission, and inventing one would change what every existing role means.
      Deletion is deliberately absent - see the progress log.
- [x] M9.1.2 `product_model.py` with pricing and publication invariants,
      including the rule that money is never floating point. A float price is an
      invariant violation rather than a value to round, prices carry at most two
      decimal places, and deactivating a published product unpublishes it in the
      same transition.
- [x] M9.1.3 `product_schema.py` with price, slug and publication validation. A price
      is accepted as a JSON number or a decimal string and always returned as a decimal
      string, so no client passes money through a binary float. The slug, the tenant,
      the public token and the two lifecycle booleans are refused at the edge.
- [x] M9.1.4 `product_crud.py` with tenant-scoped uniqueness
      (`UNIQUE(tenant_id, slug)`, conditional SKU and barcode uniqueness). Both
      anchors are in place: `products(id, tenant_id)` for the tables that will
      reference products, and `categories(id, tenant_id)` so that a product's
      category reference is composite and a cross-tenant reference is refused by
      the database itself. This closes the item M8.1.4 deferred.
- [x] M9.1.5 `product_service.py`: `create_product`, `update_product`,
      `deactivate_product`, `publish_product`, `unpublish_product`, plus
      `activate_product`. Each use case takes exactly one catalogue permission:
      deactivation takes `products.delete`, which MANAGER does not hold, while
      reactivation takes `products.update`.
- [x] M9.1.6 `product_router.py` and `category_router.py`. Publication has its own
      endpoints rather than a boolean on the update contract, and DELETE withdraws a
      product from sale instead of deleting a row that sales will reference.
- [x] M9.1.7 `product_image_model.py`, `product_image_crud.py`,
      `product_image_schema.py`, `product_image_service.py`,
      `product_image_router.py`. The upload takes the raw request body rather than a
      multipart form, which is what a browser `fetch` sends natively and avoids a
      dependency that would exist only to unpack a form nobody needs.
- [x] M9.1.8 Storage and media capabilities: delivered in M1.11 through M1.17. M9
      consumes them through the port and never constructs a provider; the composition
      root is the only module that knows which adapter is active, and the architecture
      test over provider vocabulary keeps it that way.
- [x] M9.1.9 Server-side upload pipeline: authorize `products.update`, resolve the
      product in the tenant, check the per-product limit, decode and optimize through
      the media capability, reserve quota for the *optimized* size, upload through the
      storage capability under a server-built key, then persist the metadata and commit
      the reservation. Every failure path compensates: a provider that raises releases
      the reservation, a degraded result is a typed failure rather than an empty
      success, and a metadata write that fails deletes the object it had stored.
- [x] M9.1.10 Provider-neutral image metadata persistence: `storage_provider`,
      `storage_key`, `mime_type`, `size_bytes`, `width`, `height`,
      `checksum_sha256`, `sort_order`, `is_primary`, plus `removed_at` and
      `reconciliation_reason` so a failed provider delete stays findable. No column
      is named after a provider, and an architecture test now asserts that over the
      whole metadata: no table may have a column containing `r2`, `s3`, `bucket` or
      the other vendor's name.
- [x] M9.1.11 Product image limits: maximum count per product and maximum stored
      bytes per tenant, both configuration-driven, both enforced before persistence,
      with the error naming the limit that was hit. The per-product limit is checked
      before the server decodes anything, and the gallery count excludes removed
      images, so a business that removes one can add another.
- [x] M9.1.12 Deletion and replacement: removing an image deletes the stored object,
      drops the row and releases its bytes; a provider delete that fails leaves the row
      marked for reconciliation with the quota still committed, because the bytes are
      still there, and a reconciliation pass retries it and releases the bytes when it
      succeeds.
- [x] M9.1.13 Catalog migration and tests. Each catalogue table carries its own
      revision (categories, products, product_images), each verified against a live
      database and against the models by the drift check in `tests/migrations`.
      Cross-tenant product denial is asserted at the service and endpoint layers,
      cross-tenant image denial likewise, price precision at the entity, contract and
      persistence layers (including a Decimal round trip through NUMERIC(18,2)).
- [x] M9.1.14 Storage failure test: with the active provider unavailable,
      catalog reads and product writes still work and image upload returns a
      typed degraded result. Run against both providers through the shared
      contract suite.
- [x] M9.1.15 Provider switch test: switching `STORAGE_PROVIDER` changes the active
      adapter and leaves the pipeline untouched, and a row written before the switch
      still resolves to the provider holding its bytes. The composition root now builds
      an adapter for *every* provider whose credentials are configured, and the image
      service routes delivery URLs and deletions through the provider recorded on the
      row - asking the new provider to sign an old key would produce a link that does
      not resolve.

### M9 - progress log

- M9.1.13, M9.1.14 and M9.1.15 complete, which closes M9. The provider switch needed a
  real change rather than a test: the image service built every delivery URL with the
  *active* adapter, so after a switch an old row would have been signed against the new
  provider's bucket - a link that does not resolve, which a client can only report as a
  broken picture. The composition root now builds an adapter for every provider whose
  credentials are present (`build_storage_adapters`), and the service routes URLs and
  deletions by the `storage_provider` recorded on the row. A row whose provider is no
  longer configured gets no URL and a warning rather than a wrong one, and its deletion
  is refused in a way that leaves it marked for reconciliation instead of pretending it
  succeeded.
- Each provider also gets its own resilience policy, so an unhealthy endpoint on one
  cannot trip calls to the other - a breaker belongs to a dependency, and the two
  providers are two dependencies.
- Two layers refuse an active provider with no credentials, and both are tested: settings
  validation names the missing variables, and the registry refuses to start with no way
  to store anything even if a settings object bypassed validation. The second is defence
  in depth, tested with `model_construct` because that is the shape a future enum member
  would take.
- The storage-failure tests run for both provider names, because a deployment must
  notice an outage the same way whichever provider is active. The contract suite in
  `tests/integrations/test_storage_contract.py` proves the adapters themselves;
  `tests/services/test_storage_provider_switch.py` proves what the catalogue does when
  one is down: a typed failure, no row, and nothing charged.
- M9.1.7 and M9.1.8 complete. The upload endpoint takes the raw body: a browser sends a
  file that way natively, and multipart would exist only to carry a filename that is
  never used - the object key is built from server-side identifiers. The body is read
  with a ceiling *as it streams*, so an oversized upload is stopped while it arrives
  rather than after the server has already buffered it.
- A trap worth recording, because it cost time and will cost it again: `Settings` uses
  `extra="ignore"`, so a misspelled field name in a test's overrides is silently
  dropped. A limit test written with `max_images_per_product` (a `StorageLimits` field
  name) instead of `max_product_images_per_product` (the `Settings` field name) passed
  its setup and then never applied a limit. The override now names the real field, and
  the comment in that test file says why.
- M9.1.12 and M9.1.11 complete. Quota is released only when the provider confirms the
  object is gone; a failed delete keeps the bytes committed and the row marked, because
  releasing quota for storage that still exists would understate usage and let it grow
  with nobody watching. Reconciliation retries and releases on success, and never
  removes a row whose object it could not delete - the point of the pass is to reduce
  the leak, not to hide it.
- M9.1.9 complete, and it found a defect in its own first version: a provider that
  raises left the reservation held, because only the degraded-result path released it.
  A reservation nobody releases is quota the tenant paid for and cannot use until the
  stale-reservation reaper runs, so the failure path now releases it before re-raising.
  The test asserts both accounting columns, not only the committed one.
- The upload pipeline charges for the optimized size rather than the uploaded one, so a
  1.9-megapixel phone photo costs the tenant the 800x600 WebP that was actually stored.
  The media processor's decompression-bomb ceiling is what stops a deliberately huge
  upload, and a test shows it refusing one that would have blown past the configured
  area.
- Tests for the pipeline run against the real image processor and a recording storage
  double: the processor is real because its rules are the subject, and the double is a
  double because the object store is not - what is asserted is that the service calls it
  with a server-built key, once, and compensates when a later step fails.
- M9.1.10 complete, and the schema enforces two rules that a service could otherwise
  only promise. At most one primary image per product is a partial unique index, so two
  simultaneous requests cannot produce two covers; and "a removed image is never the
  primary one" is a check constraint, because the index predicate merely excludes
  removed rows rather than forbidding the flag on one - which a test discovered when it
  expected an update to be refused and it was not.
- The image table has no `(id, tenant_id)` anchor: nothing references an image yet, and
  a composite key no foreign key uses is complexity bought for a hypothetical. Its
  product reference *is* composite, so an image in one business cannot point at another
  business's product.
- M9.1.6 complete. The catalogue is now reachable end to end: a business can add
  products, edit them, file them under categories, publish them at a public address,
  withdraw them from the storefront and bring them back.
- M9.1.5 complete, and it found a defect worth recording. The entity promised that
  withdrawing a product and republishing it keeps the public address, and the service
  minted a fresh token on every publish - so a link already printed on a QR code would
  have stopped working after a pause in the listing. The fix keeps the existing token in
  the entity (so no caller can break an address by passing a new one) and only generates
  one when there is none. The test that caught it asserts the promise, not the
  implementation.
- M9.1.3 needed a correction after M9.1.6 exercised it: the response declared prices as
  `Decimal`, which reads well and is wrong, because FastAPI encodes a Decimal into a JSON
  *number*. The test that "proved" money leaves as a string asserted a Pydantic dump, and
  the framework sits between a Pydantic dump and an HTTP response. The fields are now
  declared `str` with an explicit conversion, the OpenAPI document advertises a string,
  and the endpoint test asserts the rendered JSON. The lesson is in the module docstring.
- M9.1.4 complete, and it closed M8.1.4. Writing the persistence test for "a product
  cannot reference another business's category" exposed that a plain foreign key does
  not express that rule at all: the category identifier is unique, so it is valid in
  every tenant. `categories` gained its `(id, tenant_id)` anchor and `products`
  references the pair, which is the specification's cross-tenant key pattern applied
  where it means something. The test failed first, then passed - the order that makes
  it evidence rather than decoration.
- M9.1.4 also settled where persistence tests live: `tests/crud/test_product_crud.py`,
  mirroring `src/ahia/crud/product_crud.py`. The device and category slices had put
  their persistence tests inside their model test modules, which is why the migration
  test's expected-table list is the only place that must be kept in step with a new
  table - and it failed loudly when it was not, which is how it should behave.
- A stale table definition cost time and is worth recording: `create_all(checkfirst=True)`
  never alters an existing table, so after the model changed the test database kept the
  old shape until the schema was rebuilt from migrations. A red test that passes alone
  and fails after another module is usually shared-state shape, not logic.
- M9.1.3 complete. The transport contract carries money as a decimal string in both
  directions, and refuses the slug, the tenant, the public token and the lifecycle.
- M9.1.2 complete. The product entity is where money lives, so it is the strictest
  entity in the codebase. A price arriving as a float is refused rather than rounded:
  `0.1 + 0.2 != 0.3`, and a shop that loses a kobo per sale is a shop whose books do
  not reconcile. A price with three decimal places is refused for the same reason -
  the column cannot hold it, and rounding silently would mean the price a person typed
  and the price that was stored are different. Zero is a legitimate price; negative is
  not. Selling below cost is allowed and merely reported, because clearing stock at a
  loss is a decision rather than a defect.
- Publication is a state with rules, not a flag: an inactive product cannot be
  published, deactivating a published product unpublishes it, and publishing twice
  keeps the token a customer's shared link already carries. A published product
  without a public token is rejected by the entity, so the state and the value that
  makes it reachable cannot drift apart.
- The composite uniqueness anchor `UNIQUE(id, tenant_id)` on products - the item M8.1.4
  deferred - arrives with the table in M9.1.4, because it is a constraint on a table
  rather than a rule about a product.
- M9.1.1 complete. The slice is the template the catalogue follows: entity, contract,
  persistence, use cases, routes, one migration revision, tests at each layer.
- Categories carry no permission of their own. The specification names `products.read`,
  `products.create`, `products.update` and `products.delete` and nothing else for the
  catalogue, so a category is created under `products.create`, read under
  `products.read` and edited under `products.update`. Adding `categories.*` would mean
  deciding which of OWNER, MANAGER, SALES and INVENTORY should hold it, and every role
  bundle in the registry would quietly change meaning.
- Creating and editing are refused before the database is touched, so a caller without
  the permission cannot use the uniqueness rule as an oracle for which category names
  are taken. A test asserts exactly that, because it is the kind of property that
  disappears in a refactor.
- Deletion is deliberately not implemented yet. A category has no `is_active` column in
  the specification, and what happens to a product whose category is removed is a
  question the products table answers: the foreign key from products to categories, and
  the rule for deleting a referenced category, arrive in the revision that creates
  products. Implementing deletion now would mean choosing an answer before the
  question exists.
- Each catalogue table arrives with its own migration revision rather than one
  revision for the whole milestone, because the drift check in tests/migrations
  compares the migrated database against the models: a model added without a revision
  fails the build, and that is the property worth keeping.

---

## M10 - Inventory ledger and projections

- [x] M10.1.1 `inventory_model.py` and `inventory_movement_model.py` as pure
      entities with the invariant `after = before + delta`, derived by the factory so
      a caller cannot supply three values that disagree, plus
      `negative_stock_policy.py` as the vocabulary the tenant stores.

### M10 - progress log

- M10.1.5 complete, which closes M10 apart from the milestone's own tests. The
  architecture contract caught a real violation on the first attempt: the inventory
  response schema imported the service's combined `InventoryLevel` view, so a schema
  depended on the layer above it. The schema now takes the product and the inventory as
  two entities and the router pairs them, which is what the contract asks for. That is
  the check doing its job rather than a test that had to be adjusted.
- The listing route had to be ordered deliberately: `GET /inventory/movements` is
  declared before `GET /inventory/{product_id}`, because FastAPI matches in registration
  order and would otherwise parse the literal word `movements` as a product identifier
  and answer 422. A test asserts the route works, which is what keeps the ordering from
  being tidied away later.
- The stock policy is its own operation on the tenant surface (`PUT
  /tenants/{id}/stock-policy`, requiring `tenants.manage`) rather than a profile field:
  a business that allows negative stock is changing what its own numbers mean.
- M10.1.3, M10.1.6 and M10.1.7 complete, which leaves only the transport layer for M10.
  The concurrency test is the one worth reading: two `asyncio.gather`ed transactions
  selling three and four of ten end at three, with both movements present and the ledger
  forming a single chain from the empty shelf to the current quantity. Without the row
  lock one sale would vanish from the projection while its movement stayed in the
  ledger - the ledger right, the screen wrong, and nothing to indicate which.
- A test assumption was corrected rather than worked around: an INVENTORY worker holds
  `inventory.adjust` as well as `inventory.stock_in`, so the useful contrast is with
  SALES, who can read stock and change nothing. The distinction the registry draws is
  between counting stock and selling it, and the ledger's actor column is what makes that
  distinction answerable afterwards.
- Movement timestamps are computed before the row lock, so two serialized writes can
  carry timestamps in the other order. Nothing depends on that ordering - the ledger's
  correctness is that the quantities connect - but a test that assumed timestamp order
  would have flaked, so the chain is walked by value.
- M10.1.1, M10.1.2 and M10.1.4 complete. The append-only rule is a trigger rather than a
  convention: `crud/inventory_movement_crud.py` has no update or delete function, and a
  unit test asserts that mechanically, but the database refuses both anyway - including
  from a psql session and from code that never read the docstring.
- Two test assumptions were wrong and both were corrected rather than worked around. A
  raw duplicate insert raises `IntegrityError`, not the `PersistenceError` the service
  path would raise, because `lock_for_product` deliberately tolerates a concurrent insert
  with `ON CONFLICT DO NOTHING`; and a raised trigger surfaces as `DBAPIError`, since
  asyncpg reports it as a generic database error rather than a programming mistake.
- The migration adds `tenants.negative_stock_policy` with a server default and then drops
  it: existing businesses are backfilled with the policy that refuses negative stock, and
  a future insert that forgets the column fails loudly instead of inheriting a policy
  nobody chose.

- [ ] M10.1.1 `inventory_model.py` and `inventory_movement_model.py` as pure
      entities with the invariant `after = before + delta`.
- [x] M10.1.2 Persistence for both, with the movement ledger append-only - enforced
      by a database trigger, not only by the absence of an update function, and with
      `operation_id` unique per tenant so a replayed offline operation is recognised
      rather than applied twice.
- [x] M10.1.3 `inventory_service.py`: `receive_stock`, `adjust_stock`,
      `record_damage`, `transfer_stock`, `get_inventory_for_product`,
      `list_movements`, each writing a movement and updating the projection in
      one transaction. Every operation ends in one private `_apply_movement`, so
      there is no second path that could change stock without a ledger entry.
- [x] M10.1.4 Negative-stock policy handling with an explicit tenant configuration
      point: `tenants.negative_stock_policy`, defaulting to `BLOCK_NEGATIVE_STOCK`,
      read back through the enum so a value this version does not know fails loudly
      rather than becoming the default.
- [x] M10.1.5 `inventory_schema.py` and `inventory_router.py`, plus the tenant's stock
      policy on the tenant surface. Quantities follow the money rule: accepted as a
      number or a decimal string, always returned as a decimal string, three places.
- [x] M10.1.6 Concurrency test: two concurrent offline sales produce two movements
      and a deterministic projection, run as genuinely concurrent transactions
      against real PostgreSQL using `asyncio.gather`. Two simultaneous overdraws with
      one item left are both refused and leave the stock untouched.
- [x] M10.1.7 Invariant test: a quantity cannot change without a movement. After five
      concurrent sales the movements sum exactly to the projection, and the movements
      form one chain of quantities - checked by value rather than by timestamp, because
      concurrent writes compute their timestamps before the row lock serializes them.

---

## M11 - Customers

### M11 - progress log

- The consent field is the one boolean this API parses strictly, and it is strict in both
  contracts rather than only in the update one - the first version made only the update
  field strict, and the schema test caught the create path still accepting `"yes"`.
- M11.1.1 and M11.1.4 complete, which closes M11 apart from its progress notes. Two
  behaviours were corrected while testing rather than after: a local phone number was
  being checked for plausibility *before* country completion, so `0803 123 4567` was
  stored as eleven digits that cannot be dialled from anywhere else; and Pydantic was
  coercing `"yes"` into `True` for the marketing consent field, which is the one field
  where guessing is least welcome. Consent is now parsed strictly, and a client that means
  yes sends `true`.
- The consent rule is enforced twice on purpose - the schema refuses a non-boolean, and the
  service's narrowing refuses it again - because consent is the field whose value has legal
  weight and a CLI caller never passes through the schema.
- M11.1.2 and M11.1.3 complete in the persistence layer. A phone number is indexed but
  not unique: a household shares one, and the specification asks for duplicate
  *detection*, not prevention. Refusing the second entry would push a shopkeeper into
  inventing a number to get past the constraint, which turns a duplicate into wrong data.
  Detection can exclude the customer being edited, so renaming somebody does not report
  them as their own duplicate.
- M11.1.1's entity is in, and consolidating the phone rule was part of it rather than a
  separate chore: `normalize_phone` lived on the user entity and country completion lived
  in the auth service, so a customer would have become a third place where "the same
  number" is decided. `models/entities/phone_number.py` now holds both halves - syntax in
  one function, country completion in another that takes the code as a parameter, because
  only a configured caller can choose a country. The user entity and the auth service both
  delegate to it, and the plausible-length bounds tightened to E.164's own (seven to
  fifteen digits), which is what the user entity already enforced.

- [x] M11.1.1 `customer_model.py`, `customer_schema.py`, `customer_crud.py`,
      `customer_service.py`, `customer_router.py`, plus
      `phone_number.py`: the phone rule was split between the user entity and the auth
      service, and a customer needs the same one, so it now lives in a single module the
      entity layer owns.
- [x] M11.1.2 Tenant scoping and privacy: every lookup in `customer_crud` takes a
      tenant and there is no function that can read one without it; the opt-in flag
      defaults to False; and `describe_for_audit` returns identifiers and booleans
      rather than the name, phone, email or address, asserted by a test that renders
      it and searches for the values.
- [x] M11.1.3 Customer notes and version metadata for sync-safe merging: a `version`
      column that every transition moves, and an update that can be checked against the
      version an offline client was working from, so two edits produce a typed conflict
      rather than one silently discarding the other.
- [x] M11.1.4 Tests: cross-tenant customer access denial (by identifier, listing,
      count and phone, at the persistence and endpoint layers), duplicate detection by
      phone within a tenant, and soft deactivation that preserves everything and is
      reversible. The sales-history half is asserted structurally: deactivation keeps
      every field and there is no delete function to call.

---

## M12 - Sales, payments, ledger, transactional integrity

### M12 - progress log

- M12.1.8 and M12.1.9 complete, which closes M12. The architecture contract caught the
  same mistake in the sale schema that it caught in the inventory one: a response mapper
  took the *service's* combined result, which makes a schema depend on the layer above it.
  It now takes the sale, its lines and its payments as entities and the router assembles
  both directions - and the contract test reported it in the same run rather than in
  review.
- The receipt prefix rule was wrong in a way only a real slug exposed: truncating
  `obi-electronics` to twelve characters produced `OBIELECTRONI-000001`, a fragment that is
  neither a word nor an abbreviation. The prefix is now the first word of the slug, so a
  receipt reads `OBI-000001`.
- M12.1.5, M12.1.6 and M12.1.10 complete, which leaves the transport layer and the
  permission tests for M12. The transactional property is tested by breaking it on purpose:
  a failure injected after the sale, its lines, its payments and its stock movement have all
  been written rolls back every one of them, and the receipt number the sale had claimed is
  reused by the next sale rather than becoming a gap in the book.
- Making that possible needed one refactor rather than a second implementation:
  `InventoryService` split "the stock rules" from "the transaction". `apply_stock_change`
  takes the session the caller is holding, so a sale commits its stock movements with
  everything else or rolls them back with everything else; the single-operation methods
  (`receive_stock` and friends) keep opening their own transaction and now call it.
- The naming rule caught `sales_service.py`: the entity is `sale_model.py`, and the
  exemption list is for use-case modules that genuinely have no entity - not for a plural
  that hides a slice. Renamed to `sale_service.py`.
- Two test assumptions were corrected rather than worked around: the receipt counter is
  rolled back with the failed sale, so the assertion that it had moved was backwards; and
  two ledger entries written in the same instant have no defined relative order, so that
  assertion compares a set while the cancellation test - whose entries differ in time -
  keeps its ordering.
- M12.1.4 and M12.1.7 complete. The receipt counter is a table rather than a PostgreSQL
  sequence because a sequence belongs to the schema and cannot be scoped: every business
  would share one counter, and a customer would watch their receipts jump by the number of
  sales other businesses made. Claiming the next number inside the sale's transaction also
  means a rolled-back sale releases it - the alternative, allocating from a separate
  transaction, would leave gaps that make a business think receipts went missing.
- The architecture check caught the counter's placement: `crud/receipt_counter_crud.py` had
  no entity behind it, and the fix was not an exemption but moving the reading rules -
  rendering and prefix sanitising - into `ReceiptCounterModel`, where domain vocabulary
  belongs, leaving the crud with the locking claim alone.
- Two test assumptions were corrected rather than worked around: a trigger refuses rows, so a
  DELETE on an empty ledger fires nothing and proves nothing; and a receipt prefix longer
  than the column is truncated rather than rendered whole.
- The money vocabulary moved out of the product entity first: a sale computes line totals,
  subtotals, payment sums and ledger amounts, and every one of those has to agree with the
  prices it is computed from. `models/entities/money.py` now holds the decimal places, the
  bounds, the wire parser and one rounding rule - half-up, stated rather than inferred,
  because Python's default would turn 0.005 into 0.00 and lose a kobo on every line.
- Three ordering defects in the new entities were found by their own tests and fixed at the
  cause rather than in the assertions: a discount larger than its line was reported as "the
  line total is below zero", which is true and tells the caller nothing; the same for a
  discount larger than a subtotal; and a payment reference of only spaces was refused as
  empty instead of being stored as absent. The checks now run shape first, then the rule
  that relates the parts, then the bounds on the derived value.

- [x] M12.1.1 `sale_model.py`, `sale_item_model.py` with snapshot fields and
      monetary invariants: a line total is derived and checked, the names and prices are
      snapshots taken at the sale, and cancellation is a status with a reason and a
      timestamp rather than a deletion.
- [x] M12.1.2 `payment_model.py` with method and status enums: only the methods the
      product can actually accept, a strictly positive amount, and a refund that keeps
      the amount and records when it happened.
- [x] M12.1.3 `ledger_entry_model.py` as an append-only derived record: a positive
      amount with an explicit direction, a reference that must name what caused the
      entry, and a direction derived from the entry type so revenue cannot be filed as a
      debit.
- [x] M12.1.4 Persistence for all four entities, one file each, no cross-entity
      joins. The ledger carries a database trigger refusing UPDATE and DELETE, exactly
      as the stock ledger does, and a test asserts the module offers no mutating
      function either.
- [x] M12.1.5 `sale_service.py` (named for its entity, `sale_model.py`, rather than for
      the domain area: the naming rule is what makes a slice predictable, and a plural
      here would have needed an exemption to hide the drift): `complete_sale` inside a
      single transaction
      creating sale, items, payments, inventory movements, inventory projection
      updates, ledger entry and audit event; failure of any part rolls back all.
- [x] M12.1.6 `cancel_sale` with compensating inventory and financial events, never a
      deletion: the stock returns as a `RETURN` movement, each payment is marked
      refunded, the ledger records a refund, and the sale keeps its number, its lines
      and its total. Cancelling twice moves nothing twice.
- [x] M12.1.7 Receipt numbering per tenant with a uniqueness guarantee: one counter
      row per business, claimed under a row lock inside the sale's transaction, with
      `UNIQUE(tenant_id, receipt_number)` behind it. A rolled-back sale releases its
      number, so a number nobody printed is not a gap in the book.
- [x] M12.1.8 Sales schemas and router endpoints: one request records a whole sale
      (its lines and payments together, because they are one transaction), money leaves
      as decimal strings, a replay is a 201 with `was_replayed`, and cancellation
      accepts a reason and nothing else.
- [x] M12.1.9 Tests: full transaction rollback on injected failure, no half-created
      sale, cancellation semantics, money precision, and permission enforcement
      (`sales.create` for recording, `sales.cancel` for cancelling) at the service layer
      and over HTTP.
- [x] M12.1.10 Idempotency at the operation level: replaying `operation_id` returns the
      original sale with its lines and payments, marked as a replay, and writes nothing -
      asserted by counting sales, movements and stock before and after.

---

## M13 - Expenses

- [x] M13.1.1 `expense_model.py`, `expense_schema.py`, `expense_crud.py`,
      `expense_service.py`, `expense_router.py`.
- [x] M13.1.2 Expense categories as configuration, not free text where
      reporting depends on them.
- [x] M13.1.3 Ledger entry creation for each expense.
- [x] M13.1.4 Tests: permission enforcement, no hard delete of financial
      history, tenant scoping.

### M13 - progress log

- M13.1.1 to M13.1.4 complete, which closes M13. Money leaving the business is now a
  record with a ledger entry behind it: `record_expense` writes the expense and the
  `EXPENSE` / `DEBIT` entry in one unit of work, and `reverse_expense` stamps when and why
  and appends the `ADJUSTMENT` that credits the money back while the original debit stays
  exactly as it was written.
- Two constraints autogenerate cannot infer are stated in the migration: `amount > 0`,
  because a spending report sums that column, and
  `(reversed_at IS NULL) = (reversal_reason IS NULL)`, because a reversal is a moment and a
  reason together. A follow-up autogenerate reports no drift, so the metadata and the
  schema agree.
- The categories are a closed set in `models/entities/expense_category.py`, published at
  `GET /expenses/categories` and in the OpenAPI document. A free-text category would give
  one business three transport totals and nobody could see that it happened. `OTHER` is the
  escape hatch and the description carries the detail.
- Reversal needs `expenses.create`, which only OWNER and MANAGER hold. The specification
  declares two expense permissions and inventing a third would put a code in the product
  that the product definition does not have.
- Three routes that do not exist are asserted over HTTP: `DELETE`, `PATCH` and `PUT` on an
  expense reach no handler. A mistaken expense is reversed, never erased.
- A defect found while running the migration is fixed in the same milestone: an empty
  `DATABASE_MIGRATION_URL` followed by an inline comment parsed as the comment text, and
  Alembic failed with "Could not parse SQLAlchemy URL". The comment now sits on its own
  line in `.env.example` and `.env`.

---

## M14 - Audit trail

- [x] M14.1.1 `audit_event_model.py` and append-only persistence.
- [x] M14.1.2 `audit_service.py`: `record_audit_event` and a query surface for
      owners.
- [x] M14.1.3 Audit writing wired into every mutating use case from M4 onward.
- [x] M14.1.4 Audit query endpoints restricted to `reports.read` or an
      equivalent owner-only permission.
- [x] M14.1.5 Tests: actor, tenant, device, operation, entity and timestamp
      captured; audit records cannot be updated or deleted through the API.

### M14 - progress log

- M14.1.1 to M14.1.5 complete, which closes M14. The service is named
  `audit_event_service.py` after its entity, and `AuditEventService` after the class
  convention; the architecture contract caught the first name.
- The trail is append-only in the database, not only by convention: a trigger refuses UPDATE
  and DELETE exactly as the stock and financial ledgers do, and a test exercises both refusals
  with raw SQL. `audit_event_crud` has no function that could attempt either, asserted
  mechanically against the source.
- Events are written inside the caller's transaction. `record_audit_event` takes the session
  the use case already holds and opens no unit of work of its own; a test writes an event,
  fails the transaction, and asserts the trail is empty afterwards. Eleven services are wired
  and five are documented exemptions, and a source-reading guard in
  `tests/architecture/test_audit_wiring.py` fails the build when a service that commits a
  transaction neither records an event nor appears in the exemption list.
- Where the trail stops is a decision, not an omission: authentication, account actions,
  registry provisioning and quota bookkeeping happen before a business is chosen or are
  derived from another use case. `audit_events.tenant_id` is required because the trail is a
  business's record, so a system-wide trail would need its own table and retention decision
  rather than a nullable tenant here. Each exempt module carries an `# Audit exemption:`
  comment, and a test requires it to be there and to be a reason rather than a word.
- `actor_id` and `device_id` are copies with no foreign key, found while wiring: an append-only
  table that referenced `users` would pin every actor row forever and make erasing a person's
  account impossible while the trail held events about them.
- Reading is `reports.read` - owner and manager - and there is no write route at all. `POST`,
  `PATCH` and `DELETE` on the trail reach no handler, asserted over HTTP, and the event is still
  there afterwards.

---

## M15 - Offline synchronization and idempotency

- [x] M15.1.1 `sync_operation_model.py` and `sync_cursor_model.py`.
- [x] M15.1.2 Change/outbox table with a monotonically increasing server
      sequence, written in the same transaction as the business change.
- [x] M15.1.3 `sync_service.py`: `push_operations` (authenticate, resolve
      tenant, check permission, check operation id, validate payload, execute
      transaction, return result) and `pull_changes` (cursor-based change feed).
- [x] M15.1.4 Conflict classification per the specification matrix: operation
      based for transactional facts, versioned/LWW for safe metadata,
      explicit conflict for high-value fields.
- [x] M15.1.5 `sync_schema.py` and `sync_router.py` gated by
      `FEATURE_OFFLINE_SYNC`.
- [ ] M15.1.6 Tests: duplicate operation deduplicated, out-of-order arrival,
      conflict classification, cursor monotonicity, revoked device rejection,
      and a resumption test after simulated interruption.
- [ ] M15.1.7 Synchronization diagnostics: tenant, user, device, operation,
      timestamp, request and result are all traceable without logging secrets.

---

## M16 - Public storefront, sharing, WhatsApp click-to-chat, QR

- [x] M16.1.1 `storefront_model.py`, `storefront_crud.py`,
      `storefront_service.py` with publish/unpublish lifecycle.
- [x] M16.1.2 Public slug resolution and public product projection that never
      exposes cost price, stock counts, staff or financial data.
- [x] M16.1.3 Public read endpoints: storefront, product detail, catalog
      listing, with no authentication required and rate limiting applied.
- [x] M16.1.4 Public share tokens for invoices, shipments and reports
      (non-guessable, revocable).
- [x] M16.1.5 WhatsApp click-to-chat adapter in
      `integrations/whatsapp/click_to_chat.py` producing prefilled, correctly
      encoded links, including Nigerian number normalization.
- [x] M16.1.6 QR payload builder encoding stable public URLs only.
- [x] M16.1.7 Tests: unpublished storefront inaccessible, no private field
      leaks in public projections, share token revocation, link encoding with
      special characters, and cross-tenant slug isolation.
- [x] M16.1.8 Feature flag `FEATURE_STOREFRONT_PUBLIC_PUBLISHING` wired and
      logged at startup.

---

### M16 - progress log

- M16.1.1 and M16.1.2 complete. The shop is a state on a row, not a second address: the public URL
  is `/shop/{tenant_slug}`, which the tenant already owns and which is already globally unique, and
  `storefronts` says only whether the shop answers and what it says about itself. A second slug
  would be a second address for the same shop.
- The public projection is an allowlist built in `storefront_service`: product slug, name, selling
  price, description, one image URL and a boolean availability. Cost price, the stock count, the
  internal identifier and the publication token are not filtered out of the response, they are
  never put into it - and a test asserts that each of them is absent from the object the service
  returns rather than only from the rendered JSON.
- Availability is a boolean rather than a count: "in stock" is what a customer needs to decide
  whether to make the trip, and how thin the shelf is is the business's own information.
- A slug that does not exist, a shop that was never opened, a shop that was withdrawn and a
  deactivated business all produce the same not-found answer, so a stranger cannot enumerate which
  businesses exist by watching the difference.
- Publication is wired into the audit trail like every other mutating use case. The storefront is
  deliberately not in the change feed: no client holds a shop offline, and a test asserts both
  halves of that.
- The release flag is injected as a boolean rather than read by the service, so the flag's
  meaning stays in `core/config` and the service has one behaviour to test. While it is off,
  publishing and public reads answer as if the capability did not exist.

- M16.1.4 complete for invoices. A share link stores a peppered digest rather than the token, so a
  leaked table yields no working links; the plaintext exists only in the response that mints it and
  in the link the business sends, which is also why a business that loses a link mints a new one
  rather than asking the server to re-show it. Shipments and reports are named in the specification
  but do not exist in this product yet, so `ShareableResource` holds only `invoice`: naming them now
  would let a caller mint a link to a record the server cannot serve.
- Revocation is permanent and the row stays, so "this invoice was shared and then withdrawn" is
  answerable. Expiry is a comparison rather than a flag, so nothing has to sweep the table for an
  expired link to stop working - and an unknown token, a revoked link, an expired link and a
  missing sale all produce the same not-found, so a holder cannot learn that a token was once real.
- The shared invoice is an allowlist: the business's name and contact number, the receipt number,
  the moment of the sale, its lines and its totals, and no customer name, customer phone number or
  internal identifier. The person holding an invoice link already knows who they are.

- M16.1.5 and M16.1.6 complete. `integrations/whatsapp/click_to_chat.py` builds a `wa.me` link with
  the inquiry already written and every character percent-encoded, and
  `integrations/qr/qr_payload.py` builds the string a QR code encodes from a public path and the
  configured base URL. Both are pure functions with no state.
- The number is normalized by the domain (`phone_number.international_digits_for`) and the adapter
  checks the dialling form it is handed: a second normalizer in an integration would be a second
  opinion about a trunk prefix, and the disagreement would surface as a call to the wrong number.
  A number that cannot be dialled produces no link and a typed reason, never a `wa.me` URL that opens
  an error screen.
- The adapters are reachable through `core/ports/sharing_port.py` and chosen in the composition
  root. Neither a service nor a router may import an integration - the layer contracts enforce it,
  and the first version of the share-sheet route broke that contract, which is how the port came to
  exist. The port names no provider, so it cannot acquire a `whatsapp_` parameter.
- `GET /tenants/{id}/products/{product_id}/share-sheet` returns the public URL, the QR payload and
  the messaging link in one response, because the three describe one intention and a client that
  fetched them separately would render a share sheet with a stale address. An unpublished product or
  a closed shop is refused with a message naming which of the two is missing.
- QR payloads are a closed set of public prefixes (`/shop/`, `/share/`): an admin path, a query
  string and a fragment are refused, because a printed code is read by a camera and shown to whoever
  is holding the phone.
- M16.1.7 is covered by the three suites of this milestone rather than by a separate file: the
  unpublished and withdrawn shop each have a test, the public projection is asserted field by field
  and end to end against a product that carries a cost price and a stock count, revocation is
  asserted together with the indistinguishable not-found, the encoding tests use an ampersand, a
  newline and a hash, and cross-tenant isolation is asserted for the shop, the shared invoice and the
  catalogue.
- M16.1.8 was already satisfied by M0's flag register and the startup log: the flag is declared with
  its default, its date and its removal condition, and the container logs every flag at startup.

## M17 - Reports, insights, low-stock alerts, notifications

- [x] M17.1.1 Daily sales summary query surface with tenant scoping.
- [x] M17.1.2 Product performance and low-stock reporting.
- [x] M17.1.3 Report export to R2 with a share token.
- [x] M17.1.4 Low-stock alert evaluation as a scheduled job entry point that
      reuses the service layer rather than duplicating rules.
- [x] M17.1.5 In-app notification records.
- [x] M17.1.6 Tests: report correctness against seeded data, permission
      enforcement (`reports.read`), and scheduled job idempotency.

---

### M17 - progress log

- M17.1.1 and M17.1.2 complete. `report_service.py` answers three questions - what the business sold
  day by day, what sold most, and what is running out - and the files are named after the use case
  rather than an entity, because a report owns no table. The architecture test's exception list now
  says so where a reader will find it.
- The arithmetic happens in the database: `sale_crud.daily_totals` and `sale_crud.completed_total`
  group inside the sales table, and the one report that needs two tables at once - what sold most -
  goes through `crud/sale_performance_read_model.py`. A read model rather than a repository, because
  an entity repository never joins: the rule exists so that a service is the only place that knows
  two entities, and a report is the case where the database should do the composing anyway.
- Cancelled sales are excluded from revenue and from what sold, while the sale, its lines, its
  payments and its ledger entries stay readable: the money came back, the story did not. A test sells
  twice, cancels one, and checks both halves.
- Low stock is a comparison in the service rather than a join: the threshold belongs to the product
  and the quantity to the stock projection. A threshold of zero is the default and reports a product
  when the shelf is empty, which is the alert nobody has to ask for, and the emptiest shelf is listed
  first.
- The period is by default the last seven days and at most ninety: a report is a screen, and a wider
  range is an export (M17.1.3). A period that ends before it starts is refused, and the bounds live
  in the service so a CLI or a scheduled job gets the same answer as an HTTP request.
- `reports.read` is enforced in the service. A test asserts a salesperson is refused on all three
  reports while a manager is allowed, and that another business sees zeros rather than another
  business's trading.

- M17.1.3 complete. An export writes a CSV, stores it under the business's prefix, records the
  artifact in `report_exports` and mints a share link in one call; `GET /share/report/{token}`
  redirects the holder to the provider's own short-lived delivery URL, so the bytes never travel
  through the application process. A failed upload is recorded with its reason and reported rather
  than raised: the artifact exists, its status says what happened, and a client can offer a retry.
- The CSV writer defuses formula injection. RFC 4180 quoting handles commas and quotes; it does not
  handle the spreadsheet, where a field beginning `=` or `+` is executed when the file is opened. A
  leading apostrophe is inserted and a test exports a product named `=cmd|'/C calc'!A1` to prove the
  raw formula never reaches the file.
- Exporting is in the audit trail with its own action and outcome, because it is the action that
  moves a business's numbers out of the product and "who exported what, and when" is asked after a
  file turns up somewhere it should not be. A failed export is recorded as `FAILED`.
- The export response carries the share link's identifier as well as its token, so a business can
  revoke the link it just created; the listing carries neither, because the server keeps a digest
  rather than a token and cannot re-show what it did not keep.
- `tests/storage_double.py` now holds the in-memory object store that the image suite and the export
  suite both use: it models the port's contract, including both failure shapes, so a suite can assert
  what happens when storage is unavailable without a network.

- M17.1.5 complete. `notifications` holds one row per message per person, addressed to a user in a
  business and read back through a query that takes the recipient as part of its lookup rather than
  checking afterwards - so no code path returns somebody else's inbox, and no permission code was
  invented to stand in for that. `read_at` records acknowledgement; nothing deletes a notification,
  because an inbox that empties itself cannot answer "was anybody told".
- M17.1.4 complete. `services/low_stock_alert_service.py` decides *when* to ask and *who* to tell, and
  `ReportService.low_stock_for_tenant` answers *what is low* by running the same comparison the report
  screen runs - so the product has one definition of "low" rather than two that drift. The dedupe key
  names the product and the day, which makes the job's frequency a cost decision rather than a
  correctness one: a second run in one day raises nothing and reports a skip.
- The job entry point is `python -m ahia.jobs.low_stock_alerts`. It prints an ASCII summary, takes no
  arguments, and exits non-zero when a business could not be evaluated or the run could not start - a
  scheduler that ignores a non-zero exit lets a broken job look healthy. It is the composition root
  for its own process, which is why it is in the architecture test's list of modules permitted to
  build settings; plain stdout is its contract, which is why `jobs/*` is exempt from the print rule
  in the same way the developer guards are.
- A failure in one business does not stop the run: the evaluator records it, reports it, and carries
  on, because a job that dies on the third tenant leaves the rest unevaluated and nobody knows.
- Only the roles that can act are told - the owner and the managers, the roles that hold
  `reports.read` - so a salesperson is not sent an alert about stock they cannot order.
- The change-feed vocabulary guard caught the two new recorded actions again (`share_report`,
  `export_report`) and they are now classified, which is the fourth time this milestone that guard
  has found something a commit message would have claimed was complete.
- M17.1.6 complete, which closes M17. The three subjects it names are asserted where they can be
  asserted honestly: report correctness against sales recorded through the API and against seeded
  stock, `reports.read` refusal and allowance for a salesperson and a manager, and job idempotency
  both end to end and at the service boundary. Two further claims that no response body can show are
  asserted directly - that the job and the report screen return the same rows for the same business,
  and that a business whose evaluation fails is reported while the others are still evaluated.

## M18 - Hardening, observability, deployment

- [x] M18.1.1 Rate limiting reviewed across every endpoint class; expensive
      and message-sending endpoints covered.
- [x] M18.1.2 Request duration, error count, authorization denial and breaker
      state metrics exposed in a form the platform can scrape.
- [x] M18.1.3 Row-Level Security enabled: twenty business-owned tables carry
      one policy of the same shape, forced on the table's owner; the unit of
      work binds the authorized business into each transaction; the public and
      job paths resolve first and read inside the scope. Verified per table as
      documented in `docs/RLS_ROLLOUT.md`, including what is *not* verified.
- [x] M18.1.4 Dependency audit gate confirmed to fail the build on a critical
      finding, with a deliberately planted test finding.
- [ ] M18.1.5 Northflank deployment configuration, health checks and secret
      wiring documented.
- [x] M18.1.6 Production runbook in `docs/RUNBOOK.md`: startup, migration
      order, rollback, the secret inventory with what each rotation
      invalidates, breaker trip response, correlation-ID troubleshooting, the
      Row-Level Security symptom, the scheduled job, and the incidents this
      system actually has.
- [x] M18.1.7 Load smoke test on the sale endpoint, recorded in
      `docs/LOAD_SMOKE.md`: 200 sales at 20 in flight, 25 sales/s with p95
      1.4s and no failures, on a two-core laptop with the database on the same
      host. The document states the environment, the three runs, what the
      numbers mean and what they do not cover.

---

### M18 - progress log

- M18.1.2 complete. `core/metrics.py` holds the registry and the renderer for the Prometheus text
  exposition format; it is *constructed* in the application and handed to the middleware, the error
  handler, the resilience policies and the container, so there is no module-level singleton and a test
  asserts that. Request count, duration total and maximum, error count by code, authorization denials
  by the use case that refused, and breaker state and short circuits are all recorded and rendered.
- Labels are bounded by construction: a path label has its UUIDs, long hex and integers replaced by a
  placeholder, so the series count depends on the API's shape rather than on traffic - a distinction
  that matters the day a client hits an endpoint a thousand times with a thousand identifiers. No
  correlation ID, tenant, user or query string reaches a label.
- `GET /metrics` is unversioned like the probes and is **not open by default**: it answers only when
  `METRICS_AUTH_TOKEN` is configured, and then only to a caller presenting it as a bearer token, with
  a constant-time comparison. Unconfigured, it answers as if it did not exist. The `.env.example`
  documents it, including how to rotate it.
- The breaker reports its state into the registry on every transition and on every short circuit, and
  reports its initial closed state, so a dashboard has a series before the first failure rather than
  after it. The error handler counts every failure by the code a client was told and every refusal by
  the use case, which is what an operator can act on.
- M18.1.1 complete, and the review is a test rather than a paragraph. Invitations now share the
  message-sending budget with password resets - both send a message to somebody who did not ask for it
  at that moment - and the bucket is named `MESSAGE_SENDING` for what it protects rather than after the
  first endpoint that needed it. `tests/middleware/test_rate_limit_coverage.py` walks every registered
  route and fails the build if a write route lands in the global bucket, if a named class has no
  routes, or if a bucket has no configured limit; it found that the route walker must follow included
  routers, because a top-level walk finds nothing and asserts nothing while passing.
- M18.1.4 complete. The gate's decision moved out of the shell into `scripts/audit_verdict.py`, which
  answers `clean`, `findings` or `tooling` and is tested apart from the shell - including the malformed
  report that must not be mistaken for a clean one. `PIP_AUDIT_BIN` lets the suite hand the gate a stub
  that reports a finding public since 2018, so the failure path is exercised offline and
  deterministically: the build goes red, the CVE is shown, and the way to suppress it is named.
- `docs/HARDENING.md` starts the operational documentation: the rate-limit classes and their limits,
  the metrics endpoint and how to rotate its token, the error-reporting split, and a section that
  states what is *not* yet in place so a reader is not left to discover it.

- M18.1.3's plan was written and committed first, and deliberately not enabled at that point. The plan
  states the mechanism (`SET LOCAL app.current_tenant` per transaction, one policy shape per table,
  failing closed because a missing setting makes `tenant_id = NULL` untrue), the order the tables are
  turned on in, what stays out of scope and why (`tenants`, because a public read resolves a slug
  before any scope exists; identity tables, because a person exists before a business does), the three
  assertions every step lands with, and the two-transaction shape the public and job paths need.
  Enabling RLS without the scope plumbing in place would return empty pages rather than errors, so the
  plan was the first half of the micro-milestone and the plumbing is the second.

- M18.1.3 is implemented and enabled. `core/tenant_scope.py` holds the business in a context variable,
  following the correlation-ID pattern; `SqlAlchemyUnitOfWork.__aenter__` writes it into the
  transaction with `set_config(..., true)`. `TenantService.resolve_tenant_context` binds it, which is
  the one place authorization is decided, so a route cannot be authorized and unscoped; the
  low-stock evaluator binds it per business inside `tenant_scope(...)`; the public shop and share-link
  reads were rewritten as resolve-then-read-within, in two transactions, because a public read starts
  before any business is known.
- The migration (`56912421e4aa`) creates one policy per business-owned table with the *same* predicate
  and forces it on the table's owner. Two corrections to the plan, both recorded in
  `docs/RLS_ROLLOUT.md`: the naive `current_setting('app.current_tenant', true)::uuid` is wrong,
  because PostgreSQL leaves the placeholder defined as an *empty string* after a `SET LOCAL`
  transaction commits, so the next request on that pooled connection would raise
  `invalid input syntax for type uuid: ""` rather than returning no rows - `nullif(..., '')` is what
  makes both cases mean "no scope"; and `share_links` moved out of scope, because a token has to be
  resolved before the business it belongs to is known. The three sync tables were added, since leaving
  them out would leave a hole of the same shape.
- The verification runs as an unprivileged probe role, because the ordinary test connection is a
  superuser locally and superusers bypass RLS regardless of `FORCE` - an assertion made as the owner
  would pass with no policy present at all. It covers the three per-table assertions on `customers`,
  `categories` and `ledger_entries`, a refused write outside a scope, the pooled-connection case, the
  application path failing closed through the unit of work, and structural assertions for all twenty
  scoped tables and all eleven excluded ones. What is *not* verified is listed in the same document
  rather than left to be assumed.

- M18.1.6 complete. `docs/RUNBOOK.md` is written against the code rather than from a template: the
  commands are the ones the Makefile runs, the production refusals are the ones `Settings` actually
  enforces (JSON logs, `DATABASE_REQUIRE_SSL=true`, no `DEBUG`, no wildcard CORS with credentials, the
  active storage provider's credentials, the secret-length minimums), the metric and log names are the
  ones the registry and the logger emit, and the incident table names the failures this system can
  really have.
- The two sections worth reading before an incident: the secret inventory, because rotating
  `REFRESH_TOKEN_PEPPER` invalidates every refresh token, every pending invitation *and* every share
  link - it is the one rotation that logs users out and breaks links at the same time; and the
  Row-Level Security section, because a wrong or missing scope produces a successful empty response
  rather than an error, which is the failure a runbook has to name explicitly or nobody will look for
  it.

- M18.1.7 complete. `scripts/load_smoke_sale.py` drives the real application over an in-process ASGI
  transport - the real middleware, authorization, service and database, without the network - and
  records 200 sales at 20 in flight. Three runs are recorded in `docs/LOAD_SMOKE.md` with the machine,
  the PostgreSQL settings and the pool configuration, because a throughput number without its
  environment is not a number anybody can compare against later.
- The shape the numbers show is the useful part: quadrupling concurrency from 5 to 20 left throughput
  flat at 25 to 28 sales/s while p50 latency grew five-fold, which is saturation rather than a slow
  path - and on this machine the saturated resource is the database, not the application. The script
  also reads the application's own request counter back and refuses to report a number if the server
  counted fewer requests than the client sent, and it exits non-zero on any failed request.
- What the document says the numbers do *not* cover: Row-Level Security (the local role is a
  superuser and bypasses the policies), storage calls, multi-instance behaviour, and anything lasting
  long enough to be a soak test.

## M19 - Web application bootstrap (Next.js)

- [x] M19.1.1 `web/` workspace with Next.js (App Router), TypeScript in strict
      mode, and a committed lockfile.
- [x] M19.1.2 Typed API client generated from the backend's OpenAPI document:
      `web/openapi.json` is the specification, `npm run api:types` generates
      `web/lib/api-schema.d.ts`, and `web/lib/api.ts` is written against it.
      Generating caught three real mismatches on the first run.
- [x] M19.1.3 Authentication flow against the real API: create an account and
      sign in from the console, with the access token held client-side and the
      correlation ID shown on every failure.
- [x] M19.1.4 Trader dashboard: today's money, the four actions (`+ Sale`,
      `+ Product`, `Stock In`, `Expense`), the shelf with stock pills, recent
      sales, what is running out, and a sheet per action.
- [x] M19.1.5 Public shopfront from the public API with metadata for sharing:
      `/shop/{slug}` and `/shop/{slug}/product/{productSlug}`, rendered on the
      server so a WhatsApp link unfurls with the shop and the product.
- [ ] M19.1.6 Client-side permission awareness that hides unavailable actions
      while never being the authority.
- [x] M19.1.7 End-to-end run in a real browser: create a product, record a
      sale, watch the inventory move, and open the public shop. Driven by
      scripts (`browser-check`, `mobile-check`, `shop-check`) rather than a test
      framework, so the evidence is a screenshot and a failing assertion.

### M19.2 - The account, the photos and the shop (added while building)

- [x] M19.2.1 Profile: name, phone, email, the business's own details
      (address, city, state, currency) and a password change, each verified by
      reading the value back from the API.
- [x] M19.2.2 Product photos: upload from the camera or the gallery, cover
      choice, removal, thumbnails on the shelf. Verified against the real
      Cloudinary account, which found a broken delivery URL that would have
      made every picture a broken image.
- [x] M19.2.3 Shop management: open, close, edit what it says, copy the link,
      share on WhatsApp, and show or hide each product.
- [x] M19.2.4 More than one business on one account, with the shelf cleared
      when switching so one shop's numbers never appear under another's name.
- [x] M19.2.5 Mobile: every screen fits 390x844, measured rather than eyeballed
      (`mobile-check` fails on a viewport overflow).
- [x] M19.2.6 Team: invite a salesperson, give them a role, see who has access,
      remove somebody. The invitation is a link the owner sends on WhatsApp, and
      `/join/{token}` is where it lands.
- [ ] M19.2.7 Shop visits: how many people opened the shop, and what they
      looked at. Needs backend work first - nothing records a view today.

---

## M20 - Mobile application bootstrap (React Native + Expo)

- [ ] M20.1.1 `mobile/` workspace with Expo, TypeScript, strict mode, and a
      committed lockfile.
- [ ] M20.1.2 Local SQLite schema and migrations mirroring the local entity
      list from the specification.
- [ ] M20.1.3 Operation queue with durable pending operations and retry
      bookkeeping.
- [ ] M20.1.4 Sync engine implementing push, pull, reconcile and conflict
      surfacing, with tests against the real API contract.
- [ ] M20.1.5 Optimistic UI states: local/pending, synced, failed, conflict.
- [ ] M20.1.6 Camera and QR scanning flows with offline lookup.
- [ ] M20.1.7 Native sharing and WhatsApp handoff.
- [ ] M20.1.8 Offline acceptance test: airplane mode sale, reconnect,
      synchronization, no duplicate, no data loss.

---

## Progress log

Completed milestones, with what is verifiably working.

**M0 - repository and developer tooling foundation (25 micro-milestones).**
Repository hygiene, the pinned dependency closure with two lockfiles (development
and runtime-only, both with hashes), the ASCII and banned-name guards, nine
architecture contracts run inside pytest, secret scanning with a
checksum-verified scanner install, dependency auditing with expiring ignores, the
pre-commit hooks, one `make check` gate, CI, and the container image.

**M1 - core cross-cutting infrastructure (55 micro-milestones).** Typed
configuration and the feature flag register; the error hierarchy with correlation
IDs and the external envelope; structured logging with infrastructure-level
redaction; outbound resilience primitives; password hashing and token issuance;
the database lifecycle and unit of work; the permission registry, tenant context
and deny-by-default authorization policy; the storage port with two adapters and
the factory; server-side media optimization; tenant storage quota accounting with
concurrency safety; the composition root; correlation, security header, rate
limit and error handling middleware; and the assembled application with liveness
and readiness endpoints.

Verification at the end of M1: 557 tests pass, of which the storage, quota and
database suites run against real PostgreSQL; the build gate passes all nine
stages; the service starts, answers `/health` and `/ready`, returns the standard
error envelope on an unknown route with the caller's correlation ID echoed, and
carries the security headers on every response.

**M2 - User demonstrative vertical slice (13 micro-milestones).** The template
every future entity copies, built through all five layers: a framework-free user
entity with its invariants, wire schemas with no credential-shaped field, one
CRUD file owning the table and the mapping, a service enforcing self-scoped
authorization, and three HTTP endpoints. `docs/API_USER_SLICE.md` is the contract.
Seven end-to-end tests run against real PostgreSQL with nothing mocked, including
a request whose database is unreachable asserting the response leaks no path,
driver, query or hostname.

**M3 - Authentication and sessions (7 micro-milestones).** Registration, sign-in,
refresh rotation, sign-out and password change, backed by a session entity that
stores only a peppered digest and keeps its rotation chain so reuse is detectable.
Sign-in answers identically for an unknown account, a wrong password and a
deactivated account, and performs the same work on every path so timing does not
answer what the body refuses to. Reusing a rotated token ends the entire session
family and logs a security incident. 21 end-to-end tests, again against real
PostgreSQL, real Argon2 and real JWTs.

Two defects were found by tests rather than by review, both fixed at the cause:
error responses were missing every security header because the middleware order
put the error handler outside them, and a locally written phone number did not
resolve to the same account as its international form, which is now canonicalised
through a configured country code.

**M4 - Tenant slice (7 micro-milestones).** Businesses: an entity whose public slug
cannot change, contracts that reject a slug edit outright, persistence with a
globally unique slug, a service whose creation writes the business and its owner
membership in one transaction, and endpoints under `/api/v1/tenants`. Tenant
context resolution landed here: the path identifier is a selection hint, membership
is the evidence, and a caller with no membership receives the same 404 a stranger
receives, so identifiers cannot be probed. 15 end-to-end tests.

**M5 - Membership and staff administration (6 micro-milestones).** The membership
entity with its lifecycle as declared data, an invitation entity whose token is
stored only as a digest, and the staff use cases: invite, list, change role,
suspend, reactivate, remove, plus acceptance for the invited person. The last-owner
rule is enforced in the service and proven at its boundary. 16 end-to-end tests
covering the whole onboarding journey and every way it must fail.

Ordering note, recorded rather than hidden: M5's entity and persistence were built
before M4's service, because a business created without its owner membership would
be unreachable, and the product's own first-run journey requires both in one
transaction. The task numbers are identifiers; the dependency direction is what the
work has to respect.

**M6 - Roles, permissions and authorization as data (6 micro-milestones).** The
declared registry is now provisioned into the database by an idempotent service that
converges rather than merely adding, so a grant removed from code is removed from the
database with a warning. Two sources of truth are only safe if they cannot drift, so
a check reports every difference and tests prove it is silent when they agree and
loud when they do not. Resolution is deny-by-default, and privilege escalation is
refused by a rule: a caller may not grant a permission they do not themselves hold.
The catalogue is readable by any active member, because a person cannot judge a role
they are being given without knowing what it means.

**M7 - Devices (5 micro-milestones).** An installation registers itself, renews its
identity through the same request, appears in the business's device list, and can be
revoked. A device never grants permission, which is asserted rather than commented.
Revocation marks the device revoked, ends every session bound to it and logs a
security event in one transaction: the first without the second would be theatre.
11 end-to-end tests including a lost-phone flow whose refresh token stops working.

---

## M21 - Waybill requests: the customer's list, and the price book

Goal: replace the paper list and the market run that follows it. A customer builds a list on a link,
without an account, and it lands with the trader tied to that customer. He sources it - some from his
shelf, some bought in the market that morning - packs it, ticks it off, and waybills it. The app does
the arithmetic and records what happened; it never argues with him.

This milestone exists because the product owner described the workflow he grew up inside, and it is the
first feature that sounds like the trade rather than like software. It is written down in full because
every detail here is a decision, not a preference.

### M21.1 The customer's list (no account, ever)

- [ ] M21.1.1 A public **"Make a waybill list"** entry on the storefront, beside the catalogue. The
      customer never signs up, never logs in, and never sees a password.
- [ ] M21.1.2 **Prices are visible** while they build the list. A customer who cannot see a price
      cannot send a sensible list, and hiding it just moves the question onto WhatsApp.
- [ ] M21.1.3 **Anything can be added, including what is not in the catalogue.** A free-text line with a
      note - "screenguard for iPhone 15, the matte one" - because in real life nothing stops a customer
      asking, and a list that cannot hold the request is a list that gets written on paper again.
- [ ] M21.1.4 **Phone number is collected, and the reason is said out loud**: "so we can keep track of
      whose list this is, and so you do not have to start again next time". Date and time are recorded
      automatically.
- [ ] M21.1.5 The list is **saved against that phone number**, so a returning customer opens the same
      link, sees what they ordered last time, and changes a quantity, edits a line, adds something new
      or repeats the whole thing. Never a blank page.
- [ ] M21.1.6 **No availability, no stock count, no "out of stock"** anywhere a customer can see. An
      Igbo trader is never truly out of stock - he goes and finds it - so the customer-facing side says
      "we will source it", not "we do not have it".

### M21.2 The trader's side: sourcing, packing, quoting

- [ ] M21.2.1 The request arrives in the app tied to the customer, with the list, the notes and the
      date. Push and in-app notification, since he is walking, not sitting.
- [ ] M21.2.2 **Market-run mode**: each line carries one of **have it / buy it / cannot get it**, and
      while buying, **what it cost him**. This is the thing paper cannot do: at the end he knows what he
      actually made on a mixed waybill.
- [ ] M21.2.3 **Packing and ticking**: lines tick off as they go in the carton, with an optional photo
      of the packed goods, visible to the customer as progress.
- [ ] M21.2.4 **The quote**: he sets the final price per line, or just a total, and adjusts however he
      wants - a flat amount off ("comot one thousand"), a percentage, or nothing at all. **No ceilings,
      no floors, no approval flow.** The app computes and records; it does not restrict.
- [ ] M21.2.5 **The adjustment is a line with a reason**, so a discount does not silently corrupt the
      margin. "Customer is my guy" is a perfectly good reason.
- [ ] M21.2.6 Owner-only visibility of costs and margins. A salesperson packs and ticks; he does not see
      what the goods cost or what was made on them.

### M21.3 The price book (why screenguards need more than a price field)

- [ ] M21.3.1 **Variants as a family with axes**, not a product per combination: `Screenguard` x grade
      (5D, 21D, privacy, ceramic) x phone model x colour, with a price matrix. Otherwise his catalogue is
      hundreds of near-identical rows nobody can find anything in.
- [ ] M21.3.2 **Layered pricing, each layer optional and each overridable**: grade default, then model
      override, then customer tier (retail or wholesale), then this customer's own price, then the line
      he types, then the final adjustment. The system suggests; he decides.
- [ ] M21.3.3 **Units as first-class**: piece, pack (x N), carton (x M). Stock counted in pieces, sold in
      packs, priced per pack. Screenguards are exactly this.
- [ ] M21.3.4 **Wholesale and retail as price tiers**, so a wholesale price cannot leak to a retail
      customer through a shared catalogue.
- [ ] M21.3.5 **A generated price list** (image or PDF) from the price book, to broadcast on WhatsApp.
      Most of his customers will never open a link before they know the prices.

### M21.4 The waybill itself

- [ ] M21.4.1 Waybill details captured at handover: transporter, phone, waybill number, cost. The
      customer gets a tracking link - the Tracking module in the specification starts life as these
      four fields.
- [ ] M21.4.2 The request becomes money only when he confirms it: no inventory movement, no ledger
      entry and no receipt until then. A list is a wish, not a sale.
- [ ] M21.4.3 Repeat business in one tap: the last order and the last prices for that customer,
      pre-filled.
- [ ] M21.4.4 **Credit, because most of this trade runs on it**: what a customer owes, since when, with
      a WhatsApp reminder he can edit before it is sent.

### M21.5 What stock counts are for

- [ ] M21.5.1 Availability, thresholds and counts are the **owner's view** - inventory management he can
      look at if he wants to. Most traders do not count stock, and the product must not require it.
      Stock movements record what happened; nobody is asked to reconcile a shelf they never counted.

### M21 - decisions from the product owner

- Prices **are** visible to the customer while they build the list.
- A customer **can add anything**, including items not in the catalogue, as a free-text line with a note.
- The **phone number is collected**, with the reason stated to the customer: so he knows whose list it
  is and so they do not start from nothing next time. Date and time are recorded too.
- A returning customer **reuses the saved list** and edits it rather than starting over.
- The entry point is the **storefront**: a "make a waybill list" action beside the catalogue.
- **No "out of stock" to customers, ever.** Stock figures are for the owner, and even then only if he
  wants them.
- The trader has **no limits** on what he can do to a price or a total. The app adds to him; it does not
  restrict him.

### M21 - open questions

- Does a request link live **forever** for a customer, or expire with a fresh one per order? (Leaning to
  a standing link per customer, because the same people order every week.)
- How much of the price matrix does he want to maintain himself versus inherit from a grade default?
- **OCR of the photographed paper list**: later, not now. A photo attached to the request is useful on
  day one; reading it is a separate promise to keep.

## Cross-milestone obligations

These apply continuously and are re-verified at each milestone boundary.

- [ ] Every new mutating use case writes an audit event (from M14 onward).
- [ ] Every new outbound dependency gets timeout, breaker, bulkhead, bounded
      retry, typed fallback and observability at the moment it is introduced.
- [ ] Every new endpoint is covered by the security test suite categories:
      authentication, authorization, tenant isolation, input validation.
- [ ] Every new feature flag carries a date added and a removal condition, and
      is logged at startup.
- [ ] `docs/PREREQUISITES.md` is updated whenever a new environment variable
      or provider is introduced.
- [ ] **Everything the product owner says goes in this file.** Not a summary at the end of a
      milestone: the decision, the wording, and the reason, added when it is said. This file is the
      record of what was asked for and what was understood, and it is the only place that survives.
- [ ] Any architectural decision that touches data ownership, multi-tenancy,
      synchronization, permissions, transactions, external dependencies or
      public/private boundaries is appended to `docs/ARCHITECTURE.md` decision
      log before implementation proceeds.

## M19 - progress log

- M19.1.1 to M19.1.3 complete, and M19.1.4 partly: the console at `http://localhost:3000` creates an
  account, opens a business, adds a product, stocks it and records a sale, with the quantity on hand
  moving from 10.000 to 9.000 as the sale lands. It was driven end to end in a real browser
  (`web/scripts/browser-check.mjs`, screenshots per step in `.review/`), not only in tests.
- The API types are generated from the backend's own `openapi.json` rather than hand-written, and
  generating them immediately found three places where a hand-written client would have been wrong:
  `/api/v1/auth/login` takes `identifier` rather than `email` (a trader types either a phone number or
  an address), a business carries its own `currency` and `timezone`, and a sale line carries its own
  `discount_amount`. That is the whole argument for generating them.
- Two backend-side findings from the first real run, both fixed in the application's own configuration
  rather than by weakening anything: `DATABASE_URL` carried `?sslmode=require&channel_binding=require`,
  which asyncpg rejects outright - TLS is now requested by `DATABASE_REQUIRE_SSL=true` and the query
  string is gone - and `CORS_ALLOWED_ORIGINS` listed only `localhost:3000`, so opening the app at
  `127.0.0.1:3000` produced a 400 on the preflight. Both hostnames are now allowed.

## M19 - progress log (continued)

- The session is a cookie now, not a token in JavaScript. `/auth/register`, `/auth/login` and
  `/auth/refresh` set `ahia_session` (HttpOnly, SameSite=Lax, `Secure` in production) and `ahia_refresh`
  (the same, scoped to `/api/v1/auth`), and `/auth/logout` clears both and revokes the session. Every
  layer above the token service accepts the cookie: `require_principal` reads the header first and the
  cookie second, so a browser, a script, the mobile client and the documentation all work without a
  call site remembering a header. SameSite=Lax is the CSRF control for state-changing requests, and it
  is why a cross-site form post arrives unauthenticated rather than authenticated as somebody else.
- Two faults the change exposed, both fixed rather than worked around. The web app called the API on
  `127.0.0.1:8000` from `localhost:3000` - a *different site*, so a Lax cookie is never attached and
  every request arrived signed out. `/api/...` is now proxied through the app's own origin, which also
  removes CORS and preflights from the picture entirely. And the CORS middleware sat inside the error
  handler, so a 401 or a 429 came back with no `Access-Control-Allow-Origin` header and the browser
  reported a CORS failure instead of the status the API had actually returned.
- The interactive documentation now shows the **Authorize** control: `require_principal` declares an
  `HTTPBearer` scheme, so a token is pasted once and used for every request in the docs. A browser does
  not need it, and the description says so.
- The connectivity check no longer hangs: the database connection had no connect timeout, so a
  suspended Neon compute held a request - and the pool slot, and the person - for as long as the driver
  would wait. It is now bounded by `DATABASE_POOL_TIMEOUT_SECONDS`, which is what turned "the app is
  broken" into "the database is waking up". Every API call in the web app is bounded too, and reads are
  retried once, because a shop's connection drops in and out all day.
- The dashboard shows the day's money, the four actions (`+ Sale`, `+ Product`, `Stock In`, `Expense`),
  the shelf with stock pills, recent sales and what is running out, with a sheet per action. There is no
  holding screen: the sign-in card appears at once and the dashboard replaces it when a session is
  found, because a screen that says "checking..." forever is indistinguishable from a broken app.
- Branding: the wordmark is AHIA with the dotted I of Igbo orthography, rendered from an escape
  sequence so the source stays ASCII (ADR-0006) and the screen shows the correct letter, in the accent
  colour; the mark is a four-cell market grid that reads at favicon size.

- The entry experience is three routes now, because one screen was doing three jobs. `/` is the public
  page: what AHIA does, in a trader's words - a sale and a receipt to send, stock that matches the
  shelf, the day's money - with the WhatsApp relationship stated rather than threatened. `/start` is
  sign-in and sign-up, one screen with two modes and no lecture about where the session is kept. `/app`
  is the dashboard, which asks once whether there is a session and either renders or sends the person
  to sign in. The "Checking your session..." screen is gone: while the probe is in flight the page
  shows the shape of itself, so a slow network never leaves somebody staring at a word.
- Development now runs against the local PostgreSQL instead of Neon, and the difference is not
  cosmetic: a tenant was created in 3023ms on Neon and in 22ms locally, and the full browser journey -
  account, business, product, stock, sale, ten screenshots - went from most of a minute to 8.2 seconds.
  The Neon URL is still in `.env`, commented on the line above, because that is the deployment database
  and switching back is one line.
- Media is verified end to end against the real Cloudinary account: a 64x64 PNG uploaded through
  `POST /tenants/{id}/products/{pid}/images` came back as an optimised 78-byte webp stored under a
  tenant/product path, with a delivery URL the product schema exposes. `FEATURE_MEDIA_UPLOAD` and
  `FEATURE_STOREFRONT_PUBLIC_PUBLISHING` are enabled in `.env`, with the upload UI still to come.

- The web app is mobile-responsive, and that is measured rather than claimed:
  `web/scripts/mobile-check.mjs` drives the whole journey at 390x844 and fails if any screen is wider
  than the viewport - the one defect that makes a mobile page feel broken. It found seven: a form whose
  inputs could not shrink below their intrinsic width, and a dashboard header with three things on one
  row. Both are fixed at the cause (a flex item does not shrink below its content unless it is allowed
  to; a grid instead of a wrapping flex row for the stat cards), and every screen now measures exactly
  390/390.
- Product photos are in the dashboard: a thumbnail on each shelf row, a sheet per product with upload
  (the phone's camera or the gallery), cover selection and removal. The upload is verified against the
  real Cloudinary account from the browser, with the check waiting for the picture to *decode* rather
  than for the row to exist.
- **A delivery-URL bug found by that verification.** The adapter asked the Cloudinary SDK for a
  transformation as a string, and the SDK reads a string as the name of a transformation saved in the
  account: it rendered `t_w_2000,c_limit`, which Cloudinary answers with a 400. Every product photo
  would have been a broken image. The transformation is now a mapping, which the SDK renders inline,
  and the invariant is written down where the next person will read it.
- **Phone numbers were creating more than one account for one person.** `2348031234567` - the country
  code typed without a plus - was completed a second time into `+2342348031234567`, while
  `08031234567`, `8031234567` and `+2348031234567` all agreed. The rule also existed twice, in the
  entity and in the auth service, which is how it drifted. It now exists once: the country code is
  recognised with or without a plus, the international prefix `00` is handled, and a length guard stops
  a local number that merely begins with the same digits from being read as international. Signing up
  with a phone number and no email address works, and all four written forms reach the same account.
- The Next.js development indicator is switched off: it is a tool for the person writing the code and
  it sat on top of the interface for everybody else.

## M19 - progress log (third pass)

- The checklist above was stale for four commits, which is its own kind of defect: a plan nobody
  updates stops being the record of what happened and becomes a claim. From here, each commit that
  completes something updates this file in the same commit rather than later.
- What the third pass covers: **the profile** (your details, the business's details, your businesses
  and their roles, password change), **product photos** through the real Cloudinary account, **the
  public shopfront** with its own metadata for WhatsApp previews, **shop management** (open, close,
  edit, copy link, share, show/hide a product), **more than one business** on one account, and **a
  mobile pass** across every screen. The only M19 items still open are client-side permission
  awareness, the team screen, and shop visits.
- The bugs that pass found, all of which were invisible until somebody used the product: the sign-up
  form dropped whichever contact was in its second box, so an account could exist with no email
  address; the phone rule doubled a country code typed without a plus, so `2348031234567` was a
  different person from `+2348031234567`; the storefront flag's setting name was misspelled, so the
  documented environment variable did nothing and the whole shopfront was off with no symptom; the
  Cloudinary adapter asked for a *named* transformation, which the provider rejects, so every product
  photo was a broken image; an empty text box was sent as an empty string where the API's smallest
  valid value is one character; the public product payload is a wrapper rather than the product, which
  rendered "undefined" as a name; the server-side API base used `??` where the browser-side variable is
  deliberately empty, so the shop page 404'd for shops the API was serving; sheets kept the last values
  typed into them; one busy flag disabled buttons while unrelated requests ran; and switching
  businesses left the previous shop's shelf on screen under the new shop's name.
- Each of those is now pinned by a check rather than by a note: `mobile-check` for the journey and the
  viewport, `shop-check` for the public shop in a browser with no cookies at all, `profile-check` for
  the profile, `businesses-check` for two businesses staying apart, `firefox-check` for the second
  browser, and the API's own suites for the phone rule, the delivery URL and the storefront routes.

- M19.2.6 complete: **the team**. A `/app/team` screen that lists who is in the business with their
  role and status, invites somebody by phone or email, promotes or suspends them, and removes them.
  Four roles, and they are the product's own people: the owner (Oga), a manager, sales (the nwa boy or
  nwa girl on the counter), and whoever counts stock.
- **The invitation travels on WhatsApp, because that is where a trader's messages go.** The API returns
  the token exactly once and stores only its digest, so the screen shows the link immediately and
  offers to send it: the person taps it, signs up with the number the owner invited, and lands inside
  the business. `/join/{token}` is that landing page, and `?next=` on the sign-in screen is what makes
  the link survive a sign-up - validated to a path on this site, because an unchecked one is an open
  redirect.
- Two defects found by using it, both in the API rather than the screen. **An invitation to a phone
  number could never be accepted**: the invitation stored the number as typed (`08051954235`) while the
  account stored it canonically (`+2348051954235`), so the identity check never matched - the same
  class of bug as the doubled country code, in the one place it had not been fixed. And **a person
  could hold two memberships in one business**: nothing in the database said otherwise, so a
  double-tapped invitation link - which React's development mode produces on its own - created two
  rows twelve milliseconds apart, and removing one left the person still in. The database now has a
  partial unique index on `(tenant_id, user_id) WHERE status <> 'removed'`, with a migration that
  repairs existing duplicates by keeping the oldest and marking the rest removed, so the audit trail
  survives.
- `web/scripts/team-check.mjs` proves the whole flow: invite a phone number, take the link into a
  browser with no cookies, sign up as the invited person, land inside with the invited role, promote
  them, remove them.

## M19 - progress log (gate repair after CI went red)

- The GitHub job was red and the report was right about the two classes of failure, and wrong about why
  one of them was failing. Recorded here because the diagnosis matters more than the fix.
- **The append-only rule existed only in the migrations.** Tests and CI build the schema from the
  SQLAlchemy metadata (`create_all`), never by running the migration chain, so `inventory_movements`
  and `ledger_entries` had no trigger where every change is tried first and did have one in production.
  That is exactly backwards. The guard is now declared where the table is declared
  (`crud/append_only_guard.py`, called from the three records that need it), so every path that creates
  a table also creates its protection. It had to be one statement per DDL object: the driver refuses
  more than one command in a prepared statement, so a single block of SQL failed the moment a table was
  created.
- **The ten "unauthenticated" tests were authenticated.** Each one signed somebody in, then dropped the
  `Authorization` header and expected `401` - but the session now travels in a cookie, and a shared test
  client keeps it. The endpoints were right; the tests were describing a caller who no longer existed.
  They now empty the cookie jar, which is what "no credentials at all" actually means.
- Reproduced by building a scratch database the way CI does (`ahia_ci`, metadata only) rather than by
  trusting the local one, which had a schema built by migrations and therefore hid both defects. The
  full suite passes on that scratch database: 2125 passed, 0 failed.
