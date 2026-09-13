"""customers: the people a business sells to

One table. Four decisions are in it rather than in a service.

A phone number is indexed, not unique
    Two people in a household share a number, and one person may be entered twice by
    mistake. The specification asks for duplicate *detection* by phone within a business,
    so the index makes the lookup fast and the service reports a possible duplicate. A
    unique constraint would refuse to record a real customer, and the shopkeeper would
    invent a phone number to get past it - a worse outcome than a duplicate, because the
    data would then be wrong rather than merely repeated. The indexes are partial, because
    a shop that records only names has no phone or email on most rows.

The tenant reference is a plain foreign key
    A customer belongs to one business, unlike a product's category there is nothing
    composite to reference: `customers` is not referenced by a tenant-scoped pair. Every
    lookup takes the tenant, which is the application half of "customer data belongs to the
    tenant".

`version` exists for offline merging
    The specification names customer notes as last-writer-wins, which needs a version to
    compare. Every change increments it, and an update can be checked against the version a
    client was working from, so two edits produce a conflict the client resolves instead of
    one silently discarding the other.

There is no delete path, and no cascade
    A customer is referenced by the sales made to them. Removing the row would leave
    receipts nobody can explain, so deactivation is a column and deletion does not exist.

Revision ID: 8940933a7bca
Revises: c588206d8644
Create Date: 2026-09-13 19:46:25.303364

Generated where autogenerate was sufficient, reviewed before it was applied, and
edited by hand wherever a constraint the database should enforce is not something
autogenerate can infer.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8940933a7bca"
down_revision: str | None = "c588206d8644"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("marketing_opt_in", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_customers_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
    )
    op.create_index(
        "ix_customers_tenant_active_name",
        "customers",
        ["tenant_id", "is_active", "name"],
        unique=False,
    )
    op.create_index(
        "ix_customers_tenant_email",
        "customers",
        ["tenant_id", "email"],
        unique=False,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_index(
        "ix_customers_tenant_phone",
        "customers",
        ["tenant_id", "phone"],
        unique=False,
        postgresql_where=sa.text("phone IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_customers_tenant_phone", table_name="customers")
    op.drop_index("ix_customers_tenant_email", table_name="customers")
    op.drop_index("ix_customers_tenant_active_name", table_name="customers")
    op.drop_table("customers")
