# AHIA

AHIA is a multi-tenant, offline-first business operating system for informal
commerce, starting with electronics and appliance traders at Alaba
International Market, Lagos.

It does not try to replace WhatsApp, cash or bank transfers. It becomes the
operational system around them: storefront, products, inventory, sales,
payments, customers, and the synchronization that keeps several phones and
several workers looking at the same business state.

The full product definition lives in `PRODUCT_INITIAL_DEFINITION/`. Those
documents are the specification of record. This README is the map.

---

## Live

| Surface | Address |
|---|---|
| Web application | https://useahia-hazel.vercel.app |
| Android build | https://github.com/Ksschkw/AHIA/releases/latest |
| API | https://p01--ahia-api--qw5xhkblp8hy.code.run |

---

## Repository layout

```text
AHIA/
  PRODUCT_INITIAL_DEFINITION/   product, domain and scaffold specifications
  TASKS.md                      milestone / sub-milestone / micro-milestone plan
  docs/
    PREREQUISITES.md            toolchain, accounts, environment variables
    ARCHITECTURE.md             layer rules, invariants and the decision log
  backend/                      Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic
  web/                          Next.js + TypeScript, server-rendered storefront and app
  mobile/                       React Native + Expo, offline-first Android client
```

All three workspaces are implemented and deployed. The backend owns the domain
and the data. The web and mobile clients are both consumers of the same API, and
neither restates a business rule: a rule lives in one service and both clients
obey it.

---

## The five layers

Every entity is expressed as a vertical slice through five layers, one file per
entity per layer. Dependencies point inward only.

| # | Layer | Directory | Responsibility | May import |
|---|---|---|---|---|
| 5 | Transport | `routers/` | Parse request, call one service, shape response, map errors to status codes | services, schemas, errors |
| 4 | Services | `services/` | All business logic, orchestration, transactions, authorization | crud, schemas, entities, errors, core |
| 3 | Data access | `crud/` | Persistence for exactly one entity, row-to-entity mapping | entities, errors, core (db driver) |
| 2 | Schemas | `schemas/` | Transport contracts and validation at the edge | entities, errors |
| 1 | Entities | `models/entities/` | Pure domain types and invariants, framework-free | nothing |

Cross-cutting modules (`core/`, `middleware/`, `integrations/`) may be imported
by any layer. They never import application layers.

```text
routers  ->  services  ->  crud  ->  entities
   |             |          |
schemas       schemas   database driver
```

The hard invariants, the reasoning and the recorded decisions are in
`docs/ARCHITECTURE.md`. They are enforced by `import-linter` contracts that run
inside the test command, so an outward import fails the ordinary test run.

---

## Commands

All developer operations go through the `Makefile`, which is a thin wrapper over
real scripts. There is exactly one command that must be green before any commit.

```bash
make setup      # create backend/.venv and install the locked dependencies
make check      # lint, format check, types, ASCII guard, tests, architecture,
                # secret scan, dependency audit - the pre-commit gate
make test       # pytest with coverage
make lint       # ruff check
make format     # ruff format
make typecheck  # mypy
make arch       # import-linter contracts
make secrets    # gitleaks over the working tree
make audit      # pip-audit dependency vulnerability scan
make run        # uvicorn ahia.main:app --reload
make migrate    # alembic upgrade head
make revision   # alembic revision --autogenerate -m "message"
```

`make check` is the same gate CI runs. A red build must be reproducible locally
with one command.

---

## Documentation index

| Document | Contents |
|---|---|
| `docs/PREREQUISITES.md` | toolchain versions, external accounts, the complete environment variable contract, feature flag register, secret rotation paths, the object storage decision |
| `docs/ARCHITECTURE.md` | the five layers mapped onto directories, invariants, cross-cutting rules, decision log |
| `docs/RUNBOOK.md` | deployment, migrations, rollback, secret rotation, breaker trips, tracing a request by correlation ID, and the incidents this system actually has |
| `docs/HARDENING.md` | rate limiting, metrics, Row-Level Security and the error-reporting split, plus what is not in place |
| `docs/RLS_ROLLOUT.md` | what Row-Level Security enforces, where the scope is bound, and what was verified - and what was not |
| `docs/LOAD_SMOKE.md` | the recorded load smoke test on the sale endpoint: the numbers, the environment, and what they do and do not say |
| `TASKS.md` | 27 milestones broken into sub-milestones and micro-milestones, with status |
| `PRODUCT_INITIAL_DEFINITION/AHIA_PROJECT_SPECIFICATION.md` | product definition and journeys |
| `PRODUCT_INITIAL_DEFINITION/AHIA_DATABASE_AND_DOMAIN_SPEC.md` | entities, constraints, indexes, sync semantics |
| `PRODUCT_INITIAL_DEFINITION/AHIA_BACKEND_SCAFFOLD_SPEC.md` | backend conventions and scaffold contract |

