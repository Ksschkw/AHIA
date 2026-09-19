"""Groups inside groups.

A shelf in this trade has three levels in it - Screenguard, then 21D, then Hot 8 - and only the last one
is ever exceptional: "Hot 8 is 370, the rest of the 21D are 350". The price lives on the node and is
inherited downward, so a grade can carry one number and a model can override it, which is how the trade
already thinks and how a list is read.

A parent is nullable: an existing group stays where it is, and nothing that already works changes.

Revision ID: 9c1d2e3f4a5b
Revises: 7b2e4c91a5f3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "9c1d2e3f4a5b"
down_revision: str | None = "7b2e4c91a5f3"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("parent_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_categories_parent_id_categories",
        "categories",
        "categories",
        ["parent_id"],
        ["id"],
        # A group that is deleted takes nothing with it: its children become top-level rather than
        # vanishing with it. Losing a grade because somebody tidied up its parent is not a trade anyone
        # would make.
        ondelete="SET NULL",
    )
    # A list asks for a group's children on every visit to the list builder, so the lookup has an index
    # behind it from the first day rather than from the first slow complaint.
    op.create_index("ix_categories_parent_id", "categories", ["parent_id"])


def downgrade() -> None:
    op.drop_index("ix_categories_parent_id", table_name="categories")
    op.drop_constraint("fk_categories_parent_id_categories", "categories", type_="foreignkey")
    op.drop_column("categories", "parent_id")
