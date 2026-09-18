"""a customer's list: the tables the paper slip becomes

Two tables, and the isolation policy every other business-owned table already carries.

**Why the list is not the sale.** Nothing here touches stock or money: a list is a wish until the
trader confirms it, and only then does a sale exist. Keeping the two apart in the schema is what makes
that true rather than merely intended - there is no column on `requests` that a sale could be read out
of, because a list is not one.

**Why the phone number is the identity.** It is the only thing a customer is asked for, so it is stored
canonically and indexed per business: "what did Toba order last time" is the query this table exists to
answer, and `0901...`, `+234901...` and `234901...` have to reach the same history.

**Why the RLS policy is here as well as the tables.** Every table with a `tenant_id` gets the same
policy, and the verification test asserts that the deployed policies match one shape exactly. A new
tenant-owned table without one is the leak that would matter most, so the policy is applied in the same
migration that creates the tables rather than in a follow-up nobody remembers.

Revision ID: 7b2e4c91a5f3
Revises: 3f1c9b24d7aa
Create Date: 2026-09-17 19:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b2e4c91a5f3"
down_revision: str | None = "3f1c9b24d7aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PRICE = sa.Numeric(18, 2)
_QUANTITY = sa.Numeric(18, 3)

#: The setting the application sets per transaction, and the predicate every policy uses.
TENANT_SCOPE_SETTING = "app.current_tenant"

NEW_TENANT_SCOPED_TABLES: tuple[str, ...] = ("requests", "request_lines")


def _policy_name(table_name: str) -> str:
    return f"{table_name}_tenant_isolation"


def upgrade() -> None:
    op.create_table(
        "requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("customer_phone", sa.String(32), nullable=False),
        sa.Column("customer_name", sa.String(120), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("public_token_digest", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_requests_tenant_id", "requests", ["tenant_id"])
    op.create_index("ix_requests_customer_phone", "requests", ["customer_phone"])
    op.create_index("ix_requests_tenant_status", "requests", ["tenant_id", "status"])
    op.create_index("ix_requests_tenant_customer", "requests", ["tenant_id", "customer_phone"])

    op.create_table(
        "request_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "request_id",
            sa.Uuid(),
            sa.ForeignKey("requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("quantity", _QUANTITY, nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.Column("product_id", sa.Uuid(), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("free_text", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("pieces_per_pack", sa.Integer(), nullable=True),
        sa.Column("customer_price", _PRICE, nullable=True),
        sa.Column("shop_price", _PRICE, nullable=True),
        sa.Column("cost_price", _PRICE, nullable=True),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("image_key", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_request_lines_request_id", "request_lines", ["request_id"])
    op.create_index("ix_request_lines_tenant_id", "request_lines", ["tenant_id"])
    op.create_index("ix_request_lines_product_id", "request_lines", ["product_id"])
    op.create_index(
        "ix_request_lines_request_position", "request_lines", ["request_id", "position"]
    )

    predicate = f"tenant_id = nullif(current_setting('{TENANT_SCOPE_SETTING}', true), '')::uuid"
    for table_name in NEW_TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {_policy_name(table_name)} ON {table_name} "
            f"FOR ALL USING ({predicate}) WITH CHECK ({predicate})"
        )


def downgrade() -> None:
    for table_name in NEW_TENANT_SCOPED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {_policy_name(table_name)} ON {table_name}")
    op.drop_table("request_lines")
    op.drop_table("requests")
