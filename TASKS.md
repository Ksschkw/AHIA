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
| M0 | Repository and developer tooling foundation | `[~]` | - |
| M1 | Core cross-cutting infrastructure | `[ ]` | M0 |
| M2 | User demonstrative vertical slice | `[ ]` | M1 |
| M3 | Authentication and sessions | `[ ]` | M2 |
| M4 | Tenant slice | `[ ]` | M3 |
| M5 | Membership and staff administration | `[ ]` | M4 |
| M6 | Roles, permissions and deny-by-default authorization | `[ ]` | M5 |
| M7 | Devices and session management | `[ ]` | M6 |
| M8 | Alembic migration baseline | `[ ]` | M6 |
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

- [ ] M0.2.1 `backend/pyproject.toml`: project metadata, `src` layout, pinned
      dependency floors, and tool configuration for ruff, mypy, pytest and
      coverage in one file.
- [ ] M0.2.2 `backend/scripts/bootstrap_backend.sh`: creates `backend/.venv`,
      upgrades pip, installs the lockfile, installs the package in editable
      mode, and is safe to re-run.
- [ ] M0.2.3 Lockfile: exact pins for runtime and development dependencies,
      generated by a resolver and committed. Re-generation is an explicit
      command, never an implicit side effect.
- [ ] M0.2.4 Package skeleton: `backend/src/ahia/` with `__init__.py` exposing
      `__version__`, plus empty-but-real `models/entities`, `schemas`, `crud`,
      `services`, `routers`, `core`, `middleware`, `integrations/storage`,
      `integrations/whatsapp` packages, each with a docstring stating its layer
      responsibility.

### M0.3 Configuration contract

- [ ] M0.3.1 `backend/.env.example`: every variable from
      `docs/PREREQUISITES.md` section 3 with placeholder values only, grouped by
      concern, with the secret values obviously fake.
- [ ] M0.3.2 `.gitignore` coverage proof: a test that asserts `.env`,
      `.env.local` and key material patterns are ignored, so the guarantee is
      executable rather than aspirational.

### M0.4 Code hygiene enforcement

- [ ] M0.4.1 `backend/scripts/check_ascii.py`: fails on emoji, box drawing,
      decorative symbols and any non-ASCII character in engineering artifacts,
      with a scoped, explicit allowlist for test fixtures that intentionally
      contain Unicode user data.
- [ ] M0.4.2 Banned-identifier check: rejects `data`, `info`, `manager`,
      `helper`, `utils`, `common`, `misc`, `temp`, `tmp`, `process`, `handle`,
      `do`, `thing` as standalone module, class or file names, with the
      narrow exceptions the preset allows.
- [ ] M0.4.3 Tests for both guards: a passing tree and planted violations that
      must be detected, so the guard cannot silently rot.

### M0.5 Architecture enforcement

- [ ] M0.5.1 `backend/import-linter.ini`: layered contracts for entities,
      schemas, crud, services, routers, core, middleware and integrations,
      forbidding every outward import listed in the scaffold specification.
- [ ] M0.5.2 `backend/tests/architecture/test_layer_contracts.py`: runs the
      contracts inside pytest so an architecture violation fails the ordinary
      test command, not only a separate tool invocation.

### M0.6 Secret and dependency scanning

- [ ] M0.6.1 `gitleaks` installed into a workspace tool directory by a script
      that verifies a pinned checksum, since this workstation's system paths are
      read-only.
- [ ] M0.6.2 `.gitleaks.toml`: default rule set plus an explicit allowlist for
      the placeholder values in `.env.example` and the local-only development
      password documented in `docs/PREREQUISITES.md`.
- [ ] M0.6.3 `backend/scripts/scan_secrets.sh`: scans the working tree and,
      when asked, the full git history; exits non-zero on any finding.
- [ ] M0.6.4 Dependency audit: `pip-audit` wired into the check command, with a
      committed ignore file for findings that have a documented, time-boxed
      justification.

