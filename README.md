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

## Repository layout

```text
AHIA/
  PRODUCT_INITIAL_DEFINITION/   product, domain and scaffold specifications
  TASKS.md                      milestone / sub-milestone / micro-milestone plan
  docs/
    PREREQUISITES.md            toolchain, accounts, environment variables
    ARCHITECTURE.md             layer rules, invariants and the decision log
  backend/                      Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic
  web/                          Next.js + TypeScript          (milestone M19)
  mobile/                       React Native + Expo + TS      (milestone M20)
```

The backend is the only implemented workspace so far. `web/` and `mobile/` are
created by their own milestones; nothing is stubbed in advance.

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
| `TASKS.md` | 21 milestones broken into sub-milestones and micro-milestones, with status |
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

Milestones M0 through M8 are complete and committed: repository and tooling, core
cross-cutting infrastructure, the User vertical slice, authentication and sessions,
tenants, staff administration, the permission model as data, devices, and the versioned
migration baseline, M9 the catalogue is complete - categories, products and product
images end to end, validated, optimized, charged against the tenant's quota, stored under
a server-built key, and resolvable through whichever provider holds the bytes - and M10
the inventory ledger is complete - an append-only movement history, a stock projection
derived from it, and a per-business rule about stock going negative - and M11 customers is
complete: consent that is opt-in, duplicate detection that reports rather than refuses, and
a version that makes two offline edits a conflict instead of a lost one. M12 sales is
complete: a sale, its lines, its payments, the stock it moved and its ledger entry are
written in one transaction or none of them are, a replayed offline operation returns the
receipt it already produced, and cancelling reverses the goods and the money without
deleting the record of either. M13 expenses is complete: recording what a business spent
writes the expense and the ledger entry that accounts for it in one transaction, a mistake is
reversed with a reason and a compensating entry rather than deleted, and the categories
spending reports group by are a declared closed set published to clients. M14 the audit trail is complete: every mutating use case from the catalogue, the stock ledger, the counter, the expenses and the staff administration writes an event in its own transaction, the table is append-only by database trigger, and the trail is readable by the owner and by nobody else. M15 offline synchronization is complete: a device pushes a queue of operations that run through the same use cases as online requests and are applied exactly once, pulls a server-ordered change feed filtered by what it may read, and holds a cursor that only moves forward - all behind `FEATURE_OFFLINE_SYNC`, off by default. M16 the public surface is complete: a business opens a shop at `/shop/{slug}`, strangers read an allowlisted projection of it with no account, invoices are shared through revocable tokens that are never stored, and a product can be shared as a WhatsApp link or a QR code. M17 the reporting surface is complete: daily sales, what sells and what is running out, a CSV export stored in object storage behind a revocable link, in-app notifications addressed to one person, and a scheduled low-stock evaluation that reuses the report rule rather than restating it. 1979 tests pass, all nine gates green,
the nine-stage build gate is green, and the service serves a real flow:
create an account, sign in, create a business, invite a worker, have that worker accept
the invitation with the role they were given, inspect what that role can do, group the
catalogue into categories, add a product, upload its pictures, publish it at an address
a customer can share, and revoke a lost phone - which ends the sessions bound to it.

Cross-tenant integrity is enforced by the database, not only by services: `products`
references `categories(id, tenant_id)` as a composite key, so a product in one business
cannot point at another business's category even if a service forgets to check; product
images reference `products(id, tenant_id)` the same way. The anchor on
`products(id, tenant_id)` is what the sales tables will reference.

Object storage is provider-neutral in the schema as well as in the code: an image row
records `storage_provider` and `storage_key` rather than a column named after a vendor,
so switching providers is a configuration change and an architecture test fails the
build if a provider's name appears in a column or outside the storage boundary.

The schema is versioned: `alembic upgrade head` builds every table from an empty
database, `alembic downgrade base` takes it back, and a test asserts that an
autogenerate run afterwards finds no difference between the migrations and the models
- so a model changed without a migration fails the build rather than a deployment.
Each new table arrives with its own revision. The migration URL comes from the
environment, never from `alembic.ini`.

Delivered beyond the core: a provider-neutral storage capability with both
Cloudflare R2 and Cloudinary adapters selectable by configuration, mandatory
server-side image validation and optimization, per-tenant storage quota accounting
that is safe under concurrent uploads, and authentication whose failures are
indistinguishable across an unknown account, a wrong password and a deactivated
account.

Next: M13, expenses - the other side of the ledger, where money leaves the business and the
same discipline applies. Progress is tracked in `TASKS.md`.
