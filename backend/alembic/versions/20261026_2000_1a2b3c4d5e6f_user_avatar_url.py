"""Add avatar_url to users table.

Revision ID: 1a2b3c4d5e6f
Revises: 8f3a1d9c5e27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "1a2b3c4d5e6f"
down_revision: str | None = "8f3a1d9c5e27"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_url", sa.String(1024), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_url")
