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
| M8 | Alembic migration baseline (M8.1.4 deferred to M9) | `[~]` | M6 |
| M9 | Catalog: categories, products, images, R2 storage | `[ ]` | M8 |
| M10 | Inventory ledger and projections | `[ ]` | M9 |
| M11 | Customers | `[ ]` | M9 |
| M12 | Sales, payments, ledger, transactional integrity | `[ ]` | M10, M11 |
| M13 | Expenses | `[ ]` | M12 |
| M14 | Audit trail | `[ ]` | M6 |
| M15 | Offline synchronization and idempotency | `[ ]` | M12 |
| M16 | Public storefront, sharing, WhatsApp click-to-chat, QR | `[ ]` | M9 |
| M17 | Reports, insights, low-stock alerts, notifications | `[ ]` | M12 |
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
- [ ] M8.1.4 DEFERRED to M9, deliberately. Composite foreign keys of the
      `(product_id, tenant_id)` form anchor on tenant-owned tables such as
      `products`, which do not exist yet. The constraint is added with the table
      that needs it, together with the test that a cross-tenant reference is
      rejected by the database itself. Adding the anchor now would mean inventing
      a table in M8 to satisfy a later milestone.

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
- [ ] M9.1.7 `product_image_model.py`, `product_image_crud.py`,
      `product_image_schema.py`, `product_image_service.py`,
      `product_image_router.py`.
- [ ] M9.1.8 Storage and media capabilities: delivered in M1.11 through M1.17.
      M9 consumes them through the port; it does not construct a provider.
- [ ] M9.1.9 Server-side upload pipeline: authorize `products.update`, validate
      the request, decode and optimize the image through the media capability,
      reserve tenant quota, upload through the storage capability under a
      server-generated key, then persist the metadata and commit the quota in
      one transaction. A client-supplied object key or storage provider is never
      trusted or accepted.
- [x] M9.1.10 Provider-neutral image metadata persistence: `storage_provider`,
      `storage_key`, `mime_type`, `size_bytes`, `width`, `height`,
      `checksum_sha256`, `sort_order`, `is_primary`, plus `removed_at` and
      `reconciliation_reason` so a failed provider delete stays findable. No column
      is named after a provider, and an architecture test now asserts that over the
      whole metadata: no table may have a column containing `r2`, `s3`, `bucket` or
      the other vendor's name.
- [ ] M9.1.11 Product image limits: maximum count per product and maximum
      stored bytes per tenant, both configuration-driven, both enforced before
      persistence, with the error naming the limit that was hit.
- [ ] M9.1.12 Deletion and replacement: removing an image deletes the stored
      object and releases its quota allocation; a failed provider delete leaves
      the metadata row marked for reconciliation rather than silently leaking
      storage.
- [ ] M9.1.13 Catalog migration and tests, including cross-tenant product
      access denial, cross-tenant image access denial and price precision tests.
- [ ] M9.1.14 Storage failure test: with the active provider unavailable,
      catalog reads and product writes still work and image upload returns a
      typed degraded result. Run against both providers through the shared
      contract suite.
- [ ] M9.1.15 Provider switch test: switching `STORAGE_PROVIDER` changes the
      adapter and leaves every product, storefront and image service untouched,
      with existing rows still resolvable to the provider that holds them.

### M9 - progress log

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

- [ ] M10.1.1 `inventory_model.py` and `inventory_movement_model.py` as pure
      entities with the invariant `after = before + delta`.
- [ ] M10.1.2 Persistence for both, with the movement ledger append-only.
- [ ] M10.1.3 `inventory_service.py`: `receive_stock`, `adjust_stock`,
      `record_damage`, `transfer_stock`, `get_inventory_for_product`,
      `list_movements`, each writing a movement and updating the projection in
      one transaction.
- [ ] M10.1.4 Negative-stock policy handling with an explicit tenant
      configuration point.
