"""the public storefront, and whether it is open

The table behind `/shop/{tenant_slug}`: one row per business that has opened a shop, holding
whether it answers and what it says about itself.

The address is not in this table
    The public URL uses the tenant's slug, which is already globally unique and already the address
    a business gives out. A second slug here would be a second address for the same shop, and the
    two would eventually disagree about which one customers hold.

One row per business, enforced by the database
    `UNIQUE(tenant_id)`. A second row would be a second answer to "is this shop open", which is the
    first question a customer's link asks.

Unpublishing keeps the row
    A business that closes for a week keeps the address it gave out and the record that it was open
    before. `is_published`, `published_at` and `unpublished_at` say which state it is in; nothing in
    this revision deletes anything.

No grants beyond the application's own account, and no public role
    The public reads are served by the application through the projection in `storefront_service`,
    which is built from an allowlist. There is no database role for an anonymous reader because
    there is no path from the internet to the database.

Revision ID: fc135a55c7db
Revises: 3394dddd7e43
Create Date: 2026-09-15 05:37:00.000000

Generated where autogenerate was sufficient, reviewed before it was applied, and
edited by hand wherever a constraint the database should enforce is not something
autogenerate can infer.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fc135a55c7db"
down_revision: str | None = "3394dddd7e43"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "storefronts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False),
        sa.Column("headline", sa.String(length=120), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("contact_phone", sa.String(length=32), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unpublished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_storefronts_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_storefronts")),
        sa.UniqueConstraint("tenant_id", name="uq_storefronts_tenant_id"),
    )


def downgrade() -> None:
    op.drop_table("storefronts")
