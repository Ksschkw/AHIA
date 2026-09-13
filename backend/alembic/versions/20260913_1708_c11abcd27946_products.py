"""products: what a business sells, and the anchor that keeps tenants apart

Two changes, one subject: the catalogue's central table, and the constraint that makes
its cross-tenant references enforceable.

The anchor on categories comes first, because the foreign key needs it
    `UNIQUE(id, tenant_id)` on `categories` is what allows a composite reference to
    `categories(id, tenant_id)`. Without it the reference is illegal, so this revision
    adds the anchor before it creates the table that uses it. This is the item M8.1.4
    deferred: the anchor belongs with the table whose references need it.

The category reference from products is composite
    `(category_id, tenant_id)` references `categories(id, tenant_id)`, so the database
    refuses a product in one business that points at another business's category. A
    plain foreign key on `category_id` cannot express that: the identifier is unique and
    therefore valid in every tenant. `(id, tenant_id)` on products is the same anchor
    for the tables that will reference products.

Prices are NUMERIC(18,2) and stock thresholds NUMERIC(18,3)
    Money is never a float in this schema. The driver returns Decimal, so a price read
    back is the price that was stored and a shop's books reconcile.

UNIQUE(tenant_id, slug) always applies; SKU and barcode are unique only where present
    A slug is derived from the name, so two products in one business cannot share one.
    SKU and barcode are optional, and a plain unique constraint would let a business
    that does not use them store exactly one product - the second null would collide.
    The partial unique indexes express "unique when set", which is the rule the
    specification asks for.

`public_token` is unique and nullable
    PostgreSQL allows any number of nulls in a unique index, so every unpublished
    product holds no token and no two published products can share one.

There is no index on `tenant_id` alone: the composite unique index on `(tenant_id,
slug)` leads with tenant_id and therefore already serves tenant-scoped listings and the
foreign key's own check. The one extra index is `(tenant_id, category_id)`, which serves
both the composite foreign key's check and the storefront's "products in this category"
query.

Revision ID: c11abcd27946
Revises: ab9af68b0824
Create Date: 2026-09-13 17:08:55.072498

Generated where autogenerate was sufficient, reviewed before it was applied, and
edited by hand wherever a constraint the database should enforce is not something
autogenerate can infer.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c11abcd27946"
down_revision: str | None = "ab9af68b0824"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_categories_id_tenant_id", "categories", ["id", "tenant_id"])

    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sku", sa.String(length=64), nullable=True),
        sa.Column("barcode", sa.String(length=64), nullable=True),
        sa.Column("selling_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("cost_price", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("low_stock_threshold", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False),
        sa.Column("public_token", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # The composite reference: this is the constraint that keeps tenants apart.
        sa.ForeignKeyConstraint(
            ["category_id", "tenant_id"],
            ["categories.id", "categories.tenant_id"],
            name="fk_products_category_id_tenant_id_categories",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_products_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        # The anchor the cross-tenant keys of later tables reference.
        sa.UniqueConstraint("id", "tenant_id", name="uq_products_id_tenant_id"),
        sa.UniqueConstraint("public_token", name=op.f("uq_products_public_token")),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_products_tenant_id_slug"),
    )
    op.create_index(
        "ix_products_tenant_category", "products", ["tenant_id", "category_id"], unique=False
    )
    op.create_index(
        "uq_products_tenant_barcode",
        "products",
        ["tenant_id", "barcode"],
        unique=True,
        postgresql_where=sa.text("barcode IS NOT NULL"),
    )
    op.create_index(
        "uq_products_tenant_sku",
        "products",
        ["tenant_id", "sku"],
        unique=True,
        postgresql_where=sa.text("sku IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_products_tenant_sku", table_name="products", postgresql_where=sa.text("sku IS NOT NULL")
    )
    op.drop_index(
        "uq_products_tenant_barcode",
        table_name="products",
        postgresql_where=sa.text("barcode IS NOT NULL"),
    )
    op.drop_index("ix_products_tenant_category", table_name="products")
    op.drop_table("products")
    op.drop_constraint("uq_categories_id_tenant_id", "categories", type_="unique")
