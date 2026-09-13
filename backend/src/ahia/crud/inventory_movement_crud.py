"""Persistence for the inventory movement ledger.

One table, one entity, one file, and **no update or delete function exists in this
module**. That absence is the design: a correction is another movement, so this file
offers `record` and readers, and nothing else. A test asserts the absence mechanically,
because a helper added later "just to fix a typo in a note" would quietly turn an audit
trail into a table somebody can rewrite.

The database enforces the same rule
    A trigger refuses UPDATE and DELETE on this table. The application having no such
    function is a convention; the trigger is the guarantee, and it holds for a psql
    session and a future service that has not read this docstring. The cost is one
    trigger on a table that is only ever inserted into, and the consequence is that a
    mistake in the ledger is corrected by recording a compensating movement - which is the
    accounting rule anyway, and the only kind of correction that can be audited.

The product reference is composite
    `(product_id, tenant_id)` against `products(id, tenant_id)`, so a movement cannot
    describe another business's product. The same anchor as everywhere else in the
    catalogue, for the same reason.

`movement_type` is stored as text rather than a PostgreSQL enum
    A native enum makes adding a member a migration, and the specification's list is the
    kind that grows - shipment types arrive with multi-location support. The entity
    validates the vocabulary, so an unknown value cannot be written; what the column type
    decides is how expensive the next member is.
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
    Text,
    func,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.models.entities.inventory_movement_model import (
    MAXIMUM_REFERENCE_TYPE_LENGTH,
    InventoryMovementModel,
    MovementType,
)

_TABLE_NAME: Final[str] = "inventory_movements"
_QUANTITY_PRECISION: Final[int] = 18
_QUANTITY_SCALE: Final[int] = 3
_MOVEMENT_TYPE_LENGTH: Final[int] = 32


class InventoryMovementRecord(Base):
    """The persistence representation of one ledger entry."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    movement_type: Mapped[str] = mapped_column(String(_MOVEMENT_TYPE_LENGTH), nullable=False)
    quantity_delta: Mapped[Decimal] = mapped_column(
        Numeric(_QUANTITY_PRECISION, _QUANTITY_SCALE), nullable=False
    )
    quantity_before: Mapped[Decimal] = mapped_column(
        Numeric(_QUANTITY_PRECISION, _QUANTITY_SCALE), nullable=False
    )
    quantity_after: Mapped[Decimal] = mapped_column(
        Numeric(_QUANTITY_PRECISION, _QUANTITY_SCALE), nullable=False
    )
    reference_type: Mapped[str | None] = mapped_column(
        String(MAXIMUM_REFERENCE_TYPE_LENGTH), nullable=True
    )
    reference_id: Mapped[UUID | None] = mapped_column(nullable=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    device_id: Mapped[UUID | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    # Set by offline sync, so a movement that arrived twice can be recognised as the same
    # one rather than counted twice. Unique per tenant where present.
    operation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["product_id", "tenant_id"],
            ["products.id", "products.tenant_id"],
            name="fk_inventory_movements_product_id_tenant_id_products",
        ),
        # The history of one product, which is the query a stock dispute is settled with.
        Index(
            "ix_inventory_movements_tenant_product_occurred",
            "tenant_id",
            "product_id",
            "occurred_at",
        ),
        # The whole business's recent history, for the activity view.
        Index("ix_inventory_movements_tenant_occurred", "tenant_id", "occurred_at"),
        # One movement per offline operation. Partial, because most movements online
        # carry no operation identifier at all.
        Index(
            "uq_inventory_movements_tenant_operation",
            "tenant_id",
            "operation_id",
            unique=True,
            postgresql_where=text("operation_id IS NOT NULL"),
        ),
    )


def to_entity(record: InventoryMovementRecord) -> InventoryMovementModel:
    return InventoryMovementModel(
        id=record.id,
        tenant_id=record.tenant_id,
        product_id=record.product_id,
        movement_type=MovementType(record.movement_type),
        quantity_delta=record.quantity_delta,
        quantity_before=record.quantity_before,
        quantity_after=record.quantity_after,
        actor_id=record.actor_id,
        device_id=record.device_id,
        operation_id=record.operation_id,
        occurred_at=record.occurred_at,
        created_at=record.created_at,
        reference_type=record.reference_type,
        reference_id=record.reference_id,
        note=record.note,
    )


def apply_entity(record: InventoryMovementRecord, entity: InventoryMovementModel) -> None:
    record.tenant_id = entity.tenant_id
    record.product_id = entity.product_id
    record.movement_type = entity.movement_type.value
    record.quantity_delta = entity.quantity_delta
    record.quantity_before = entity.quantity_before
    record.quantity_after = entity.quantity_after
    record.reference_type = entity.reference_type
    record.reference_id = entity.reference_id
    record.actor_id = entity.actor_id
    record.device_id = entity.device_id
    record.operation_id = entity.operation_id
    record.occurred_at = entity.occurred_at
    record.created_at = entity.created_at
    record.note = entity.note


async def record(session: AsyncSession, movement: InventoryMovementModel) -> InventoryMovementModel:
    """Append one movement to the ledger.

    There is no `update` and no `delete` beside this function, and the table refuses both
    at the database level. The only way to correct the ledger is to append to it.
    """
    record_row = InventoryMovementRecord(id=movement.id)
    apply_entity(record_row, movement)
    session.add(record_row)
    await session.flush()
    return to_entity(record_row)


async def list_for_product(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    product_id: UUID,
    limit: int = 100,
) -> list[InventoryMovementModel]:
    """Return a product's history, most recent first."""
    result = await session.execute(
        select(InventoryMovementRecord)
        .where(InventoryMovementRecord.tenant_id == tenant_id)
        .where(InventoryMovementRecord.product_id == product_id)
        .order_by(InventoryMovementRecord.occurred_at.desc(), InventoryMovementRecord.id.desc())
        .limit(limit)
    )
    return [to_entity(record_row) for record_row in result.scalars().all()]


async def list_for_tenant(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    limit: int = 100,
) -> list[InventoryMovementModel]:
    """Return a business's recent movements, most recent first."""
    result = await session.execute(
        select(InventoryMovementRecord)
        .where(InventoryMovementRecord.tenant_id == tenant_id)
        .order_by(InventoryMovementRecord.occurred_at.desc(), InventoryMovementRecord.id.desc())
        .limit(limit)
    )
    return [to_entity(record_row) for record_row in result.scalars().all()]


async def count_for_product(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    product_id: UUID,
) -> int:
    """Return how many movements a product's history holds."""
    result = await session.execute(
        select(func.count())
        .select_from(InventoryMovementRecord)
        .where(InventoryMovementRecord.tenant_id == tenant_id)
        .where(InventoryMovementRecord.product_id == product_id)
    )
    return int(result.scalar_one())


async def get_by_operation_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    operation_id: UUID,
) -> InventoryMovementModel | None:
    """Return the movement an offline operation produced, if it already arrived.

    This is what makes a replayed sync operation idempotent: the same operation
    identifier is recognised rather than applied a second time.
    """
    result = await session.execute(
        select(InventoryMovementRecord)
        .where(InventoryMovementRecord.tenant_id == tenant_id)
        .where(InventoryMovementRecord.operation_id == operation_id)
    )
    record_row = result.scalar_one_or_none()
    return None if record_row is None else to_entity(record_row)