### M0.7 Pre-commit hooks

- [ ] M0.7.1 `backend/.pre-commit-config.yaml`: trailing whitespace, end of
      file, YAML/TOML validity, large file guard, private key guard, ruff,
      ASCII guard, architecture check and gitleaks.
- [ ] M0.7.2 Hook installation and verification: install into the repository
      hooks directory and prove the hooks run by executing them against the
      tree.

### M0.8 One reproducible developer command

- [ ] M0.8.1 `Makefile`: `setup`, `lint`, `format`, `typecheck`, `test`,
      `arch`, `secrets`, `audit`, `ascii`, `check`, `run`, `migrate`, `revision`
      targets, each a thin wrapper over a real script or tool with no hidden
      logic.
- [ ] M0.8.2 `backend/scripts/dev_check.sh`: runs every gate in a fixed order,
      prints a plain-ASCII summary (`[OK]`, `[FAIL]`) and returns the correct
      exit code.

### M0.9 Continuous integration

- [ ] M0.9.1 `.github/workflows/backend-check.yml`: PostgreSQL service
      container, Python 3.12, locked install, `make check`, with a critical
      dependency-audit finding failing the build.

### M0.10 Containers

- [ ] M0.10.1 `backend/Dockerfile`: multi-stage build, non-root runtime user,
      no secrets in the image, `uvicorn ahia.main:app` as the process.
- [ ] M0.10.2 `backend/.dockerignore`: excludes virtualenvs, tests, caches,
      env files and documentation from the build context.
- [ ] M0.10.3 `backend/docker-compose.dev.yml`: local PostgreSQL service for a
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

### M1.1 Configuration

- [ ] M1.1.1 `core/config.py`: typed settings object built from environment
      variables, with validation, environment profiles (`development`, `test`,
      `production`) and no module-level mutable global.
- [ ] M1.1.2 Feature flag registry in `core/config.py`: name, type, default,
      description, date added and removal condition for each flag declared in
      `docs/PREREQUISITES.md` section 4.
- [ ] M1.1.3 Startup flag logging: exactly one INFO line per flag at
      application start, and a check that no security control is flag-gated.
- [ ] M1.1.4 Tests: missing required variable fails loudly, defaults are safe,
      production rejects console log format and disabled TLS, and the flag
      registry is internally consistent.

### M1.2 Error architecture

- [ ] M1.2.1 `core/errors.py` base hierarchy: one root error, layer-tagged
      subclasses (`EntityError`, `SchemaError`, `PersistenceError`,
      `DomainError`, `TransportError`, `IntegrationError`), and the typed
      `NotFoundError`, `ConflictError`, `AuthorizationError`,
      `AuthenticationError`, `ValidationError`, `DependencyUnavailableError`.
- [ ] M1.2.2 Correlation ID: context variable, generator, inbound validation
      rules (length, character set) and accessor used by every layer.
- [ ] M1.2.3 External envelope mapping: one table from error type to HTTP
      status, external code and safe message. Internal detail never crosses.
- [ ] M1.2.4 Tests: internal errors carry operation, entity, identifier, layer,
      correlation ID and cause chain; external payloads contain exactly the
      code, safe message and correlation ID; a leak test asserts that no stack
      trace, SQL fragment, path, hostname or dependency exception appears.

### M1.3 Structured logging

- [ ] M1.3.1 `core/logging.py` JSON formatter: timestamp, level, logger,
      correlation ID, operation, layer, and safe identifiers.
- [ ] M1.3.2 Redaction: passwords, hashes, tokens, API keys, authorization
      headers, cookies and configured secret fields are redacted by the logger
      itself, not by call sites.
- [ ] M1.3.3 Request-scoped logger: a bound adapter that carries correlation ID,
      tenant, actor and device without callers repeating them.
