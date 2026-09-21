"""Persistence for the lines of a customer's list: one table, one entity.

A line is stored with the three prices the trade actually involves and never with a fourth: what the
customer was shown, what the trader set, and what it cost him. Nothing here decides anything - the
arithmetic lives in the entity and the decisions live in a service.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import NotFoundError
from ahia.models.entities.request_line_model import (
    RequestLineModel,
    RequestLineState,
    RequestLineUnit,
)

_TABLE_NAME: Final[str] = "request_lines"
_PRICE_PRECISION: Final[int] = 18
_PRICE_SCALE: Final[int] = 2
_QUANTITY_SCALE: Final[int] = 3
_UNIT_LENGTH: Final[int] = 16
_STATE_LENGTH: Final[int] = 24
_IMAGE_KEY_LENGTH: Final[int] = 512


class RequestLineRecord(Base):
    """The persistence representation of one item on one list."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    request_id: Mapped[UUID] = mapped_column(
        ForeignKey("requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(_PRICE_PRECISION, _QUANTITY_SCALE), nullable=False
    )
    unit: Mapped[str] = mapped_column(String(_UNIT_LENGTH), nullable=False)
    product_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("products.id"), nullable=True, index=True
    )
    free_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    pieces_per_pack: Mapped[int | None] = mapped_column(Integer, nullable=True)
    customer_price: Mapped[Decimal | None] = mapped_column(
        Numeric(_PRICE_PRECISION, _PRICE_SCALE), nullable=True
    )
    shop_price: Mapped[Decimal | None] = mapped_column(
        Numeric(_PRICE_PRECISION, _PRICE_SCALE), nullable=True
    )
    cost_price: Mapped[Decimal | None] = mapped_column(
        Numeric(_PRICE_PRECISION, _PRICE_SCALE), nullable=True
    )
    state: Mapped[str] = mapped_column(String(_STATE_LENGTH), nullable=False)
    image_key: Mapped[str | None] = mapped_column(String(_IMAGE_KEY_LENGTH), nullable=True)
    parent_line_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("request_lines.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_request_lines_request_position", "request_id", "position"),)


def to_entity(record: RequestLineRecord) -> RequestLineModel:
    return RequestLineModel(
        id=record.id,
        request_id=record.request_id,
        tenant_id=record.tenant_id,
        position=record.position,
        quantity=record.quantity,
        unit=RequestLineUnit(record.unit),
        product_id=record.product_id,
        free_text=record.free_text,
        note=record.note,
        pieces_per_pack=record.pieces_per_pack,
        customer_price=record.customer_price,
        shop_price=record.shop_price,
        cost_price=record.cost_price,
        state=RequestLineState(record.state),
        image_key=record.image_key,
        parent_line_id=record.parent_line_id,
        created_at=record.created_at,
    )


def apply_entity(record: RequestLineRecord, entity: RequestLineModel) -> None:
    record.request_id = entity.request_id
    record.tenant_id = entity.tenant_id
    record.position = entity.position
    record.quantity = entity.quantity
    record.unit = entity.unit.value
    record.product_id = entity.product_id
    record.free_text = entity.free_text
    record.note = entity.note
    record.pieces_per_pack = entity.pieces_per_pack
    record.customer_price = entity.customer_price
    record.shop_price = entity.shop_price
    record.cost_price = entity.cost_price
    record.state = entity.state.value
    record.image_key = entity.image_key
    record.parent_line_id = entity.parent_line_id
    record.created_at = entity.created_at


async def create_many(
    session: AsyncSession, lines: list[RequestLineModel]
) -> list[RequestLineModel]:
    """Store every line of a list in one write, which is how a list arrives."""
    records = []
    for line in lines:
        record = RequestLineRecord(id=line.id)
        apply_entity(record, line)
        session.add(record)
        records.append(record)
    await session.flush()
    return [to_entity(record) for record in records]


async def update(session: AsyncSession, line: RequestLineModel) -> RequestLineModel:
    """Store a line's current state: what it costs, what it cost him, where it came from."""
    record = await session.get(RequestLineRecord, line.id)
    if record is None:
        raise NotFoundError(
            operation="update_request_line",
            entity="request_line",
            identifier=str(line.id),
            detail="no line matched",
        )
    apply_entity(record, line)
    await session.flush()
    return to_entity(record)


async def require_by_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    request_id: UUID,
    line_id: UUID,
) -> RequestLineModel:
    """Return one line of one list, or refuse as if it did not exist.

    Scoped by both the business and the list: a line identifier from another shop's list is not a
    line
    this caller may touch, and the refusal is the same as for one that was never there.
    """
    record = await session.get(RequestLineRecord, line_id)
    if record is None or record.tenant_id != tenant_id or record.request_id != request_id:
        raise NotFoundError(
            operation="get_request_line",
            entity="request_line",
            identifier=str(line_id),
            detail="no line matched in this list",
        )
    return to_entity(record)


async def list_for_request(
    session: AsyncSession, *, tenant_id: UUID, request_id: UUID
) -> list[RequestLineModel]:
    """Return a list's lines in the order the customer wrote them."""
    statement = (
        select(RequestLineRecord)
        .where(
            RequestLineRecord.tenant_id == tenant_id,
            RequestLineRecord.request_id == request_id,
        )
        .order_by(RequestLineRecord.position)
    )
    records = (await session.execute(statement)).scalars().all()
    return [to_entity(record) for record in records]
