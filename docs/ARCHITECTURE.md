# AHIA - Architecture

Status: baseline
Enforcement: `backend/import-linter.ini` contracts, run inside `pytest` by
`backend/tests/architecture/test_layer_contracts.py`

This document states the architecture, the invariants that make it hold, and the
decisions that have been taken so far. The specifications in
`PRODUCT_INITIAL_DEFINITION/` are the source of the rules; this document is the
map from those rules to directories and to executable checks.

---

## 1. Layer map

| # | Layer | Directory | May import | Never imports |
|---|---|---|---|---|
| 5 | Transport | `backend/src/ahia/routers/` | services, schemas, core, middleware, errors | crud, models, integrations directly |
| 4 | Services | `backend/src/ahia/services/` | crud, schemas, models, core, integrations ports | routers, middleware, database drivers |
| 3 | Data access | `backend/src/ahia/crud/` | models, core, database | services, routers, schemas |
| 2 | Schemas | `backend/src/ahia/schemas/` | models, core | crud, services, routers |
| 1 | Entities | `backend/src/ahia/models/entities/` | standard library only | everything else, including any framework |
| - | Cross-cutting | `core/`, `middleware/`, `integrations/` | may be imported by any layer | may never import layers 2 through 5 |

```text
        routers
           |
        services
           |
          crud
           |
        entities

schemas sit beside transport as the wire contract.
core sits underneath everything and depends on nothing in the application.
```

### 1.1 Hard invariants

1. A transport handler parses, calls exactly one service method, and returns a
   schema. Any `if` that is not error mapping belongs in a service.
2. A CRUD file owns exactly one entity's persistence. No joins across entities,
   no workflow coordination, no business decisions.
3. A service never imports a database driver and never builds a raw query. It
   expresses transactional intent through the unit of work port.
4. An entity imports nothing but the standard library. No Pydantic, no
   SQLAlchemy, no FastAPI.
5. Wire validation happens only in schemas. Domain invariants live only in
   entities. Database integrity lives only in PostgreSQL constraints.
6. No module-level mutable singletons. Everything is constructed in
   `core/container.py` and injected.
7. Cross-entity coordination lives in a service named after the use case
   (`complete_sale`, `receive_stock`), not after a table.
8. Authorization is enforced in the service layer. A router check is UX, never
   the authority.

### 1.2 The persistence mapping decision

The scaffold specification requires framework-independent entities, so
SQLAlchemy ORM classes are not the domain model. Each CRUD file owns:

- a `*Record` SQLAlchemy declarative class, the persistence representation;
- a mapper between `*Record` and the domain `*Model`;
- query functions that return domain entities, never records.

`UserModel` is the domain source of truth. `UserRecord` is how PostgreSQL
happens to store it. The mapping boundary is the CRUD file and nowhere else.

---

## 2. Cross-cutting modules

| Module | Responsibility | Notes |
|---|---|---|
| `core/config.py` | typed settings and the feature flag registry | the only module that may read the environment |
| `core/errors.py` | error hierarchy, correlation ID, external envelope mapping | internal detail never crosses the boundary |
| `core/logging.py` | structured logging and redaction | call sites never redact by hand |
| `core/resilience.py` | timeout, circuit breaker, bulkhead, retry with jitter, typed fallback | outbound boundaries only |
| `core/security.py` | Argon2id hashing, JWT, token generation | no hand-rolled cryptography |
| `core/database.py` | async engine, session lifecycle, unit of work port | the only place a database driver is constructed |
| `core/tenant_context.py` | authorized tenant context | requested tenant is a hint, membership is proof |
| `core/permissions/` | permission registry and role bundles | data-driven, one module per domain |
| `core/container.py` | composition root | constructs every dependency once |
| `middleware/` | correlation, security headers, rate limit, error handling | registered on the application, not in routers |
| `integrations/` | provider adapters (R2, WhatsApp) | services depend on capability ports, not providers |

### 2.1 Resilience policy

Resilience primitives are applied at outbound failure boundaries only:
third-party HTTP APIs, object storage, LLM providers, payment gateways,
messaging, caches and remote databases.

Every outbound dependency gets an explicit timeout, a circuit breaker with one
instance per dependency, a bulkhead concurrency limit, bounded retry with
exponential backoff and jitter for idempotent operations only, a typed
degradation result, and observability on state changes.

A circuit breaker is never placed around an in-process call between our own
layers. A service calling its own repository is not a failure domain.

### 2.2 Feature flags

