"""one person, one membership per business

A person can hold at most one *current* membership in a business, and until now only the service said
so. Two requests that pass the service's "are they already a member" test at the same time both insert,
and that is not hypothetical: it is what a double-tapped invitation link does, and it happened while
building the team screen - two rows twelve milliseconds apart, one of them active and the other
promoted, so the owner's "remove" took away one of the two and the person stayed in the business.

A partial unique index rather than a plain one, for two reasons:

- **Removed memberships stay.** They are the audit trail of who had access and when it ended, and a
  plain unique constraint would forbid keeping them.
- **The index is the guard, not the check.** The service still refuses a second membership politely;
  the index is what makes the refusal true when two requests arrive together.

The migration repairs what is already there before it can enforce anything: where a business has more
than one current membership for one person, the oldest is kept and the rest are marked removed, with
the reason recorded in `removed_at` and `updated_at`.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "8dd6119da104"
down_revision: str | None = "56912421e4aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "uq_tenant_memberships_current_member"


def upgrade() -> None:
    # Repair first: the index cannot be created while duplicates exist, and silently dropping rows
    # would destroy access records that somebody may need to explain.
    op.execute(
        """
        UPDATE tenant_memberships AS duplicate
        SET status = 'removed',
            removed_at = COALESCE(duplicate.removed_at, NOW()),
            updated_at = NOW()
        WHERE duplicate.status <> 'removed'
          AND EXISTS (
            SELECT 1
            FROM tenant_memberships AS keep
            WHERE keep.tenant_id = duplicate.tenant_id
              AND keep.user_id = duplicate.user_id
              AND keep.status <> 'removed'
              AND (
                keep.created_at < duplicate.created_at
                OR (keep.created_at = duplicate.created_at AND keep.id < duplicate.id)
              )
          )
        """
    )
    op.execute(
        f"CREATE UNIQUE INDEX {INDEX_NAME} ON tenant_memberships (tenant_id, user_id) "
        "WHERE status <> 'removed'"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
