"""row-level security: the tenant filter the database enforces itself

The application already scopes every query by `tenant_id`. This migration is the second line: a
policy that makes a query *which forgot* the filter return nothing instead of everything. It does
not replace the application's scoping, and it is not a substitute for authorization - it is the
reason a mistake in either one stops being silent.

Every in-scope table carries the same column and gets the same policy shape:

    USING (tenant_id = nullif(current_setting('app.current_tenant', true), '')::uuid)
    WITH CHECK (same expression)

`current_setting(..., true)` is the difference between failing safely and failing loudly: a missing
setting returns NULL rather than raising, and `tenant_id = NULL` is never true, so a query outside a
scope returns no rows. The `nullif(..., '')` is not decoration. After a transaction that used
`SET LOCAL` commits, PostgreSQL leaves the placeholder defined with an *empty string* rather than
removing it, and `''::uuid` raises `invalid input syntax for type uuid`. Without `nullif`, the next
request that borrowed that pooled connection would receive a database error where it should have
received no rows - a fail-loud, fail-unsafe outcome, and the exact case the verification tests cover.

`WITH CHECK` is what makes the policy a constraint rather than a filter. Without it, a write could
insert a row belonging to another business and the mistake would only be visible to whoever read it
next.

`FORCE ROW LEVEL SECURITY` is set as well, because a table's owner bypasses its own policies. The
same role runs the migrations and the application in the current deployment, so without FORCE the
policies would bind nobody and this migration would be a comment.

Out of scope, deliberately:

- `tenants`: a public shop resolves a business by slug before any scope exists.
- `users`, `user_sessions`, `devices`: identity is not tenant-scoped - a person exists before any
  business does and may belong to several.
- `tenant_memberships`, `membership_invitations`: resolving membership is what *produces* the
  scope, so it cannot require one.
- `share_links`: a share token is resolved before the business it belongs to is known. Everything a
  link opens is scoped to the link's own business.
- `roles`, `permissions`, `role_permissions`: deployment-wide, filtered by the application.

Revision ID: 56912421e4aa
Revises: e4b5f67bc3fd
Create Date: 2026-09-15 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "56912421e4aa"
down_revision: str | None = "e4b5f67bc3fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The setting the unit of work writes and these policies read. Kept in step with
#: `ahia.core.database.TENANT_SCOPE_SETTING` by a test, because a rename in one place that missed
#: the other would silently unscope every table.
TENANT_SCOPE_SETTING = "app.current_tenant"

#: Every table whose rows belong to exactly one business. Financial history first, then the records
#: that name people, then operations - an order a reader can follow, since all of them receive the
#: same policy.
TENANT_SCOPED_TABLES: tuple[str, ...] = (
    "ledger_entries",
    "audit_events",
    "inventory_movements",
    "payments",
    "sales",
    "sale_items",
    "receipt_counters",
    "expenses",
    "customers",
    "products",
    "product_images",
    "categories",
    "inventory",
    "notifications",
    "report_exports",
    "storefronts",
    "tenant_storage_usage",
    "sync_changes",
    "sync_cursors",
    "sync_operations",
)


def policy_name(table_name: str) -> str:
    """Return the deterministic name of a table's isolation policy.

    Deterministic so that `downgrade` can drop exactly what `upgrade` created, and so that the
    verification test can query `pg_policies` by name rather than by guesswork.
    """
    return f"{table_name}_tenant_isolation"


def tenant_predicate() -> str:
    """Return the predicate every policy uses.

    One function, one shape: a per-table variation would be a place for a policy to be subtly wider
    than the others, and nobody would notice until it leaked. The verification test asserts that the
    deployed policies match this text exactly.
    """
    return f"tenant_id = nullif(current_setting('{TENANT_SCOPE_SETTING}', true), '')::uuid"


def upgrade() -> None:
    predicate = tenant_predicate()
    for table_name in TENANT_SCOPED_TABLES:
        # ENABLE applies the policies to every role except the table's owner; FORCE removes that
        # exemption, which is what makes them apply to the role that runs the migrations too.
        op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{policy_name(table_name)}" ON "{table_name}" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def downgrade() -> None:
    for table_name in TENANT_SCOPED_TABLES:
        op.execute(f'DROP POLICY IF EXISTS "{policy_name(table_name)}" ON "{table_name}"')
        op.execute(f'ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY')
