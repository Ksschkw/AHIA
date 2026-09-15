# Row-Level Security: rollout plan

**Status: planned, not enabled.** The application enforces tenant scoping in every query today; this
document is the plan for the *second* line - the database refusing to return another business's rows
even when a query forgets to filter. It is written before the change because the change is what makes
a mistake in the application stop being silent.

Nothing here is enabled yet. When it is, this document is the record of what was turned on, in what
order, and how it was verified.

---

## 1. What RLS adds, and what it does not replace

The application scopes every read by `tenant_id`, and the architecture tests assert that repositories
touch one entity's storage and that services receive an authorized context. RLS does not replace any of
that. It closes one specific gap: a query that *forgets* the filter currently returns every business's
rows, and no test notices until somebody sees the data.

With RLS enabled, that same query returns nothing. A missing scope is a failure, and it fails closed.

## 2. The mechanism

**A session variable carries the business.** Every transaction that touches business data begins with

```sql
SET LOCAL app.current_tenant = '<tenant uuid>';
```

`SET LOCAL` is transaction-scoped, which is what a connection pool requires: a pooled connection
carries no scope from one request into the next, because the setting evaporates at commit.

**Every policy is the same shape.**

```sql
USING (tenant_id = current_setting('app.current_tenant', true)::uuid)
```

`current_setting(..., true)` returns NULL when the setting is absent rather than raising, and
`tenant_id = NULL` is never true - so a query outside a scope returns no rows instead of erroring and
instead of returning everything. The `true` is the difference between failing closed and failing
loudly-and-unsafely; both are checked in the tests.

**The scope is request-scoped state, like the correlation ID.** A context variable set by the
authenticated-context dependency (and by the job and public-read paths, below) is read by the unit of
work when it opens a transaction. Application code therefore does not pass a tenant into the database
layer by hand: the same authorized context that decides *whether* a request may proceed also decides
*which business's rows exist* for it.

## 3. Tables in scope, and in what order

Order is by how bad a leak would be, and each step is independently revertible.

| Order | Table | Why it is here |
|---|---|---|
| 1 | `ledger_entries` | The financial history, append-only, and the one table a leak would be unrecoverable in. |
| 2 | `audit_events` | Who did what in a business. A leak is a privacy incident about named people. |
| 3 | `inventory_movements` | Every stock movement, including the notes a person wrote. |
| 4 | `payments` | Money in and out, with references. |
| 5 | `sales`, `sale_items`, `receipt_counters` | A business's trading and its customers' baskets. |
| 6 | `expenses` | Spending, including the descriptions people type. |
| 7 | `customers`, `products`, `product_images`, `categories`, `inventory` | The catalogue and the people it is sold to. |
| 8 | `notifications`, `report_exports`, `share_links`, `storefronts`, `tenant_storage_usage` | Operational records. |

**Out of scope, deliberately:**

- `tenants` - a public read resolves a shop by its slug before any scope exists, and the row holds the
  business's own name, slug and settings. Enabling RLS here would break every public address.
- `users`, `user_sessions`, `devices`, `membership_invitations` - identity is not tenant-scoped: a
  person exists before any business does and may belong to several.
- `permissions`, `roles`, `role_permissions` - the registry is deployment-wide, with per-business
  custom roles scoped by a column the application filters.
- `alembic_version`, and every table the migrations own.

## 4. Consequence: reads that span businesses need two transactions

Three paths legitimately begin without a scope, and each resolves a business first and then reads its
data **in a new transaction** with the scope set:

1. **The public shop** (`/shop/{slug}`): resolve the tenant by slug, then read the storefront and the
   catalogue inside that tenant's scope.
2. **A shared invoice or report** (`/share/{token}`): resolve the link, then read the sale and its
   lines inside the link's tenant scope.
3. **The scheduled evaluator**: list active tenants, then evaluate each one inside its own scope -
   one transaction per business, which is also what makes a failure in one business not affect the
   next.

A read that spans businesses *inside* one transaction cannot exist under RLS. That is not a
limitation to work around; it is the property being bought, and the three cases above are each already
written as "resolve, then read within" - they need the scope set at the right point, not a redesign.

## 5. Verification, per table

Each rollout step lands with the same three assertions, and a step is not complete until all three
hold:

1. **Without a scope, a query returns nothing.** Read from the table with no `app.current_tenant` set
   and assert zero rows, with rows present in the database.
2. **With a scope, a query returns only that business's rows.** Two businesses' rows exist; the scope
   of one returns exactly its own.
3. **A cross-tenant read by identifier returns nothing.** Ask for the other business's row by its
   primary key inside the first business's scope, and assert nothing comes back.

The application suite must also stay green, because a policy that breaks a legitimate read is a policy
that will be turned off in an incident.

## 6. Operational notes

- **The application account must not own the tables.** A table's owner bypasses its own policies unless
  `FORCE ROW LEVEL SECURITY` is set. The migration sets it, so the policies bind the application even
  though the same role runs the migrations.
- **Migrations run as the owner and must therefore be explicit.** A data migration that touches a
  scoped table needs either the scope set or `ALTER TABLE ... NO FORCE ROW LEVEL SECURITY` for the
  duration, and either way it is a deliberate line in the migration rather than an accident.
- **A connection is scoped by its transaction, never by its lifetime.** `SET LOCAL` is what makes that
  true; `SET` (session-scoped) would leak one request's business into the next request that borrowed
  the connection, which is the exact failure this work exists to prevent.
- **Monitoring.** The metrics endpoint does not expose the scope, and no log line carries it; a
  failed scope shows up as empty result sets rather than as an error, so the health check exercises a
  scoped read on every run.

## 7. Rollback

Each step is reverted by dropping the policies and `NO FORCE ROW LEVEL SECURITY` for that table, which
returns the behaviour to "the application filters, and the database does not". The migration for each
step has a `downgrade` that does exactly that.
