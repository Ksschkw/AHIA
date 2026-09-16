# Row-Level Security: enabled

**Status: enabled.** The migration `56912421e4aa` creates one policy per business-owned table and
forces it on the tables' owners. The application binds the business for every transaction through the
unit of work. This document is the record of what was turned on, where the application binds it, and
what was verified - including what was not.

The application scopes every read by `tenant_id`, and the architecture tests assert that repositories
touch one entity's storage and that services receive an authorized context. RLS does not replace any
of that. It closes one specific gap: a query that *forgets* the filter used to return every
business's rows, and no test noticed until somebody saw the data. With the policies on, that same
query returns nothing.

---

## 1. The mechanism

**A session variable carries the business.** Every transaction that touches business data begins with

```sql
SELECT set_config('app.current_tenant', '<tenant uuid>', true);
```

`set_config(..., true)` is the function form of `SET LOCAL`, used because `SET` cannot take a bind
parameter. The transaction-scoped form is what a connection pool requires: a pooled connection
carries no scope from one request into the next, because the setting stops applying at commit.

**Every policy is the same shape.**

```sql
USING (tenant_id = nullif(current_setting('app.current_tenant', true), '')::uuid)
WITH CHECK (same expression)
```

**The `nullif` is a correction to the original plan, and it is load-bearing.** The plan said that
`current_setting(..., true)` returns NULL when the setting is absent. That is true only for a setting
that has never been used in the session. After a transaction that used `SET LOCAL` commits,
PostgreSQL leaves the placeholder *defined with an empty string*, so the naive predicate becomes
`tenant_id = ''::uuid`, which raises `invalid input syntax for type uuid: ""` - a database error on
the next request that borrowed that pooled connection, where the correct answer is "no rows". Both
cases now mean the same thing: no scope, and therefore no rows. The verification includes a test that
runs two transactions on one connection specifically to keep this true.

**`WITH CHECK` makes the policy a constraint, not a filter.** Without it, a scoped write could still
create a row belonging to another business.

**`FORCE ROW LEVEL SECURITY` makes it apply to the table's owner.** A table's owner bypasses its own
policies otherwise, and the same role runs the migrations and the application in this deployment.

**The scope is request-scoped state, like the correlation ID.** `core/tenant_scope.py` holds it in a
context variable, and `SqlAlchemyUnitOfWork.__aenter__` writes it into the transaction it opens.
Application code therefore never passes a tenant into the database layer by hand: the same authorized
context that decides *whether* a request may proceed also decides *which business's rows exist* for
it.

---

## 2. Where the application binds the scope

Three entry points, and no others:

| Path | Where the binding happens | Why there |
|---|---|---|
| Every tenant-scoped request | `TenantService.resolve_tenant_context`, which is what produces the `TenantContext` every route depends on | One place decides both authorization and scope, so a route cannot be authorized and unscoped |
| The scheduled low-stock evaluator | `LowStockAlertEvaluator.evaluate_tenant`, inside `tenant_scope(...)` | There is no authenticated caller in a job; the business comes from the tenant list, and the scope is restored on exit so the next business in the loop starts clean |
| The public shop and share links | `StorefrontService.read_public_storefront`, `read_public_product`, `ShareLinkService.read_shared_invoice`, `_read_shared` | A public read begins before any business is known, so it resolves first and then reads within the resolved business's scope |

Everything else runs with whatever scope is in context, and a missing scope is a refusal, not a leak.

---

## 3. Tables in scope

`ledger_entries`, `audit_events`, `inventory_movements`, `payments`, `sales`, `sale_items`,
`receipt_counters`, `expenses`, `customers`, `products`, `product_images`, `categories`, `inventory`,
`notifications`, `report_exports`, `storefronts`, `tenant_storage_usage`, `sync_changes`,
`sync_cursors`, `sync_operations`.

The rollout plan ordered these by how bad a leak would be, and the implementation collapsed the order
into one migration because every table receives the same policy from the same function: there is no
per-table decision left to stage. The three sync tables were **added** to the plan's list - they are
business-owned rows written and read with a tenant context, and leaving them out would have left a
hole of exactly the shape the rest of this work closes.

**Out of scope, deliberately:**

- `tenants` - a public read resolves a shop by its slug before any scope exists.
- `users`, `user_sessions`, `devices` - identity is not tenant-scoped: a person exists before any
  business does and may belong to several.
- `tenant_memberships`, `membership_invitations` - resolving a membership is what *produces* the
  scope, so it cannot require one.
