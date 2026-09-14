"""Persistence for sale lines.

One table, one entity, one file, and one property worth stating.

The line belongs to a sale as a pair
    `(sale_id, tenant_id)` references `sales(id, tenant_id)`, which is only legal because
    that pair is unique on the sales table. It is what makes a line unable to belong to
    another business's sale - the same composite pattern that keeps a product reference
    from crossing tenants, and the reason `sales` carries its own anchor.

Lines are written with the sale and read with it
    There is no update and no delete function: a line is what was sold, and a correction is
    a cancellation of the sale and a new one. That is why the table has no `updated_at` -
    nothing about a line ever changes after it is written.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.crud.integrity_violations import translate_integrity_violation
from ahia.models.entities.sale_item_model import (
    MAXIMUM_PRODUCT_NAME_LENGTH,
    SaleItemModel,
)

_TABLE_NAME: Final[str] = "sale_items"
_MONEY_PRECISION: Final[int] = 18
_MONEY_SCALE: Final[int] = 2
_QUANTITY_SCALE: Final[int] = 3


class SaleItemRecord(Base):
    """The persistence representation of one sale line."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    sale_id: Mapped[UUID] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    product_name_snapshot: Mapped[str] = mapped_column(
        String(MAXIMUM_PRODUCT_NAME_LENGTH), nullable=False
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(_MONEY_PRECISION, _MONEY_SCALE), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(_MONEY_PRECISION, _QUANTITY_SCALE), nullable=False
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(_MONEY_PRECISION, _MONEY_SCALE), nullable=False
    )
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(_MONEY_PRECISION, _MONEY_SCALE), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["sale_id", "tenant_id"],
            ["sales.id", "sales.tenant_id"],
            name="fk_sale_items_sale_id_tenant_id_sales",
        ),
        ForeignKeyConstraint(
            ["product_id", "tenant_id"],
            ["products.id", "products.tenant_id"],
            name="fk_sale_items_product_id_tenant_id_products",
        ),
        Index("ix_sale_items_tenant_sale", "tenant_id", "sale_id"),
        # "What did we sell of this product" is the report this index serves.
        Index("ix_sale_items_tenant_product", "tenant_id", "product_id"),
    )


def to_entity(record: SaleItemRecord) -> SaleItemModel:
    return SaleItemModel(
        id=record.id,
        tenant_id=record.tenant_id,
        sale_id=record.sale_id,
        product_id=record.product_id,
        product_name_snapshot=record.product_name_snapshot,
        unit_price=record.unit_price,
        quantity=record.quantity,
        discount_amount=record.discount_amount,
        line_total=record.line_total,
        created_at=record.created_at,
    )


def apply_entity(record: SaleItemRecord, entity: SaleItemModel) -> None:
    record.tenant_id = entity.tenant_id
    record.sale_id = entity.sale_id
    record.product_id = entity.product_id
    record.product_name_snapshot = entity.product_name_snapshot
    record.unit_price = entity.unit_price
    record.quantity = entity.quantity
    record.discount_amount = entity.discount_amount
    record.line_total = entity.line_total
    record.created_at = entity.created_at


async def create(session: AsyncSession, item: SaleItemModel) -> SaleItemModel:
    """Insert one sale line."""
    record = SaleItemRecord(id=item.id)
    apply_entity(record, item)
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise translate_integrity_violation(
            conflict,
            operation="complete_sale",
            entity="sale_item",
            identifier=str(item.id),
            conflict_detail="this sale line already exists",
            missing_detail="the sale or product this line references does not exist",
        ) from conflict
    return to_entity(record)


async def list_for_sale(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    sale_id: UUID,
) -> list[SaleItemModel]:
    """Return a sale's lines, in the order they were written."""
    result = await session.execute(
        select(SaleItemRecord)
        .where(SaleItemRecord.tenant_id == tenant_id)
        .where(SaleItemRecord.sale_id == sale_id)
        .order_by(SaleItemRecord.created_at, SaleItemRecord.id)
    )
    return [to_entity(record) for record in result.scalars().all()]


async def count_for_sale(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    sale_id: UUID,
) -> int:
    """Return how many lines a sale has."""
    result = await session.execute(
        select(func.count())
        .select_from(SaleItemRecord)
        .where(SaleItemRecord.tenant_id == tenant_id)
        .where(SaleItemRecord.sale_id == sale_id)
    )
    return int(result.scalar_one())
