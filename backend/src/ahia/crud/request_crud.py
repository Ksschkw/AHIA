"""Persistence for customer lists: one table, one entity, nothing else.

A repository touches its entity's storage and no other's. Reading a line, pricing a list, or
resolving
whether a customer is new belongs to a service; this file only stores and returns lists.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import NotFoundError
from ahia.models.entities.request_model import RequestModel, RequestStatus

_TABLE_NAME: Final[str] = "requests"
_STATUS_LENGTH: Final[int] = 24
_PHONE_LENGTH: Final[int] = 32
_NAME_LENGTH: Final[int] = 120
_DIGEST_LENGTH: Final[int] = 128


class RequestRecord(Base):
    """The persistence representation of one customer's list."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    #: The one identity a customer has here, stored canonically so that every way of writing the
    #: number reaches the same history. Indexed per tenant, because "what did Toba order last
    #: time" is the query this table exists to answer.
    customer_phone: Mapped[str] = mapped_column(String(_PHONE_LENGTH), nullable=False, index=True)
    customer_name: Mapped[str | None] = mapped_column(String(_NAME_LENGTH), nullable=True)
    status: Mapped[str] = mapped_column(String(_STATUS_LENGTH), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_token_digest: Mapped[str | None] = mapped_column(String(_DIGEST_LENGTH), nullable=True)
    transporter_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    transporter_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    waybill_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dispatch_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    tracking_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_requests_tenant_status", "tenant_id", "status"),
        Index("ix_requests_tenant_customer", "tenant_id", "customer_phone"),
    )


def to_entity(record: RequestRecord) -> RequestModel:
    return RequestModel(
        id=record.id,
        tenant_id=record.tenant_id,
        customer_phone=record.customer_phone,
        customer_name=record.customer_name,
        status=RequestStatus(record.status),
        note=record.note,
        public_token_digest=record.public_token_digest,
        transporter_name=record.transporter_name,
        transporter_phone=record.transporter_phone,
        waybill_number=record.waybill_number,
        dispatch_cost=record.dispatch_cost,
        tracking_url=record.tracking_url,
        dispatched_at=record.dispatched_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def apply_entity(record: RequestRecord, entity: RequestModel) -> None:
    record.tenant_id = entity.tenant_id
    record.customer_phone = entity.customer_phone
    record.customer_name = entity.customer_name
    record.status = entity.status.value
    record.note = entity.note
    record.public_token_digest = entity.public_token_digest
    record.created_at = entity.created_at
    record.updated_at = entity.updated_at


async def create(session: AsyncSession, request: RequestModel) -> RequestModel:
    """Store a list and return it as the entity."""
    record = RequestRecord(id=request.id)
    apply_entity(record, request)
    session.add(record)
    await session.flush()
    return to_entity(record)


async def update(session: AsyncSession, request: RequestModel) -> RequestModel:
    """Store a list's current state, which is how pricing and confirmation are recorded."""
    record = await session.get(RequestRecord, request.id)
    if record is None:
        raise NotFoundError(
            operation="update_request",
            entity="request",
            identifier=str(request.id),
            detail="no list matched",
        )
    apply_entity(record, request)
    await session.flush()
    return to_entity(record)


async def get_by_id(
    session: AsyncSession, *, tenant_id: UUID, request_id: UUID
) -> RequestModel | None:
    """Return one list, or None."""
    record = await session.get(RequestRecord, request_id)
    if record is None or record.tenant_id != tenant_id:
        return None
    return to_entity(record)


async def require_by_id(
    session: AsyncSession, *, tenant_id: UUID, request_id: UUID
) -> RequestModel:
    """Return one list, or refuse as if it did not exist - which, for another business's list, it
    did."""
    found = await get_by_id(session, tenant_id=tenant_id, request_id=request_id)
    if found is None:
        raise NotFoundError(
            operation="get_request",
            entity="request",
            identifier=str(request_id),
            detail="no list matched in this business",
        )
    return found


async def get_by_token_digest(session: AsyncSession, *, token_digest: str) -> RequestModel | None:
    """Return the list a token names, or None.

    One query on a digest with an index behind it, and no tenant scope: the holder of the token does
    not
    have a tenant, they have the address of their own list.
    """
    statement = select(RequestRecord).where(RequestRecord.public_token_digest == token_digest)
    record = (await session.execute(statement)).scalars().first()
    return to_entity(record) if record is not None else None


async def list_for_tenant(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    status: RequestStatus | None = None,
    customer_phone: str | None = None,
    limit: int = 100,
) -> list[RequestModel]:
    """Return a business's lists, newest first, optionally for one customer or one state."""
    statement = select(RequestRecord).where(RequestRecord.tenant_id == tenant_id)
    if status is not None:
        statement = statement.where(RequestRecord.status == status.value)
    if customer_phone is not None:
        statement = statement.where(RequestRecord.customer_phone == customer_phone)
    statement = statement.order_by(RequestRecord.created_at.desc()).limit(limit)
    records = (await session.execute(statement)).scalars().all()
    return [to_entity(record) for record in records]
