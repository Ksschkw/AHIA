"""Persistence for the inventory projection.

One table, one entity, one file. Three properties are worth stating.

The projection is keyed by product, per tenant
    `UNIQUE(tenant_id, product_id)` and a composite foreign key to
    `products(id, tenant_id)`: one stock state per product in a business, and no way for a
    projection to describe another business's product.

Every mutation goes through `lock_for_product`
    The read-modify-write sequence is the whole hazard in this file. Two workers selling
    the last item at the same time must produce two movements and a projection that
    reflects both, so the row is locked for the duration of the transaction and the
    service computes the new quantity while holding it. A plain read followed by a write
    would lose one of the two sales, and the loss would be invisible: the ledger would be
    right and the number on the screen wrong.

This is a projection and is allowed to be rebuilt
    Nothing here is the truth. A reconciliation job could delete every row in this table
    and reconstruct it from the movement ledger; the ledger has no such path, which is the
    asymmetry that makes it the authority.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import PersistenceError
from ahia.crud.integrity_violations import translate_integrity_violation
from ahia.models.entities.inventory_model import (
    ZERO_QUANTITY,
    InventoryModel,
)

_TABLE_NAME: Final[str] = "inventory"
_QUANTITY_PRECISION: Final[int] = 18
_QUANTITY_SCALE: Final[int] = 3


class InventoryRecord(Base):
    """The persistence representation of one product's stock state."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    quantity_on_hand: Mapped[Decimal] = mapped_column(
        Numeric(_QUANTITY_PRECISION, _QUANTITY_SCALE), nullable=False
    )
    reserved_quantity: Mapped[Decimal] = mapped_column(
        Numeric(_QUANTITY_PRECISION, _QUANTITY_SCALE), nullable=False
    )
    # Incremented by every movement. What an offline client sends back to prove which
    # version it was working from.
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["product_id", "tenant_id"],
            ["products.id", "products.tenant_id"],
            name="fk_inventory_product_id_tenant_id_products",
        ),
        # One stock state per product per business.
        UniqueConstraint("tenant_id", "product_id", name="uq_inventory_tenant_id_product_id"),
    )


def to_entity(record: InventoryRecord) -> InventoryModel:
    return InventoryModel(
        id=record.id,
        tenant_id=record.tenant_id,
        product_id=record.product_id,
        quantity_on_hand=record.quantity_on_hand,
        reserved_quantity=record.reserved_quantity,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def apply_entity(record: InventoryRecord, entity: InventoryModel) -> None:
    record.tenant_id = entity.tenant_id
    record.product_id = entity.product_id
    record.quantity_on_hand = entity.quantity_on_hand
    record.reserved_quantity = entity.reserved_quantity
    record.version = entity.version
    record.created_at = entity.created_at
    record.updated_at = entity.updated_at


async def lock_for_product(
    session: AsyncSession,
    *,
    inventory_id: UUID,
    tenant_id: UUID,
    product_id: UUID,
    now: datetime,
) -> InventoryModel:
    """Return a product's stock state with the row locked, creating it if absent.

    The insert is `ON CONFLICT DO NOTHING` followed by a locking select, so two
    simultaneous first movements on the same product cannot both insert - one waits and
    then reads the other's row. Without that, the second insert would raise on the unique
    constraint and a legitimate concurrent first sale would fail rather than serialize.
    """
    await session.execute(
        postgresql_insert(InventoryRecord)
        .values(
            id=inventory_id,
            tenant_id=tenant_id,
            product_id=product_id,
            quantity_on_hand=ZERO_QUANTITY,
            reserved_quantity=ZERO_QUANTITY,
            version=1,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_inventory_tenant_id_product_id")
    )

    result = await session.execute(
        select(InventoryRecord)
        .where(InventoryRecord.tenant_id == tenant_id)
        .where(InventoryRecord.product_id == product_id)
        # The whole point of this module: everything that moves stock serializes here.
        .with_for_update()
    )
    record = result.scalar_one_or_none()
    if record is None:  # pragma: no cover - the insert above guarantees a row
        raise PersistenceError(
            operation="lock_inventory_for_product",
            entity="inventory",
            identifier=str(product_id),
            detail="row missing immediately after ensure-row-exists",
        )
    return to_entity(record)


async def get_for_product(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    product_id: UUID,
) -> InventoryModel | None:
    """Return a product's stock state without locking it, for a read-only display."""
    result = await session.execute(
        select(InventoryRecord)
        .where(InventoryRecord.tenant_id == tenant_id)
        .where(InventoryRecord.product_id == product_id)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def save(session: AsyncSession, inventory: InventoryModel) -> InventoryModel:
    """Persist a projection that was read through `lock_for_product`.

    No lock is taken here: the caller already holds it, and taking it twice in one
    transaction would be pointless.
    """
    result = await session.execute(
        select(InventoryRecord)
        .where(InventoryRecord.id == inventory.id)
        .where(InventoryRecord.tenant_id == inventory.tenant_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise PersistenceError(
            operation="save_inventory",
            entity="inventory",
            identifier=str(inventory.id),
            detail="no row to update; stock is created through lock_for_product",
        )
    apply_entity(record, inventory)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise translate_integrity_violation(
            conflict,
            operation="save_inventory",
            entity="inventory",
            identifier=str(inventory.id),
            conflict_detail="this product already has a stock record in this business",
        ) from conflict
    return to_entity(record)


async def list_for_tenant(session: AsyncSession, tenant_id: UUID) -> list[InventoryModel]:
    """Return every product's stock state in a business, ordered by product.

    Ordered by identifier rather than by name, because a name lives in another table and
    joining to it here would make this file responsible for two entities. The service
    sorts by name when it has both.
    """
    result = await session.execute(
        select(InventoryRecord)
        .where(InventoryRecord.tenant_id == tenant_id)
        .order_by(InventoryRecord.product_id)
    )
    return [to_entity(record) for record in result.scalars().all()]


async def count_for_tenant(session: AsyncSession, tenant_id: UUID) -> int:
    """Return how many products in a business have a stock record."""
    result = await session.execute(
        select(func.count())
        .select_from(InventoryRecord)
        .where(InventoryRecord.tenant_id == tenant_id)
    )
    return int(result.scalar_one())
