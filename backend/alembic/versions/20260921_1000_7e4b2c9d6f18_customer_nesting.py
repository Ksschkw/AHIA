"""A customer can put a heading inside their own heading.

A list is a document the customer writes, and people write in outlines: "Items for my shop", with things under
it. Until now a line could carry a heading in `note` and nothing could carry a heading under *that*, so a
customer's own structure was one level deep - which is enough for "Privacy Glass / iPhone X650 x10" and not
enough for the lists traders actually receive.

A line with a parent is a heading; a line without one stands at the top. **The same shape as the catalogue's own
hierarchy**, used a second time rather than a second concept invented for lists - and it is the customer's
structure, so it never touches the trader's catalogue.

`ON DELETE CASCADE` here, unlike the catalogue's `SET NULL`: a line's children belong to it. Deleting a heading
from a list means deleting what was under it, and leaving orphans behind would put lines on a list under nothing.

Revision ID: 7e4b2c9d6f18
Revises: 5d2f7a1c8e34
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "7e4b2c9d6f18"
down_revision: str | None = "5d2f7a1c8e34"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("request_lines", sa.Column("parent_line_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_request_lines_parent_line_id_request_lines",
        "request_lines",
        "request_lines",
        ["parent_line_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # A list is loaded in full and assembled into its shape in one pass, so the lookup is by parent.
    op.create_index("ix_request_lines_parent_line_id", "request_lines", ["parent_line_id"])


def downgrade() -> None:
    op.drop_index("ix_request_lines_parent_line_id", table_name="request_lines")
    op.drop_constraint(
        "fk_request_lines_parent_line_id_request_lines", "request_lines", type_="foreignkey"
    )
    op.drop_column("request_lines", "parent_line_id")
