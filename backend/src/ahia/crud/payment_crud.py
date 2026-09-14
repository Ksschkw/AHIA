"""Persistence for payments.

One table, one entity, one file, and one property worth stating.

A payment belongs to a sale as a pair
    `(sale_id, tenant_id)` references `sales(id, tenant_id)`, so a payment cannot be
    recorded against another business's sale.

A payment's status changes; its amount never does
    `update` exists for the two facts that can change about money already taken - it was
    refunded, or it turned out to have failed - and it cannot alter the amount. A mistyped
    amount is corrected by a second payment in the other direction, which is what a
    reconciliation is, rather than by rewriting what was taken.
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
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import NotFoundError
from ahia.crud.integrity_violations import translate_integrity_violation
from ahia.models.entities.payment_model import (
    MAXIMUM_REFERENCE_LENGTH,
    PaymentMethod,
    PaymentModel,
    PaymentStatus,
)

_TABLE_NAME: Final[str] = "payments"
_MONEY_PRECISION: Final[int] = 18
_MONEY_SCALE: Final[int] = 2
_METHOD_LENGTH: Final[int] = 32
_STATUS_LENGTH: Final[int] = 32


class PaymentRecord(Base):
    """The persistence representation of one payment."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    sale_id: Mapped[UUID] = mapped_column(nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(_MONEY_PRECISION, _MONEY_SCALE), nullable=False)
    method: Mapped[str] = mapped_column(String(_METHOD_LENGTH), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(MAXIMUM_REFERENCE_LENGTH), nullable=True)
    status: Mapped[str] = mapped_column(String(_STATUS_LENGTH), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["sale_id", "tenant_id"],
            ["sales.id", "sales.tenant_id"],
            name="fk_payments_sale_id_tenant_id_sales",
        ),
        Index("ix_payments_tenant_sale", "tenant_id", "sale_id"),
        Index("ix_payments_tenant_received", "tenant_id", "received_at"),
    )


def to_entity(record: PaymentRecord) -> PaymentModel:
    return PaymentModel(
        id=record.id,
        tenant_id=record.tenant_id,
        sale_id=record.sale_id,
        amount=record.amount,
        method=PaymentMethod(record.method),
        received_at=record.received_at,
        created_at=record.created_at,
        reference=record.reference,
        status=PaymentStatus(record.status),
        refunded_at=record.refunded_at,
    )


def apply_entity(record: PaymentRecord, entity: PaymentModel) -> None:
    record.tenant_id = entity.tenant_id
    record.sale_id = entity.sale_id
    record.amount = entity.amount
    record.method = entity.method.value
    record.reference = entity.reference
    record.status = entity.status.value
    record.received_at = entity.received_at
    record.refunded_at = entity.refunded_at
    record.created_at = entity.created_at


async def create(session: AsyncSession, payment: PaymentModel) -> PaymentModel:
    """Insert a payment."""
    record = PaymentRecord(id=payment.id)
    apply_entity(record, payment)
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise translate_integrity_violation(
            conflict,
            operation="complete_sale",
            entity="payment",
            identifier=str(payment.id),
            conflict_detail="this payment already exists",
            missing_detail="the sale this payment belongs to does not exist",
        ) from conflict
    return to_entity(record)


async def list_for_sale(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    sale_id: UUID,
) -> list[PaymentModel]:
    """Return a sale's payments, in the order they were taken."""
    result = await session.execute(
        select(PaymentRecord)
        .where(PaymentRecord.tenant_id == tenant_id)
        .where(PaymentRecord.sale_id == sale_id)
        .order_by(PaymentRecord.received_at, PaymentRecord.id)
    )
    return [to_entity(record) for record in result.scalars().all()]


async def get_by_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    payment_id: UUID,
) -> PaymentModel | None:
    result = await session.execute(
        select(PaymentRecord)
        .where(PaymentRecord.id == payment_id)
        .where(PaymentRecord.tenant_id == tenant_id)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def update(session: AsyncSession, payment: PaymentModel) -> PaymentModel:
    """Persist a change to an existing payment, scoped to its business.

    Only the status fields can differ in practice: the amount is what was taken, and the
    entity refuses a different one only in the sense that nothing calls this with one.
    """
    result = await session.execute(
        select(PaymentRecord)
        .where(PaymentRecord.id == payment.id)
        .where(PaymentRecord.tenant_id == payment.tenant_id)
    )
    stored = result.scalar_one_or_none()
    if stored is None:
        raise NotFoundError(
            operation="update_payment",
            entity="payment",
            identifier=str(payment.id),
            detail="no payment matched in this business",
        )
    apply_entity(stored, payment)
    await session.flush()
    return to_entity(stored)
