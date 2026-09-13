"""categories: a business's own grouping of products

One table, created in this revision rather than in the baseline because it belongs to
the catalogue milestone: a category exists to group products, and it arrives with the
slice that manages it.

Two decisions are encoded in the constraints.

Uniqueness is composite and per tenant
    UNIQUE(tenant_id, slug). "Drinks" means something in every shop, so two businesses
    may each have one; one business may not have two, however the name was typed. The
    database enforces it, so two simultaneous creates cannot produce the duplicate a
    read-then-write check in the service would miss.

The category belongs to a business
    tenant_id references tenants.id, so a category cannot be created for a business
    that does not exist. There is no cascade: a business is closed rather than deleted.

What is deliberately absent: an is_active column, and any delete path. The
specification gives a category no state, and what happens to a product whose category
is removed is a question the products table answers - the foreign key from products to
categories, and the rule for deleting a referenced category, arrive in the revision
that creates products.

Revision ID: ab9af68b0824
Revises: ae15ce60c835
Create Date: 2026-09-13 16:12:01.144434

Generated where autogenerate was sufficient, reviewed before it was applied, and
edited by hand wherever a constraint the database should enforce is not something
autogenerate can infer.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ab9af68b0824"
down_revision: str | None = "ae15ce60c835"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_categories_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("tenant_id", "slug", name=op.f("uq_categories_tenant_id_slug")),
    )
    op.create_index(op.f("ix_categories_tenant_id"), "categories", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_categories_tenant_id"), table_name="categories")
    op.drop_table("categories")