- [ ] M1.3.4 Tests: redaction of nested and case-varied keys, correlation ID
      presence in every record, and no secret ever appearing in a formatted
      record.

### M1.4 Resilience primitives

- [ ] M1.4.1 Timeout wrapper for outbound calls, with a typed timeout error.
- [ ] M1.4.2 Circuit breaker: closed, open and half-open states; failure
      threshold, reset window and probe count from configuration; one breaker
      per dependency; state transitions emit a metric and a structured log.
- [ ] M1.4.3 Bulkhead: per-dependency concurrency limit and queue behavior.
- [ ] M1.4.4 Retry policy: bounded attempts, exponential backoff with jitter,
      idempotency guard that refuses to retry a non-idempotent operation.
- [ ] M1.4.5 Fallback contract: a typed degraded result, never `None`, never a
      silent success.
- [ ] M1.4.6 Tests: breaker trips and recovers, retries are bounded and
      jittered, timeout fires, bulkhead rejects past the limit, fallback is
      typed, and no breaker exists around in-process calls.

### M1.5 Security primitives

- [ ] M1.5.1 Argon2id password hashing and verification with configured cost
      parameters and constant-time comparison.
- [ ] M1.5.2 JWT access token encode and decode with issuer, audience,
      expiry, algorithm allowlist and clock-skew handling.
- [ ] M1.5.3 Refresh token generation, hashing with a pepper, and constant-time
      verification; cryptographically secure public token generator.
- [ ] M1.5.4 Tests: wrong password, unknown user timing behavior, expired,
      tampered, wrong-issuer and wrong-audience tokens are all rejected.

### M1.6 Database lifecycle

- [ ] M1.6.1 `core/database.py`: async engine and session factory built from
      configuration, with pool size, overflow, pool timeout, statement timeout
      and TLS enforcement.
- [ ] M1.6.2 Session dependency: one session per request, committed or rolled
      back exactly once, closed on exit.
- [ ] M1.6.3 Unit of work port and SQLAlchemy implementation: services declare
      transactional intent without importing a database driver.
- [ ] M1.6.4 Declarative base with a naming convention for constraints and
      indexes so Alembic autogenerate produces stable, reviewable names.
- [ ] M1.6.5 Tests: engine configuration reflects settings, sessions do not
      leak, rollback on error, and the unit of work commits once.

### M1.7 Tenant context and authorization policy

- [ ] M1.7.1 `core/tenant_context.py`: immutable context carrying user,
      tenant, membership, role, permissions and device, with explicit
      helpers that make the difference between "requested tenant" and
      "authorized tenant" obvious.
- [ ] M1.7.2 Permission registry: one module per domain
      (`product_permissions`, `inventory_permissions`, `sales_permissions`,
      `customer_permissions`, `expense_permissions`, `storefront_permissions`,
      `staff_permissions`, `report_permissions`) plus `permissions_registry`
      exposing the full code set and the system role bundles.
- [ ] M1.7.3 `require_permission` policy: deny-by-default, checks against the
      authorized context only, logs every decision with principal, tenant,
      resource, action and outcome, and fails closed when the permission set
      cannot be resolved.
- [ ] M1.7.4 Tests: missing permission denies, unrelated role denies, owner
      bundle allows configured codes, and every decision produces a log record.

### M1.8 Composition root

- [ ] M1.8.1 `core/container.py`: constructs configuration, engine, session
      factory, unit of work, repositories, services, integrations and
      resilience policies in one place.
- [ ] M1.8.2 Lifespan resource management: create on startup, dispose on
      shutdown, expose readiness state, and fail startup loudly if a required
      resource is unavailable.
- [ ] M1.8.3 Tests: container builds in test profile, no module-level
      singleton state, resources are disposed, and a missing dependency fails
      at startup rather than at first request.

### M1.9 Middleware

- [ ] M1.9.1 `middleware/correlation_middleware.py`: read or generate the
      correlation ID, validate inbound format, expose it on the request state
      and the response, and bind it into the logger.
