"""expenses, and the table spending reports read

The milestone where money leaving the business becomes a first-class record. Until now the
ledger could record an expense entry, but nothing in the product wrote one: this revision
adds the table that records what the money was spent on, who recorded it and when, so the
ledger entry has something to attribute itself to.

There is no delete path, and none is added by a cascade
    An expense is financial history: the money left the business and a ledger entry recorded
    it. A mistaken expense is reversed - `reversed_at` and `reversal_reason` - which leaves
    the original amount readable and writes a compensating ledger entry. Nothing in this
    revision deletes a row, and `expense_crud` deliberately offers no function that could.

An offline operation is recorded once
    `UNIQUE(tenant_id, operation_id) WHERE operation_id IS NOT NULL` is what makes an expense
    queued on a phone safe to resend: the second arrival is recognised as the first and the
    business does not pay twice for one bag of cement.

The category column holds a value from a closed set, and the database does not list it
    The vocabulary lives in `models/entities/expense_category` and is validated by the entity.
    A CHECK constraint listing categories here would be a second copy of that vocabulary, and
    the copy in SQL is the one nobody remembers to change - adding a category would then fail
    at run time, in production, on the first expense somebody records. The column length is
    the one place the two must agree, and a test asserts every category fits it. This is the
    same decision the sales and ledger tables make for their status columns.

Two constraints are stated here because an UPDATE must not be able to bypass them
    `amount > 0`: a spending report sums this column, so a negative row would reduce a total
    it claims to report. `(reversed_at IS NULL) = (reversal_reason IS NULL)`: a reversal is a
    moment and a reason together, and either one alone is a row nobody can act on.

Reads are indexed by what a spending report asks
    `(tenant_id, incurred_at)` for a period, `(tenant_id, category, incurred_at)` for a
    heading within a period. Declared with the table rather than discovered from a slow
    report later.

Revision ID: 4cba683657a9
Revises: cc5497582879
Create Date: 2026-09-14 08:30:33.606689

Generated where autogenerate was sufficient, reviewed before it was applied, and
edited by hand wherever a constraint the database should enforce is not something
autogenerate can infer.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4cba683657a9"
down_revision: str | None = "cc5497582879"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "expenses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("payment_method", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("incurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("operation_id", sa.Uuid(), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversal_reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # The entity's amount rule, stated where neither an UPDATE nor a script can bypass it.
        sa.CheckConstraint("amount > 0", name=op.f("ck_expenses_expense_amount_is_positive")),
        # A reversal is a moment and a reason, together.
        sa.CheckConstraint(
            "(reversed_at IS NULL) = (reversal_reason IS NULL)",
            name=op.f("ck_expenses_expense_reversal_is_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_expenses_actor_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"], name=op.f("fk_expenses_device_id_devices")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_expenses_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expenses")),
    )
    op.create_index(
        "ix_expenses_tenant_category_incurred",
        "expenses",
        ["tenant_id", "category", "incurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_expenses_tenant_incurred", "expenses", ["tenant_id", "incurred_at"], unique=False
    )
    op.create_index(
        "uq_expenses_tenant_id_operation_id",
        "expenses",
        ["tenant_id", "operation_id"],
        unique=True,
        postgresql_where=sa.text("operation_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_expenses_tenant_id_operation_id",
        table_name="expenses",
        postgresql_where=sa.text("operation_id IS NOT NULL"),
    )
    op.drop_index("ix_expenses_tenant_incurred", table_name="expenses")
    op.drop_index("ix_expenses_tenant_category_incurred", table_name="expenses")
    op.drop_table("expenses")
