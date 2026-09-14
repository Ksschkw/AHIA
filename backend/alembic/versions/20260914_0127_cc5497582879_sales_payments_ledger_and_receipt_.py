"""sales, sale lines, payments, ledger entries and receipt counters

The milestone where the catalogue, the stock ledger and the customer record meet in one
transaction, so this revision carries the tables that transaction writes and the constraints
that keep them honest.

The counter comes first, then the sale, then everything that references it
    `receipt_counters` is one row per business, holding the highest receipt number issued.
    `sales` carries the trade itself. The lines, the payments and the ledger all reference
    the sale as `(sale_id, tenant_id)`, which is legal only because `sales` declares
    `UNIQUE(id, tenant_id)` - the same anchor pattern the catalogue uses, applied to the
    table its children point at. The customers anchor arrives in the same revision for the
    same reason: the sale references `(customer_id, tenant_id)`.

The receipt number is unique per business, and an offline operation is recorded once
    `UNIQUE(tenant_id, receipt_number)` makes a duplicate receipt impossible rather than
    unlikely. `UNIQUE(tenant_id, operation_id) WHERE operation_id IS NOT NULL` is what makes
    a replayed sync operation return the original sale instead of selling the basket twice -
    idempotency as a database guarantee rather than a service promise.

The ledger is append-only, enforced by a trigger
    A trigger refuses UPDATE and DELETE on `ledger_entries`, exactly as it does for stock
    movements. The application has no function that could perform either, but a convention
    holds only until somebody writes the function that breaks it. The consequence is that a
    correction is another entry, which is the accounting rule and the only kind of correction
    that can be audited.

No cascade anywhere in this revision
    A cancelled sale keeps its lines and its payments, because the money and the stock still
    moved: the refund is recorded as its own payment state and its own ledger entry. A
    cascade would delete the explanation and leave the totals.

Revision ID: cc5497582879
Revises: 8940933a7bca
Create Date: 2026-09-14 01:27:30.245675

Generated where autogenerate was sufficient, reviewed before it was applied, and
edited by hand wherever a constraint the database should enforce is not something
autogenerate can infer.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "cc5497582879"
down_revision: str | None = "8940933a7bca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPEND_ONLY_FUNCTION: str = "ahia_ledger_entries_append_only"
_APPEND_ONLY_TRIGGER: str = "ledger_entries_append_only"


def upgrade() -> None:
    # The anchor the sale's customer reference depends on, before the table that uses it.
    op.create_unique_constraint("uq_customers_id_tenant_id", "customers", ["id", "tenant_id"])

    op.create_table(
        "receipt_counters",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("last_receipt_number", sa.BigInteger(), nullable=False),
        sa.Column("receipt_prefix", sa.String(length=12), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_receipt_counters_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_receipt_counters")),
    )

    op.create_table(
        "sales",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("receipt_number", sa.String(length=40), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("subtotal", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payment_status", sa.String(length=32), nullable=False),
        sa.Column("seller_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("operation_id", sa.Uuid(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["customer_id", "tenant_id"],
            ["customers.id", "customers.tenant_id"],
            name="fk_sales_customer_id_tenant_id_customers",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"], name=op.f("fk_sales_device_id_devices")
        ),
        sa.ForeignKeyConstraint(["seller_id"], ["users.id"], name=op.f("fk_sales_seller_id_users")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_sales_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales")),
        sa.UniqueConstraint("id", "tenant_id", name="uq_sales_id_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "receipt_number", name="uq_sales_tenant_id_receipt_number"
        ),
    )
    op.create_index("ix_sales_tenant_customer", "sales", ["tenant_id", "customer_id"])
    op.create_index("ix_sales_tenant_occurred", "sales", ["tenant_id", "occurred_at"])
    op.create_index(
        "ix_sales_tenant_seller_occurred", "sales", ["tenant_id", "seller_id", "occurred_at"]
    )
    op.create_index(
        "uq_sales_tenant_id_operation_id",
        "sales",
        ["tenant_id", "operation_id"],
        unique=True,
        postgresql_where=sa.text("operation_id IS NOT NULL"),
    )

    op.create_table(
        "sale_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("sale_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("product_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("discount_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id", "tenant_id"],
            ["products.id", "products.tenant_id"],
            name="fk_sale_items_product_id_tenant_id_products",
        ),
        sa.ForeignKeyConstraint(
            ["sale_id", "tenant_id"],
            ["sales.id", "sales.tenant_id"],
            name="fk_sale_items_sale_id_tenant_id_sales",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sale_items")),
    )
    op.create_index("ix_sale_items_tenant_product", "sale_items", ["tenant_id", "product_id"])
    op.create_index("ix_sale_items_tenant_sale", "sale_items", ["tenant_id", "sale_id"])

    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("sale_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("reference", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["sale_id", "tenant_id"],
            ["sales.id", "sales.tenant_id"],
            name="fk_payments_sale_id_tenant_id_sales",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
    )
    op.create_index("ix_payments_tenant_received", "payments", ["tenant_id", "received_at"])
    op.create_index("ix_payments_tenant_sale", "payments", ["tenant_id", "sale_id"])

    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("reference_type", sa.String(length=64), nullable=False),
        sa.Column("reference_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_ledger_entries_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger_entries")),
    )
    op.create_index(
        "ix_ledger_entries_tenant_occurred", "ledger_entries", ["tenant_id", "occurred_at"]
    )
    op.create_index(
        "ix_ledger_entries_tenant_reference",
        "ledger_entries",
        ["tenant_id", "reference_type", "reference_id"],
    )
    op.create_index(
        "ix_ledger_entries_tenant_type_occurred",
        "ledger_entries",
        ["tenant_id", "entry_type", "occurred_at"],
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_APPEND_ONLY_FUNCTION}() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'ledger_entries is append-only: record a correcting entry instead';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_APPEND_ONLY_TRIGGER}
        BEFORE UPDATE OR DELETE ON ledger_entries
        FOR EACH ROW EXECUTE FUNCTION {_APPEND_ONLY_FUNCTION}();
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_APPEND_ONLY_TRIGGER} ON ledger_entries")
    op.execute(f"DROP FUNCTION IF EXISTS {_APPEND_ONLY_FUNCTION}()")

    op.drop_index("ix_ledger_entries_tenant_type_occurred", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_tenant_reference", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_tenant_occurred", table_name="ledger_entries")
    op.drop_table("ledger_entries")

    op.drop_index("ix_payments_tenant_sale", table_name="payments")
    op.drop_index("ix_payments_tenant_received", table_name="payments")
    op.drop_table("payments")

    op.drop_index("ix_sale_items_tenant_sale", table_name="sale_items")
    op.drop_index("ix_sale_items_tenant_product", table_name="sale_items")
    op.drop_table("sale_items")

    op.drop_index(
        "uq_sales_tenant_id_operation_id",
        table_name="sales",
        postgresql_where=sa.text("operation_id IS NOT NULL"),
    )
    op.drop_index("ix_sales_tenant_seller_occurred", table_name="sales")
    op.drop_index("ix_sales_tenant_occurred", table_name="sales")
    op.drop_index("ix_sales_tenant_customer", table_name="sales")
    op.drop_table("sales")

    op.drop_table("receipt_counters")

    op.drop_constraint("uq_customers_id_tenant_id", "customers", type_="unique")