Flags are declared once in `core/config.py` with a name, type, default,
description, date added and removal condition. Flag state is logged at startup,
one INFO line per flag. Flags are booleans or enums, never free-form strings or
numeric thresholds, and never nested.

Authentication, authorization, input validation, rate limiting and logging are
never gated by a flag. There is no `FEATURE_AUTH_ENABLED`.

---

## 3. Domain model rules that affect the architecture

These come from the database and domain specification and constrain the code,
not just the schema.

- PostgreSQL is authoritative. SQLite is never a development substitute for the
  server database.
- Every tenant-owned record carries `tenant_id` explicitly.
- Identifiers are UUIDs; money is `NUMERIC`, never floating point.
- Inventory is a movement ledger. The quantity on hand is a projection. A
  quantity cannot change without a movement.
- Transactional facts (sales, payments, movements, expenses) are merged by
  operation semantics and idempotency, never by naive last-write-wins.
- Devices carry identity for sync, audit and security. They never grant
  permission.
- Public sharing uses stable slugs and non-guessable tokens and never bypasses
  private authorization.
- Historical financial and inventory records are appended to or compensated,
  never deleted. Sale cancellation writes compensating events.
- Core operations must survive the failure of optional providers: storage,
  AI, SMS, email and payment gateways.

---

## 4. Decision log

New decisions are appended here before implementation proceeds. Each entry
states the decision, the reasoning and the consequence.

### ADR-0001 - Pure domain entities, persistence mapping in CRUD

Decision: entities are standard-library dataclasses; SQLAlchemy declarative
classes live in CRUD as `*Record` persistence representations with explicit
mapping.

Reasoning: the scaffold specification requires framework-independent entities,
and the preset forbids an entity importing an ORM. Making `class UserModel(Base)`
the domain object would violate both.

Consequence: every entity pays a small mapping cost. In exchange, domain rules
are testable without a database, and the persistence representation can change
without touching business logic.

### ADR-0002 - Cloudflare R2 for object storage, behind a storage port

Decision: R2 is the object store. Services depend on an injected storage
capability; only `integrations/storage/r2_client.py` knows R2 specifics.

Reasoning: recorded in `docs/PREREQUISITES.md` section 8, including the
Cloudinary comparison, the egress cost shape for public storefront images and
the S3-compatible exit path.

Consequence: image transformation features Cloudinary provides for free must be
produced as derived variants at upload time. The read path never depends on a
third-party transformation service.

### ADR-0003 - No generic repository, no generic utility module

Decision: one CRUD file per entity; no `repository.py`, no `utils.py`, no
`helpers.py`, no `common.py`. A small unit of work abstraction is permitted only
for coordinating atomic cross-entity use cases.

Reasoning: explicit persistence ownership keeps tenant scoping auditable, and
the preset forbids dumping grounds.

Consequence: a new entity adds five files, and cross-entity workflows get a
service named after the use case.

### ADR-0004 - UUID primary keys, UUIDv7 where the driver allows it

Decision: internal identifiers are UUIDs. Public artifacts additionally carry a
slug or an opaque public token.

Reasoning: UUIDs do not leak record counts and compose across offline clients
that must generate identifiers before synchronization. Public tokens prevent
enumeration of shareable but sensitive resources.

### ADR-0005 - `X-Correlation-ID` as the single request correlation header

Decision: the transport boundary reads `X-Correlation-ID` when it matches the
allowed format, otherwise generates one. The value is attached to the request
context, included in every log line and returned in the standard error envelope.

Reasoning: one identifier is the entire bridge between a client complaint and
an engineer's log search.

### ADR-0006 - ASCII-only engineering artifacts

Decision: source, comments, docstrings, log messages, error strings, test names,
configuration, CLI output and commit messages are ASCII only. No emojis, no
decorative symbols, no ASCII art. Runtime user data is explicitly out of scope
and may contain any Unicode a trader types.

Reasoning: the preset requires it, and it keeps every terminal, log pipeline and
diff viewer identical.

Consequence: the product name is written `AHIA` in engineering artifacts and may
appear with its diacritic only in user-facing content. `scripts/check_ascii.py`
enforces the rule with a scoped allowlist for intentional Unicode fixtures.

### ADR-0007 - One reproducible developer gate

Decision: `make check` runs lint, format check, type check, the ASCII guard, the
unit and integration tests, the architecture contracts, the secret scan and the
dependency audit. CI runs the same command.

Reasoning: a rule that cannot be reproduced locally with one command is a rule
that will be skipped.