---

## Working agreements

- One micro-milestone is one commit. Nothing is committed that fails
  `make check`.
- Every commit is authored by `Ksschkw <kookafor893@gmail.com>`. No co-author
  trailers.
- Engineering artifacts are ASCII only: source, comments, docstrings, log
  messages, error strings, test names, configuration, CLI output and commit
  messages. No emojis, no decorative symbols, no ASCII art. Runtime business
  data is unaffected and may contain any Unicode the user supplies.
- Secrets are never committed. `.env.example` holds placeholder names only.
- Security controls are never behind a feature flag. Authentication,
  authorization, validation and rate limiting are always on.

---

## Current status

M0 through M26 are complete: 27 milestones, each broken into sub-milestones that
landed as individual commits behind one green gate.

**Backend.** The five layers with their enforced import contracts; typed
configuration and the feature flag register; an error hierarchy with correlation
IDs and an external envelope that leaks nothing; structured logging with
infrastructure-level redaction; timeout, breaker, bulkhead, bounded retry and a
typed fallback on every outbound dependency; authentication with rotating refresh
tokens, constant-time failure behaviour and errors that do not disclose whether an
account exists; tenants, memberships, permissions as data, and devices; the
catalogue with categories, products and provider-neutral image storage; the
inventory ledger and the projection derived from it; sales, payments and expenses
written in a single transaction; an audit trail that is append-only by database
trigger; offline synchronisation with idempotent operations and a cursor-based
change feed; the public storefront, revocable share links and WhatsApp handover;
reports, low-stock alerts and notifications; Row-Level Security on every
business-owned table; and the metrics, rate limiting and deployment pipeline that
carry it.

**Web.** A server-rendered storefront, so a customer on a market connection reads
the shop rather than watching a spinner fill in a page already paid for, and an
authenticated application shell with a bottom bar on a phone and a side rail on a
desk. The trader's screens cover the shelf, sales, the catalogue as a nested
family tree, the price book, the list workbench, dispatch and a storefront studio.

**Mobile.** An offline-first Android client that installs from a GitHub release. A
local store mirrors the catalogue for instant first paint, and a sale made with no
signal queues in a durable outbox that drains when the connection returns without
booking the same sale twice.

The suite runs past two thousand tests, of which the storage, quota, database and
migration suites run against real PostgreSQL.

Cross-tenant integrity is enforced by the database, not only by services:
`products` references `categories(id, tenant_id)` as a composite key, so a product
in one business cannot point at another business's category even if a service
forgets to check; product images reference `products(id, tenant_id)` the same way.
The anchor on `products(id, tenant_id)` is what the sales tables reference.

Object storage is provider-neutral in the schema as well as in the code: an image
row records `storage_provider` and `storage_key` rather than a column named after
a vendor, so switching providers is a configuration change, and an architecture
test fails the build if a provider's name appears in a column or outside the
storage boundary.

The schema is versioned: `alembic upgrade head` builds every table from an empty
database, `alembic downgrade base` takes it back, and a test asserts that an
autogenerate run afterwards finds no difference between the migrations and the
models, so a model changed without a migration fails the build rather than a
deployment. Each new table arrives with its own revision, and the migration URL
comes from the environment rather than from `alembic.ini`.

Deferred by design, not forgotten: AI forecasting, a community module, a supplier
marketplace, fleet tracking, automated bank integrations, the full WhatsApp
Business API, and a native desktop shell.

---

## License

Source-available under the [Elastic License 2.0](LICENSE).

You may read this code, run it, copy it, modify it and share it. You may not offer
it to third parties as a hosted or managed service, and you may not remove the
license or copyright notices. The exact terms are in `LICENSE`.

This is deliberately not an open-source license. The web and mobile applications
are separate works under the same terms, and the Android build published on the
releases page is distributable as-is.
