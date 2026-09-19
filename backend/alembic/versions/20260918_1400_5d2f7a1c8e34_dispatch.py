"""Sending it: the transporter, the waybill number, what the trip cost, and how to follow it.

A confirmed list becomes a parcel on a road. The trader writes down who is carrying it and under what
number, because that is the answer he needs when somebody calls to ask where their goods are - and the
cost, because that comes off what he made on the list and he should not have to remember it.

All nullable: a list that is picked up by hand, or by the customer themselves, is a normal way for this
trade to work and needs none of it.

Revision ID: 5d2f7a1c8e34
Revises: 9c1d2e3f4a5b
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "5d2f7a1c8e34"
down_revision: str | None = "9c1d2e3f4a5b"
branch_labels: str | None = None
depends_on: str | None = None

_PRICE = sa.Numeric(14, 2)


def upgrade() -> None:
    op.add_column("requests", sa.Column("transporter_name", sa.String(120), nullable=True))
    op.add_column("requests", sa.Column("transporter_phone", sa.String(32), nullable=True))
    op.add_column("requests", sa.Column("waybill_number", sa.String(64), nullable=True))
    op.add_column("requests", sa.Column("dispatch_cost", _PRICE, nullable=True))
    op.add_column("requests", sa.Column("tracking_url", sa.Text(), nullable=True))
    op.add_column("requests", sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for column in (
        "dispatched_at",
        "tracking_url",
        "dispatch_cost",
        "waybill_number",
        "transporter_phone",
        "transporter_name",
    ):
        op.drop_column("requests", column)
