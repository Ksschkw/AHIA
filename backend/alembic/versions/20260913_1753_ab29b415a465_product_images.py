"""product_images: where the pictures live, described without naming a provider

One table, and the schema-level half of the storage request: nothing here says "R2" or
"Cloudinary". `storage_provider` records who holds the bytes and `storage_key` records
the path within that provider, so switching providers is a configuration change and
every row written before the switch stays resolvable afterwards.

The product reference is composite, `(product_id, tenant_id)` against
`products(id, tenant_id)`. A plain foreign key on the product identifier would accept an
image in one business pointing at another business's product, because the identifier
alone is valid in every tenant. This is the same pattern as products referencing
categories.

A primary image is never a removed one: `CHECK (NOT (is_primary AND removed_at IS
NOT NULL))`. The entity refuses the combination, and a raw update could otherwise
produce it - the partial unique index below excludes removed rows from the count of
primaries, it does not forbid the flag on a removed row.

At most one primary image per product: `UNIQUE(product_id) WHERE is_primary AND
removed_at IS NULL`. The service demotes the previous primary in the same transaction,
so the ordinary path never leans on the constraint - but two simultaneous requests
cannot produce a product with two primary images, which a read-then-write check would
allow. The predicate also means a removed image never blocks the choice of a new one.

`storage_key` is unique: two rows may not claim the same stored object, because deleting
one image would then delete another's bytes.

A removed image keeps its row
    `removed_at` marks an image the business no longer wants, and `reconciliation_reason`
    records a provider delete that failed. The row survives until the object is
    confirmed gone. Deleting the row on a failed delete would leave bytes nobody is
    accounting for: storage the tenant is not charged for and no operator can find. The
    partial index on `reconciliation_reason` is what a reconciliation job scans.

No `(id, tenant_id)` anchor here: nothing references an image yet, and a composite key
that no foreign key uses is complexity bought for a hypothetical. It arrives with the
table that needs it, as it did for products.

Revision ID: ab29b415a465
Revises: c11abcd27946
Create Date: 2026-09-13 17:53:56.709387

Generated where autogenerate was sufficient, reviewed before it was applied, and
edited by hand wherever a constraint the database should enforce is not something
autogenerate can infer.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ab29b415a465"
down_revision: str | None = "c11abcd27946"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("storage_provider", sa.String(length=32), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciliation_reason", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # The entity's rule, stated where an UPDATE cannot bypass it.
        sa.CheckConstraint(
            "NOT (is_primary AND removed_at IS NOT NULL)",
            name=op.f("ck_product_images_primary_image_not_removed"),
        ),
        # The composite reference: an image cannot belong to another business's product.
        sa.ForeignKeyConstraint(
            ["product_id", "tenant_id"],
            ["products.id", "products.tenant_id"],
            name="fk_product_images_product_id_tenant_id_products",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_product_images_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_images")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_product_images_storage_key")),
    )
    op.create_index(
        "ix_product_images_pending_reconciliation",
        "product_images",
        ["tenant_id"],
        unique=False,
        postgresql_where=sa.text("reconciliation_reason IS NOT NULL"),
    )
    op.create_index(
        "ix_product_images_tenant_product",
        "product_images",
        ["tenant_id", "product_id"],
        unique=False,
    )
    op.create_index(
        "uq_product_images_primary",
        "product_images",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("is_primary AND removed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_product_images_primary",
        table_name="product_images",
        postgresql_where=sa.text("is_primary AND removed_at IS NULL"),
    )
    op.drop_index("ix_product_images_tenant_product", table_name="product_images")
    op.drop_index(
        "ix_product_images_pending_reconciliation",
        table_name="product_images",
        postgresql_where=sa.text("reconciliation_reason IS NOT NULL"),
    )
    op.drop_table("product_images")