- [ ] M1.9.2 `middleware/security_headers_middleware.py`: HSTS, CSP,
      `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` on every
      response, including error responses.
- [ ] M1.9.3 `middleware/rate_limit_middleware.py`: per-identity and per-route
      limits for authentication, password reset, writes and expensive
      endpoints; never disabled by a flag; returns a typed 429 through the
      standard envelope.
- [ ] M1.9.4 `middleware/error_handler_middleware.py`: one place mapping typed
      errors to status and envelope, logging full internal context, returning
      nothing internal to the client, and handling unexpected exceptions
      without leaking.
- [ ] M1.9.5 Tests: header presence on success and failure, correlation ID
      round trip, rate limit trips and recovers, and error mapping for every
      typed error.

### M1.10 Application assembly

- [ ] M1.10.1 `main.py` app factory: settings, container, middleware
      registration, router registration under `/api/v1`, exception handlers.
- [ ] M1.10.2 Lifespan wiring: startup logging of environment, version and
      flags; clean shutdown.
- [ ] M1.10.3 Health endpoints: `GET /health` for liveness and `GET /ready`
      for critical dependency readiness, exposing no internals.
- [ ] M1.10.4 Tests: app imports without side effects, health and ready
      answer, unknown route returns the standard error envelope, and no
      configuration is read outside `core/config.py` (enforced by an AST test).

---

## M2 - User demonstrative vertical slice

Goal: prove the architecture end to end with one real entity before multiplying
it, including `GET /api/v1/users/me`.

Exit criteria: an authenticated request flows transport to service to
persistence to entity and back, with a correlation ID, typed error handling and
layer-appropriate tests.

### M2.1 Entity

- [ ] M2.1.1 `models/entities/user_model.py`: frozen domain object with
      identity, contact, name, lifecycle fields and domain invariants
      (identifier stability, at least one contact channel, normalized phone,
      active-state transitions). No framework import.
- [ ] M2.1.2 Entity tests: construction invariants, normalization, equality,
      immutability, and rejection of invalid values.

### M2.2 Schema

- [ ] M2.2.1 `schemas/user_schema.py`: `UserCreateSchema`,
      `UserUpdateSchema`, `UserResponseSchema` with allowlist validation,
      field length limits and explicit serialization rules. No business rules.
- [ ] M2.2.2 Schema tests: valid input, missing fields, oversized input,
      malformed email and phone, unknown field rejection, and response shape.

### M2.3 Persistence

- [ ] M2.3.1 `crud/user_crud.py`: SQLAlchemy record owning the `users` table,
      the row-to-entity mapper, and `get_by_id`, `get_by_email`,
      `get_by_phone`, `create`, `update`, `deactivate`. Returns entities, never
      records.
- [ ] M2.3.2 CRUD tests: mapping both directions, unique constraint behavior,
      tenant-independent lookups by identity, and no business decisions in the
      file.

### M2.4 Service

- [ ] M2.4.1 `services/user_service.py`: `get_authenticated_user`,
      `update_user_profile`, `deactivate_user` with authorization checks at the
      service layer, unit-of-work usage, and structured logging with
      correlation ID.
- [ ] M2.4.2 Service tests with the CRUD layer mocked: authorization denial,
      not-found mapping, successful profile update, and audit logging.

### M2.5 Transport

- [ ] M2.5.1 `routers/user_router.py`: `GET /api/v1/users/me` and
      `PATCH /api/v1/users/me`, both parse, call one service method and return
      a schema. No branching beyond dependency wiring.
- [ ] M2.5.2 Router tests with the service mocked: response shape, status
      codes, unauthenticated access, and confirmation that the handler performs
      no business logic.

### M2.6 Wiring and smoke

- [ ] M2.6.1 Wire the User slice into the composition root and register the
      router; add a smoke test that starts the application against the test
      database.
