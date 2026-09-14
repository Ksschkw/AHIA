"""Persistence for the sale entity.

One table, one entity, one file. Five properties are worth stating.

The receipt number is unique per business, and the database says so
    `UNIQUE(tenant_id, receipt_number)`. The number is allocated from a counter under a row
    lock in the same transaction that writes the sale, so two tills selling at the same
    moment cannot produce the same receipt - which a read-the-highest-and-add-one approach
    would, silently, and the business would discover it while looking for a missing sale.

An offline operation is recorded once
    `UNIQUE(tenant_id, operation_id)` where the identifier is present, so a replayed sync
    operation returns the original sale instead of selling the same basket twice. That
    index is what makes idempotency a database guarantee rather than a service promise.

The customer reference is composite
    `(customer_id, tenant_id)` against `customers(id, tenant_id)`, so a sale cannot be made
    to another business's customer even if a service forgets to check. `customers` therefore
    carries its own `(id, tenant_id)` anchor, added in the same revision that needs it.

`(id, tenant_id)` on this table is the anchor its children reference
    Sale lines, payments and ledger entries all point back at a sale as a `(sale_id,
    tenant_id)` pair, which is only legal because that pair is unique here. It is the same
    pattern that keeps a product line from belonging to another tenant's sale.

A cancelled sale is a row that changed status
    There is no delete function and no cascade: cancellation is recorded, and the lines and
    payments that explain the money stay exactly where they were.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import NotFoundError
from ahia.crud.integrity_violations import constraint_name, translate_integrity_violation
from ahia.models.entities.sale_model import (
    MAXIMUM_CANCELLATION_REASON_LENGTH,
    MAXIMUM_RECEIPT_NUMBER_LENGTH,
    PaymentStatus,
    SaleModel,
    SaleStatus,
)

_TABLE_NAME: Final[str] = "sales"
_MONEY_PRECISION: Final[int] = 18
_MONEY_SCALE: Final[int] = 2

#: Why a write was refused, per constraint. The classification is shared; what each
#: constraint means is this table's business.
_CONFLICT_DETAILS: Final[dict[str, str]] = {
    "uq_sales_tenant_id_receipt_number": "this receipt number is already used in this business",
    "uq_sales_tenant_id_operation_id": "this operation has already been recorded",
}

_MISSING_REFERENCE: Final[str] = (
    "the business, seller, customer or device this sale references does not exist"
)


class SaleRecord(Base):
    """The persistence representation of one sale."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    receipt_number: Mapped[str] = mapped_column(
        String(MAXIMUM_RECEIPT_NUMBER_LENGTH), nullable=False
    )
    customer_id: Mapped[UUID | None] = mapped_column(nullable=True)
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(_MONEY_PRECISION, _MONEY_SCALE), nullable=False
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(_MONEY_PRECISION, _MONEY_SCALE), nullable=False
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(_MONEY_PRECISION, _MONEY_SCALE), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payment_status: Mapped[str] = mapped_column(String(32), nullable=False)
    seller_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    # A device identifier is an opaque value taken from the authenticated context, so it is
    # a plain reference: the service cannot obtain one that belongs to another business.
    device_id: Mapped[UUID | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    operation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(
        String(MAXIMUM_CANCELLATION_REASON_LENGTH), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # The anchor every child of a sale references as a pair.
        UniqueConstraint("id", "tenant_id", name="uq_sales_id_tenant_id"),
        UniqueConstraint("tenant_id", "receipt_number", name="uq_sales_tenant_id_receipt_number"),
        # Idempotency: one sale per offline operation, per business.
        Index(
            "uq_sales_tenant_id_operation_id",
            "tenant_id",
            "operation_id",
            unique=True,
            postgresql_where=text("operation_id IS NOT NULL"),
        ),
        # A sale cannot be made to another business's customer.
        ForeignKeyConstraint(
            ["customer_id", "tenant_id"],
            ["customers.id", "customers.tenant_id"],
            name="fk_sales_customer_id_tenant_id_customers",
        ),
        # The three queries a sales screen makes.
        Index("ix_sales_tenant_occurred", "tenant_id", "occurred_at"),
        Index("ix_sales_tenant_seller_occurred", "tenant_id", "seller_id", "occurred_at"),
        Index("ix_sales_tenant_customer", "tenant_id", "customer_id"),
    )


def to_entity(record: SaleRecord) -> SaleModel:
    return SaleModel(
        id=record.id,
        tenant_id=record.tenant_id,
        receipt_number=record.receipt_number,
        seller_id=record.seller_id,
        subtotal=record.subtotal,
        discount_amount=record.discount_amount,
        total_amount=record.total_amount,
        occurred_at=record.occurred_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
        customer_id=record.customer_id,
        device_id=record.device_id,
        operation_id=record.operation_id,
        status=SaleStatus(record.status),
        payment_status=PaymentStatus(record.payment_status),
        cancelled_at=record.cancelled_at,
        cancellation_reason=record.cancellation_reason,
    )


def apply_entity(record: SaleRecord, entity: SaleModel) -> None:
    record.tenant_id = entity.tenant_id
    record.receipt_number = entity.receipt_number
    record.customer_id = entity.customer_id
    record.subtotal = entity.subtotal
    record.discount_amount = entity.discount_amount
    record.total_amount = entity.total_amount
    record.status = entity.status.value
    record.payment_status = entity.payment_status.value
    record.seller_id = entity.seller_id
    record.device_id = entity.device_id
    record.operation_id = entity.operation_id
    record.occurred_at = entity.occurred_at
    record.cancelled_at = entity.cancelled_at
    record.cancellation_reason = entity.cancellation_reason
    record.created_at = entity.created_at
    record.updated_at = entity.updated_at


def _conflict_detail(conflict: IntegrityError) -> str:
    name = constraint_name(conflict)
    return _CONFLICT_DETAILS.get(name, f"this sale collides with an existing one ({name})")


async def create(session: AsyncSession, sale: SaleModel) -> SaleModel:
    """Insert a sale, naming the rule that refused it when one does."""
    record = SaleRecord(id=sale.id)
    apply_entity(record, sale)
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise translate_integrity_violation(
            conflict,
            operation="complete_sale",
            entity="sale",
            identifier=str(sale.id),
            conflict_detail=_conflict_detail(conflict),
            missing_detail=_MISSING_REFERENCE,
        ) from conflict
    return to_entity(record)


async def get_by_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    sale_id: UUID,
) -> SaleModel | None:
    """Return a sale by identifier, scoped to the business that made it."""
    result = await session.execute(
        select(SaleRecord).where(SaleRecord.id == sale_id).where(SaleRecord.tenant_id == tenant_id)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def require_by_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    sale_id: UUID,
) -> SaleModel:
    sale = await get_by_id(session, tenant_id=tenant_id, sale_id=sale_id)
    if sale is None:
        raise NotFoundError(
            operation="fetch_sale",
            entity="sale",
            identifier=str(sale_id),
            detail="no sale matched in this business",
        )
    return sale


