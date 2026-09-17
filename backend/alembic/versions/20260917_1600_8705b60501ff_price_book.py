"""the price book: a price for the counter, a price for a list, and a pack size

Three facts the trade runs on and the schema did not hold.

**A group of goods shares a price.** "All of the 21D are 350" is one number, not twenty - so a category
carries the price and the items under it follow, with the exceptions being the items that carry their
own. That is what makes a grade a grade, and it is why this is a nullable column on both tables rather
than a price on every row.

**There are two prices, and both are the merchant's.** The normal price is what the shop page shows; the
wholesale price is what a list is priced with. No tier machinery, no per-customer configuration - just
the two numbers he sets, overridable on any line when he wants to.

**A pack is a fact about the goods, not a question for the buyer.** Pieces per pack sits on the group
and can be overridden per item, so a customer counting "20 pcs" is never asked how many are in a pack.

Every column is nullable and additive: nothing that exists today changes meaning, and a business that
never touches the price book keeps working exactly as it did.

Revision ID: 8705b60501ff
Revises: 8dd6119da104
Create Date: 2026-09-17 16:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8705b60501ff"
down_revision: str | None = "8dd6119da104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PRICE = sa.Numeric(18, 2)


def upgrade() -> None:
    op.add_column("categories", sa.Column("default_normal_price", _PRICE, nullable=True))
    op.add_column("categories", sa.Column("default_wholesale_price", _PRICE, nullable=True))
    op.add_column("categories", sa.Column("default_pieces_per_pack", sa.Integer(), nullable=True))

    op.add_column("products", sa.Column("wholesale_price", _PRICE, nullable=True))
    op.add_column("products", sa.Column("pieces_per_pack", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "pieces_per_pack")
    op.drop_column("products", "wholesale_price")

    op.drop_column("categories", "default_pieces_per_pack")
    op.drop_column("categories", "default_wholesale_price")
    op.drop_column("categories", "default_normal_price")