- [ ] M2.6.2 `docs/` endpoint reference for the slice, including the error
      envelope and the correlation ID header.

### M2.7 Cross-cutting verification

- [ ] M2.7.1 Security test: the external error response for a failed request
      contains no stack trace, SQL, path, hostname or dependency name.
- [ ] M2.7.2 Architecture test additions for the new modules, and a
      confirmation run of `make check` recorded in the commit message.

---

## M3 - Authentication and sessions

Goal: real identity. Email/password registration and login, short-lived access
tokens, rotating refresh tokens, logout, and rate limiting on every credential
endpoint.

- [ ] M3.1.1 `SessionModel` entity and `session_crud.py` persistence for
      refresh token hashes, device binding, expiry and revocation.
- [ ] M3.1.2 `auth_schema.py` request and response contracts.
- [ ] M3.1.3 `auth_service.py`: `register_user`, `authenticate_user`,
      `refresh_session`, `revoke_session`, `change_password` with constant-time
      failure behavior and identical external errors for unknown user and wrong
      password.
- [ ] M3.1.4 `auth_router.py`: `POST /api/v1/auth/register`,
      `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh`,
      `POST /api/v1/auth/logout` with strict rate limits.
- [ ] M3.1.5 Authentication dependency: bearer token to authenticated
      principal, denying malformed, expired, wrong-issuer and wrong-audience
      tokens with a single external message.
- [ ] M3.1.6 Tests: registration, duplicate registration policy, login
      success and failure, refresh rotation and reuse detection, logout
      revocation, rate limit behavior, and no-existence-disclosure.
- [ ] M3.1.7 Security tests: token tampering, algorithm confusion, replay of a
      rotated refresh token, and credential stuffing throttling.

M3 exit criteria: a client can register, log in, call `/users/me`, refresh and
log out; every credential endpoint is rate limited; no response reveals whether
an account exists.

---

## M4 - Tenant slice

Goal: a business exists as a tenant with a globally unique public slug.

- [ ] M4.1.1 `tenant_model.py` with slug invariants and lifecycle rules.
- [ ] M4.1.2 `tenant_schema.py` with slug format validation and reserved-word
      rejection.
- [ ] M4.1.3 `tenant_crud.py`: persistence with global slug uniqueness.
- [ ] M4.1.4 `tenant_service.py`: `create_tenant`, `update_tenant_profile`,
      `get_tenant`, `deactivate_tenant`, with slug allocation and conflict
      handling.
- [ ] M4.1.5 `tenant_router.py`: `POST /api/v1/tenants`, `GET /api/v1/tenants`,
      `GET /api/v1/tenants/{tenant_id}`, `PATCH /api/v1/tenants/{tenant_id}`.
- [ ] M4.1.6 Tests: slug collisions, reserved slugs, cross-tenant access
      denial, tenant list scoping to memberships.
- [ ] M4.1.7 Tenant-context resolution: requested tenant is a hint, membership
      is the proof; denial is deny-by-default.

---

## M5 - Membership and staff administration

- [ ] M5.1.1 `tenant_membership_model.py` with status lifecycle (`invited`,
      `active`, `suspended`, `removed`) and uniqueness invariant.
- [ ] M5.1.2 `tenant_membership_schema.py`.
- [ ] M5.1.3 `tenant_membership_crud.py`.
- [ ] M5.1.4 `tenant_membership_service.py`: `invite_tenant_member`,
      `activate_membership`, `change_member_role`, `suspend_member`,
      `remove_member`, each authorizing `staff.*` permissions.
- [ ] M5.1.5 `tenant_membership_router.py` for the staff endpoints.
- [ ] M5.1.6 Invitation token entity and flow that never requires an owner to
      share a password.
- [ ] M5.1.7 Tests: last-owner protection, self-removal policy, duplicate
      membership, inactive membership denial, cross-tenant denial.

---

## M6 - Roles, permissions and authorization