async def get_by_receipt_number(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    receipt_number: str,
) -> SaleModel | None:
    """Return the sale a customer's receipt refers to."""
    result = await session.execute(
        select(SaleRecord)
        .where(SaleRecord.tenant_id == tenant_id)
        .where(SaleRecord.receipt_number == receipt_number)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def get_by_operation_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    operation_id: UUID,
) -> SaleModel | None:
    """Return the sale an offline operation already produced, if it arrived before.

    This is what makes a replayed operation idempotent: the same identifier is recognised
    and the original sale is returned instead of a second one being written.
    """
    result = await session.execute(
        select(SaleRecord)
        .where(SaleRecord.tenant_id == tenant_id)
        .where(SaleRecord.operation_id == operation_id)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def list_for_tenant(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    limit: int = 100,
) -> list[SaleModel]:
    """Return a business's sales, most recent first."""
    result = await session.execute(
        select(SaleRecord)
        .where(SaleRecord.tenant_id == tenant_id)
        .order_by(SaleRecord.occurred_at.desc(), SaleRecord.id.desc())
        .limit(limit)
    )
    return [to_entity(record) for record in result.scalars().all()]


async def update(session: AsyncSession, sale: SaleModel) -> SaleModel:
    """Persist a change to an existing sale, scoped to its business.

    Used for the two things that legitimately change about a sale: its payment status,
    when payments are added, and its status and reason, when it is cancelled.
    """
    result = await session.execute(
        select(SaleRecord)
        .where(SaleRecord.id == sale.id)
        .where(SaleRecord.tenant_id == sale.tenant_id)
    )
    stored = result.scalar_one_or_none()
    if stored is None:
        raise NotFoundError(
            operation="update_sale",
            entity="sale",
            identifier=str(sale.id),
            detail="no sale matched in this business",
        )
    apply_entity(stored, sale)
    await session.flush()
    return to_entity(stored)


async def count_for_tenant(session: AsyncSession, tenant_id: UUID) -> int:
    """Return how many sales a business has recorded."""
    result = await session.execute(
        select(func.count()).select_from(SaleRecord).where(SaleRecord.tenant_id == tenant_id)
    )
    return int(result.scalar_one())


async def count_for_tenant_since(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    since: datetime,
) -> int:
    """Return how many sales a business has recorded since a moment."""
    result = await session.execute(
        select(func.count())
        .select_from(SaleRecord)
        .where(SaleRecord.tenant_id == tenant_id)
        .where(SaleRecord.occurred_at >= since)
    )
    return int(result.scalar_one())
