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
migration baseline. M9 is under way: categories are complete, and products exist as an
entity, a transport contract and a table with decimal money, per-tenant codes and the
composite cross-tenant anchors the specification calls for. 1199 tests pass, the
nine-stage build gate is green, and the service serves a real flow: create an account,
sign in, create a business, invite a worker, have that worker accept the invitation with
the role they were given, inspect what that role can do, group the catalogue into
categories, and revoke a lost phone - which ends the sessions bound to it.

Cross-tenant integrity is enforced by the database, not only by services: `products`
references `categories(id, tenant_id)` as a composite key, so a product in one business
cannot point at another business's category even if a service forgets to check. The
same anchor on `products(id, tenant_id)` is what the sales tables will reference.

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

Next in M9: the product use cases and their endpoints - create, edit, publish,
unpublish, deactivate - then product images against R2 or Cloudinary. Progress is
tracked in `TASKS.md`.