- [ ] M10.1.5 `inventory_schema.py` and `inventory_router.py`.
- [ ] M10.1.6 Concurrency test: two concurrent offline sales produce two
      movements and a deterministic projection.
- [ ] M10.1.7 Invariant test: a quantity cannot change without a movement.

---

## M11 - Customers

- [ ] M11.1.1 `customer_model.py`, `customer_schema.py`, `customer_crud.py`,
      `customer_service.py`, `customer_router.py`.
- [ ] M11.1.2 Tenant scoping and privacy: opt-in flag, no cross-tenant leakage,
      identifiers rather than names in logs.
- [ ] M11.1.3 Customer notes and version metadata for sync-safe merging.
- [ ] M11.1.4 Tests: cross-tenant customer access denial, duplicate detection
      by phone within a tenant, soft deactivation preserving sales history.

---

## M12 - Sales, payments, ledger, transactional integrity

- [ ] M12.1.1 `sale_model.py`, `sale_item_model.py` with snapshot fields and
      monetary invariants.
- [ ] M12.1.2 `payment_model.py` with method and status enums.
- [ ] M12.1.3 `ledger_entry_model.py` as an append-only derived record.
- [ ] M12.1.4 Persistence for all four entities, one file each, no cross-entity
      joins.
- [ ] M12.1.5 `sales_service.py`: `complete_sale` inside a single transaction
      creating sale, items, payments, inventory movements, inventory projection
      updates, ledger entry and audit event; failure of any part rolls back all.
- [ ] M12.1.6 `cancel_sale` with compensating inventory and financial events,
      never a deletion.
- [ ] M12.1.7 Receipt numbering per tenant with a uniqueness guarantee.
- [ ] M12.1.8 Sales schemas and router endpoints.
- [ ] M12.1.9 Tests: full transaction rollback on injected failure, no
      half-created sale, cancellation semantics, money precision, permission
      enforcement (`sales.create`, `sales.cancel`).
- [ ] M12.1.10 Idempotency at the operation level: replaying `operation_id`
      returns the original result and creates nothing new.

---

## M13 - Expenses

- [ ] M13.1.1 `expense_model.py`, `expense_schema.py`, `expense_crud.py`,
      `expense_service.py`, `expense_router.py`.
- [ ] M13.1.2 Expense categories as configuration, not free text where
      reporting depends on them.
- [ ] M13.1.3 Ledger entry creation for each expense.
- [ ] M13.1.4 Tests: permission enforcement, no hard delete of financial
      history, tenant scoping.

---

## M14 - Audit trail

- [ ] M14.1.1 `audit_event_model.py` and append-only persistence.
- [ ] M14.1.2 `audit_service.py`: `record_audit_event` and a query surface for
      owners.
- [ ] M14.1.3 Audit writing wired into every mutating use case from M4 onward.
- [ ] M14.1.4 Audit query endpoints restricted to `reports.read` or an
      equivalent owner-only permission.
- [ ] M14.1.5 Tests: actor, tenant, device, operation, entity and timestamp
      captured; audit records cannot be updated or deleted through the API.

---

## M15 - Offline synchronization and idempotency

- [ ] M15.1.1 `sync_operation_model.py` and `sync_cursor_model.py`.
- [ ] M15.1.2 Change/outbox table with a monotonically increasing server
      sequence, written in the same transaction as the business change.
- [ ] M15.1.3 `sync_service.py`: `push_operations` (authenticate, resolve
      tenant, check permission, check operation id, validate payload, execute
      transaction, return result) and `pull_changes` (cursor-based change feed).
- [ ] M15.1.4 Conflict classification per the specification matrix: operation
      based for transactional facts, versioned/LWW for safe metadata,
      explicit conflict for high-value fields.
- [ ] M15.1.5 `sync_schema.py` and `sync_router.py` gated by
      `FEATURE_OFFLINE_SYNC`.
- [ ] M15.1.6 Tests: duplicate operation deduplicated, out-of-order arrival,
      conflict classification, cursor monotonicity, revoked device rejection,
      and a resumption test after simulated interruption.