- [ ] M6.1.1 `permission_model.py`, `role_model.py`, `role_permission_model.py`
      as pure entities.
- [ ] M6.1.2 Persistence for the three entities, one file each.
- [ ] M6.1.3 Permission registry seeding: system permissions from
      `core/permissions/`, system roles (OWNER, MANAGER, SALES, INVENTORY) as
      permission bundles.
- [ ] M6.1.4 `permission_service.py`: `resolve_permissions_for_membership`,
      `list_roles`, `list_permissions`, `update_role_permissions` with
      server-authoritative decisions.
- [ ] M6.1.5 `role_service.py` and `permission_router.py`.
- [ ] M6.1.6 Data migration/seeding path that installs the registry
      idempotently.
- [ ] M6.1.7 Tests: role bundle correctness, permission escalation attempt,
      custom role behavior if enabled, and a cross-tenant role isolation test.

---

## M7 - Devices and session management

- [ ] M7.1.1 `device_model.py` and persistence with
      `UNIQUE(tenant_id, device_identifier)`.
- [ ] M7.1.2 Device registration and heartbeat endpoints.
- [ ] M7.1.3 Device revocation: revoked devices are rejected by sync and by
      session validation.
- [ ] M7.1.4 `device_service.py` and `device_router.py` wired to
      `staff.*`/`devices.*` permissions as appropriate.
- [ ] M7.1.5 Tests: revoked device denied, unknown device denied, device cannot
      grant permissions, tenant scoping.

---

## M8 - Alembic migration baseline

- [ ] M8.1.1 Alembic environment configured for async engine, settings-driven
      URL and naming conventions from the metadata base.
- [ ] M8.1.2 Foundation migration: `users`, `tenants`, `permissions`, `roles`,
      `role_permissions`, `tenant_memberships`, `devices`, plus indexes and
      constraints from the database specification.
- [ ] M8.1.3 Migration verification test: upgrade from empty to head, downgrade
      to base, and upgrade again, all against `ahia_test`.
- [ ] M8.1.4 Composite foreign keys where the specification calls for
      cross-tenant safety (`(product_id, tenant_id)` style), with tests that a
      cross-tenant reference is rejected by the database itself.

---

## M9 - Catalog: categories, products, images, R2 storage

- [ ] M9.1.1 `category_model.py`, `category_schema.py`, `category_crud.py`,
      `category_service.py`, `category_router.py`.
- [ ] M9.1.2 `product_model.py` with pricing and publication invariants,
      including the rule that money is never floating point.
- [ ] M9.1.3 `product_schema.py` with price, slug and publication validation.
- [ ] M9.1.4 `product_crud.py` with tenant-scoped uniqueness
      (`UNIQUE(tenant_id, slug)`, conditional SKU and barcode uniqueness).
- [ ] M9.1.5 `product_service.py`: `create_product`, `update_product`,
      `deactivate_product`, `publish_product`, `unpublish_product`.
- [ ] M9.1.6 `product_router.py` and `category_router.py`.
- [ ] M9.1.7 `product_image_model.py`, `product_image_crud.py`,
      `product_image_schema.py`, `product_image_service.py`,
      `product_image_router.py`.
- [ ] M9.1.8 Storage capability port plus the R2 adapter in
      `integrations/storage/`, with timeout, circuit breaker, bulkhead,
      bounded retry and typed degradation.
- [ ] M9.1.9 Signed upload flow: server issues scoped, short-lived upload URLs;
      client-supplied object keys are never trusted.
- [ ] M9.1.10 Upload validation: size, MIME type, extension, ownership and
      tenant, all enforced server-side.
- [ ] M9.1.11 Catalog migration and tests, including cross-tenant product
      access denial and price precision tests.
- [ ] M9.1.12 Storage failure test: with R2 unavailable, catalog reads and
      product writes still work and image upload returns a typed degraded
      result.

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
