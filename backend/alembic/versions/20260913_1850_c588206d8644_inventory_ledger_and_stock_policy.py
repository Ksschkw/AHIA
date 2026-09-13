"""inventory ledger, stock projection, and the tenant's stock policy

Three changes, one subject: stock is a history, and what a business may do with it is
its own decision.

`inventory_movements` is append-only, enforced by the database
    A trigger refuses UPDATE and DELETE on the table. The application has no function
    that could perform either - `crud/inventory_movement_crud.py` offers `record` and
    readers - but a convention holds only until somebody writes the function that breaks
    it. The trigger holds for a psql session, a migration, and a future service that has
    not read the docstring. The cost is one trigger on a table that is only ever inserted
    into; the consequence is that a mistake is corrected by recording a compensating
    movement, which is the accounting rule and the only kind of correction that can be
    audited.

`inventory` is the projection derived from that history
    One row per product per business, `UNIQUE(tenant_id, product_id)`, with a composite
    reference to `products(id, tenant_id)` so a projection cannot describe another
    business's product. Every mutation takes the row lock, which is what makes two
    simultaneous sales produce two movements and a projection that reflects both.

`tenants.negative_stock_policy` is the business's own rule about stock going negative
    Added with a server default so existing businesses are backfilled with the safe
    answer - `BLOCK_NEGATIVE_STOCK` - and the default is then dropped, leaving the schema
    exactly as the model declares it and making a future insert that forgets the column
    fail loudly rather than inherit a policy silently.

Revision ID: c588206d8644
Revises: ab29b415a465
Create Date: 2026-09-13 18:50:35.985041

Generated where autogenerate was sufficient, reviewed before it was applied, and
edited by hand wherever a constraint the database should enforce is not something
autogenerate can infer.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c588206d8644"
down_revision: str | None = "ab29b415a465"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The safe answer, and the one every existing business is backfilled with. A shop that
#: has sold stock it does not have has a problem, and the moment it appears is the
#: cheapest moment to notice.
_DEFAULT_NEGATIVE_STOCK_POLICY: str = "BLOCK_NEGATIVE_STOCK"

_APPEND_ONLY_FUNCTION: str = "ahia_inventory_movements_append_only"
_APPEND_ONLY_TRIGGER: str = "inventory_movements_append_only"


def upgrade() -> None:
    op.create_table(
        "inventory",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity_on_hand", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("reserved_quantity", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id", "tenant_id"],
            ["products.id", "products.tenant_id"],
            name="fk_inventory_product_id_tenant_id_products",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_inventory_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory")),
        sa.UniqueConstraint("tenant_id", "product_id", name="uq_inventory_tenant_id_product_id"),
    )

    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("movement_type", sa.String(length=32), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("quantity_before", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("quantity_after", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("reference_type", sa.String(length=64), nullable=True),
        sa.Column("reference_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("operation_id", sa.Uuid(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_inventory_movements_actor_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"], name=op.f("fk_inventory_movements_device_id_devices")
        ),
        sa.ForeignKeyConstraint(
            ["product_id", "tenant_id"],
            ["products.id", "products.tenant_id"],
            name="fk_inventory_movements_product_id_tenant_id_products",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_inventory_movements_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_movements")),
    )
    op.create_index(
        "ix_inventory_movements_tenant_occurred",
        "inventory_movements",
        ["tenant_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_movements_tenant_product_occurred",
        "inventory_movements",
        ["tenant_id", "product_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "uq_inventory_movements_tenant_operation",
        "inventory_movements",
        ["tenant_id", "operation_id"],
        unique=True,
        postgresql_where=sa.text("operation_id IS NOT NULL"),
    )

    # The backfill: a NOT NULL column cannot be added to a table that has rows without a
    # value to put in them, and every existing business gets the policy that refuses
    # negative stock.
    op.add_column(
        "tenants",
        sa.Column(
            "negative_stock_policy",
            sa.String(length=32),
            nullable=False,
            server_default=_DEFAULT_NEGATIVE_STOCK_POLICY,
        ),
    )
    # Then the default goes, so the schema matches the model exactly. A future insert that
    # forgets the column should fail rather than silently inherit a policy - the safe
    # answer is not the same thing as an answer nobody chose.
    op.alter_column("tenants", "negative_stock_policy", server_default=None)

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_APPEND_ONLY_FUNCTION}() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'inventory_movements is append-only: record a compensating movement';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_APPEND_ONLY_TRIGGER}
        BEFORE UPDATE OR DELETE ON inventory_movements
        FOR EACH ROW EXECUTE FUNCTION {_APPEND_ONLY_FUNCTION}();
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_APPEND_ONLY_TRIGGER} ON inventory_movements")
    op.execute(f"DROP FUNCTION IF EXISTS {_APPEND_ONLY_FUNCTION}()")
    op.drop_column("tenants", "negative_stock_policy")
    op.drop_index(
        "uq_inventory_movements_tenant_operation",
        table_name="inventory_movements",
        postgresql_where=sa.text("operation_id IS NOT NULL"),
    )
    op.drop_index("ix_inventory_movements_tenant_product_occurred", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_tenant_occurred", table_name="inventory_movements")
    op.drop_table("inventory_movements")
    op.drop_table("inventory")