- [ ] M15.1.7 Synchronization diagnostics: tenant, user, device, operation,
      timestamp, request and result are all traceable without logging secrets.

---

## M16 - Public storefront, sharing, WhatsApp click-to-chat, QR

- [ ] M16.1.1 `storefront_model.py`, `storefront_crud.py`,
      `storefront_service.py` with publish/unpublish lifecycle.
- [ ] M16.1.2 Public slug resolution and public product projection that never
      exposes cost price, stock counts, staff or financial data.
- [ ] M16.1.3 Public read endpoints: storefront, product detail, catalog
      listing, with no authentication required and rate limiting applied.
- [ ] M16.1.4 Public share tokens for invoices, shipments and reports
      (non-guessable, revocable).
- [ ] M16.1.5 WhatsApp click-to-chat adapter in
      `integrations/whatsapp/click_to_chat.py` producing prefilled, correctly
      encoded links, including Nigerian number normalization.
- [ ] M16.1.6 QR payload builder encoding stable public URLs only.
- [ ] M16.1.7 Tests: unpublished storefront inaccessible, no private field
      leaks in public projections, share token revocation, link encoding with
      special characters, and cross-tenant slug isolation.
- [ ] M16.1.8 Feature flag `FEATURE_STOREFRONT_PUBLIC_PUBLISHING` wired and
      logged at startup.

---

## M17 - Reports, insights, low-stock alerts, notifications

- [ ] M17.1.1 Daily sales summary query surface with tenant scoping.
- [ ] M17.1.2 Product performance and low-stock reporting.
- [ ] M17.1.3 Report export to R2 with a share token.
- [ ] M17.1.4 Low-stock alert evaluation as a scheduled job entry point that
      reuses the service layer rather than duplicating rules.
- [ ] M17.1.5 In-app notification records.
- [ ] M17.1.6 Tests: report correctness against seeded data, permission
      enforcement (`reports.read`), and scheduled job idempotency.

---

## M18 - Hardening, observability, deployment

- [ ] M18.1.1 Rate limiting reviewed across every endpoint class; expensive
      and message-sending endpoints covered.
- [ ] M18.1.2 Request duration, error count, authorization denial and breaker
      state metrics exposed in a form the platform can scrape.
- [ ] M18.1.3 Row-Level Security rollout plan and implementation for the
      highest-risk tables, with a session-level tenant setting that is
      verifiably set before any query.
- [ ] M18.1.4 Dependency audit gate confirmed to fail the build on a critical
      finding, with a deliberately planted test finding.
- [ ] M18.1.5 Northflank deployment configuration, health checks and secret
      wiring documented.
- [ ] M18.1.6 Production runbook in `docs/`: startup, migration, rollback,
      secret rotation, breaker trip response, correlation-ID based
      troubleshooting.
- [ ] M18.1.7 Load smoke test on the sale endpoint; record numbers.

---

## M19 - Web application bootstrap (Next.js)

- [ ] M19.1.1 `web/` workspace with Next.js, TypeScript, strict mode, and a
      committed lockfile.
- [ ] M19.1.2 Typed API client generated from or aligned with the backend
      schemas.
- [ ] M19.1.3 Authentication flow against the real API.
- [ ] M19.1.4 Trader dashboard shell with the operational actions
      (`+ Sale`, `+ Product`, `Stock In`, `Expense`).
- [ ] M19.1.5 Public storefront rendering from the public API with correct
      metadata for sharing.
- [ ] M19.1.6 Client-side permission awareness that hides unavailable actions
      while never being the authority.
- [ ] M19.1.7 End-to-end test: create product, record sale, see inventory
      update, open the public storefront.

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
- [ ] Any architectural decision that touches data ownership, multi-tenancy,
      synchronization, permissions, transactions, external dependencies or
      public/private boundaries is appended to `docs/ARCHITECTURE.md` decision
      log before implementation proceeds.