- `share_links` - **moved out of scope during implementation.** The plan had it scoped, but a share
  token has to be resolved before the business it belongs to is known; that is what a share link is.
  Everything a link opens is read inside the link's own business scope, so a token still cannot reach
  another business.
- `roles`, `permissions`, `role_permissions` - the registry is deployment-wide, with per-business
  custom roles filtered by the application.
- `alembic_version`, and every table the migrations own.

The exclusions are asserted: a test fails if a policy appears on any of these tables, or if RLS is
enabled on one of them.

---

## 4. Consequence: reads that span businesses need two transactions

A read that spans businesses *inside* one transaction cannot exist under RLS. That is not a
limitation to work around; it is the property being bought. The three paths that legitimately start
without a scope are each written as "resolve, then read within", and each uses two transactions:

1. **The public shop** (`/shop/{slug}`): resolve the tenant by slug, then read the storefront, the
   catalogue and each product's stock inside that tenant's scope.
2. **A shared invoice or report** (`/share/{token}`): resolve the link, then read the sale, its lines
   or the export inside the link's tenant scope.
3. **The scheduled evaluator**: list active tenants, then evaluate each one inside its own scope -
   one transaction per business, which is also what makes a failure in one business not affect the
   next.

---

## 5. Verification

`tests/migrations/test_row_level_security.py` rebuilds the schema from the migration and makes every
behavioural assertion through a dedicated unprivileged role, `ahia_rls_probe`: login, no superuser,
no bypass, granted exactly what the application is granted. This matters, because the ordinary test
connection is a superuser locally and *superusers bypass RLS regardless of `FORCE`* - an assertion
made as the owner would have passed with no policy present at all. The probe role is created by the
test with a random password that is never written to a file, and re-created with a new password on
each run.

What actually holds today:

- **The three per-table assertions**, for `customers`, `categories` and `ledger_entries`: with no
  scope a query returns zero rows while the rows exist; with a scope it returns exactly that
  business's rows; a read of the other business's row by primary key returns nothing.
- **A write outside a scope is refused**, and leaves no row behind.
- **A pooled connection carries no scope into the next transaction** - the `nullif` case above.
- **The application path fails closed**: a repository read through the unit of work, as the probe
  role, raises not-found without a scope and finds the row with one. This is the assertion that the
  unit of work is what binds the scope.
- **Every one of the twenty scoped tables** has RLS enabled, forced, exactly one permissive policy
  for all commands, with identical read and write predicates containing the setting name.
- **Every deliberately unscoped table** has no policy and RLS disabled.
- **The setting name agrees** between the unit of work and the policies.

Not verified, and stated rather than implied:

- The behavioural three-assertion test runs on three representative tables, not on all twenty. The
  remaining seventeen have the identical predicate and are asserted structurally - enabled, forced,
  one policy, same expression, on a table that has a `tenant_id` column. What that leaves untested is
  a table whose *rows* behave unusually under the policy, which would require per-table fixtures for
  every one of them; the risk is recorded here rather than hidden behind a green suite.
- The suite as a whole runs as the owning role, which bypasses policies. RLS is therefore not
  exercised by the ordinary CRUD and router tests - those prove the application filters correctly,
  which was already true before this work.
- No production database has been checked yet. The migration is applied to the local test database
  only; `M18.1.5` is where deployment wiring lands.

---

## 6. Operational notes

- **The application account must not own the tables**, and the migration does not rely on that: it
  sets `FORCE`, so the policies bind the role that runs the migrations too.
- **Migrations run as the owner and must therefore be explicit.** A data migration that touches a
  scoped table needs either the scope set or `ALTER TABLE ... NO FORCE ROW LEVEL SECURITY` for the
  duration. DDL - creating a table or a policy - is unaffected.
- **A connection is scoped by its transaction, never by its lifetime.** `SET LOCAL` is what makes
  that true; a session-scoped `SET` would leak one request's business into the next request that
  borrowed the connection.
- **A new business-owned table needs a policy in the same migration that creates it**, and its name
  added to `TENANT_SCOPED_TABLES` in the verification test. A table with a `tenant_id` column and no
  policy is a table where a forgotten filter is silent again.
- **Monitoring.** The metrics endpoint does not expose the scope and no log line carries it. A failed
  scope shows up as empty result sets rather than as an error, so the symptom to look for is "the API
  answers 200 with an empty list".

---

## 7. Rollback

The migration's `downgrade` drops each policy and runs `NO FORCE` and `DISABLE ROW LEVEL SECURITY`
for every table, returning the behaviour to "the application filters, and the database does not". It
is verified by `tests/migrations/test_migration_baseline.py`, which takes the whole chain down to an
empty database and back up again.
