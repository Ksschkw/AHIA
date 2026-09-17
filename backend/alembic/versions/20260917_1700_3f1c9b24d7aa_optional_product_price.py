"""an item's own price becomes optional

"All of the 21D are 350" is one number on the group, and the exceptions are the items that carry their
own. For that to be true, an item must be allowed to have no price of its own - so `products.selling_price`
becomes nullable, and `wholesale_price` and `pieces_per_pack` already were.

Nothing changes for existing rows: every product that has a price keeps it, and the difference is only
that a new item can be added under a priced group and inherit it.

An item that ends up with no price from anywhere - no price of its own and no group price either - is
refused by the service, because that is a business rule about an item and its group together. The
database stores the absence; the service decides whether the absence is acceptable.

Revision ID: 3f1c9b24d7aa
Revises: 8705b60501ff
Create Date: 2026-09-17 17:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3f1c9b24d7aa"
down_revision: str | None = "8705b60501ff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("products", "selling_price", existing_type=sa.Numeric(18, 2), nullable=True)


def downgrade() -> None:
    # Going back requires every row to have a price, which is exactly the state a group-priced item
    # is not in. Rows that inherited a price are given one here so the column can be made mandatory
    # again, from the group they were following.
    op.execute(
        """
        UPDATE products AS product
        SET selling_price = category.default_normal_price
        FROM categories AS category
        WHERE product.selling_price IS NULL
          AND product.category_id = category.id
          AND category.default_normal_price IS NOT NULL
        """
    )
    op.alter_column("products", "selling_price", existing_type=sa.Numeric(18, 2), nullable=False)
