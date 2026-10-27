"""Add push_subscriptions table.

Revision ID: b2c3d4e5f6a7
Revises: 1a2b3c4d5e6f
Create Date: 2026-10-27 04:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "1a2b3c4d5e6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("endpoint", sa.String(length=1024), nullable=False),
        sa.Column("p256dh", sa.Text(), nullable=True),
        sa.Column("auth", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_push_subscriptions_tenant_id_tenants"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_push_subscriptions_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_push_subscriptions")),
    )
    op.create_index(
        "ix_push_subscriptions_recipient",
        "push_subscriptions",
        ["tenant_id", "user_id"],
        unique=False,
    )
    op.create_index(
        "uq_push_subscriptions_tenant_user_endpoint",
        "push_subscriptions",
        ["tenant_id", "user_id", "endpoint"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_push_subscriptions_tenant_user_endpoint",
        table_name="push_subscriptions",
    )
    op.drop_index(
        "ix_push_subscriptions_recipient",
        table_name="push_subscriptions",
    )
    op.drop_table("push_subscriptions")
