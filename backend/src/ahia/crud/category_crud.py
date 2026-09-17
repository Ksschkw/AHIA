"""Persistence for the category entity.

One table, one entity, one file. Two properties are worth stating.

The uniqueness rule is composite and per tenant
    `UNIQUE(tenant_id, slug)` is the first composite constraint in this schema. It
    encodes the domain rule directly: two businesses may each have a "Drinks"
    category, and one business may not have two, however the name was typed. The
    database enforces it, so a race between two requests cannot create the duplicate
    that a read-then-write check would miss.

A category belongs to a business, and the foreign key says so
    `tenant_id` references `tenants.id`. Deleting a category is therefore a decision
    about the products that reference it, which is not this file's decision to make:
    the join lives in the service when products exist (M9.1.4 onward), and until then
    this table is only ever read, inserted and updated.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import NotFoundError
from ahia.crud.integrity_violations import translate_integrity_violation
from ahia.models.entities.category_model import CategoryModel

_TABLE_NAME: Final[str] = "categories"
_NAME_LENGTH: Final[int] = 120
_SLUG_LENGTH: Final[int] = 63


#: The numeric shape a price is stored in, matching the product table so a value means the
#: same thing wherever it is read from.
_PRICE_PRECISION: Final[int] = 18
_PRICE_SCALE: Final[int] = 2


class CategoryRecord(Base):
    """The persistence representation of one product grouping."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(_NAME_LENGTH), nullable=False)
    slug: Mapped[str] = mapped_column(String(_SLUG_LENGTH), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The group's own prices. A group is a grade - "21D", "Privacy", "Grains" - and this is
    #: common price lives, so the trader sets one number instead of typing it on every item.
    default_normal_price: Mapped[Decimal | None] = mapped_column(
        Numeric(_PRICE_PRECISION, _PRICE_SCALE), nullable=True
    )
    default_wholesale_price: Mapped[Decimal | None] = mapped_column(
        Numeric(_PRICE_PRECISION, _PRICE_SCALE), nullable=True
    )
    default_pieces_per_pack: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # Per-tenant uniqueness, not global: a category is a business's own word for
        # what it sells. The constraint name comes from the metadata naming
        # convention, so it is the same shape as every other constraint here.
        UniqueConstraint("tenant_id", "slug"),
        # The cross-tenant anchor. A product carries `(category_id, tenant_id)` as a
        # composite foreign key to this pair, which is what makes it impossible for a
        # product in one business to point at another business's category. A plain
        # foreign key on the identifier cannot express that: the identifier is unique
        # and therefore valid wherever it is used.
        UniqueConstraint("id", "tenant_id", name="uq_categories_id_tenant_id"),
    )


def to_entity(record: CategoryRecord) -> CategoryModel:
    return CategoryModel(
        id=record.id,
        tenant_id=record.tenant_id,
        name=record.name,
        slug=record.slug,
        description=record.description,
        default_normal_price=record.default_normal_price,
        default_wholesale_price=record.default_wholesale_price,
        default_pieces_per_pack=record.default_pieces_per_pack,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def apply_entity(record: CategoryRecord, entity: CategoryModel) -> None:
    record.tenant_id = entity.tenant_id
    record.name = entity.name
    record.slug = entity.slug
    record.description = entity.description
    record.default_normal_price = entity.default_normal_price
    record.default_wholesale_price = entity.default_wholesale_price
    record.default_pieces_per_pack = entity.default_pieces_per_pack
    record.created_at = entity.created_at
    record.updated_at = entity.updated_at


async def create(session: AsyncSession, category: CategoryModel) -> CategoryModel:
    """Insert a category, translating a name collision into a typed conflict."""
    record = CategoryRecord(id=category.id)
    apply_entity(record, category)
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise translate_integrity_violation(
            conflict,
            operation="create_category",
            entity="category",
            identifier=str(category.id),
            conflict_detail="a category with this name already exists in this business",
            missing_detail="the business this category belongs to does not exist",
        ) from conflict
    return to_entity(record)


async def get_by_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    category_id: UUID,
) -> CategoryModel | None:
    """Return a category by identifier, scoped to the business that owns it.

    The tenant is part of the where clause rather than checked after loading, so a
    category identifier from another business cannot be read even by accident.
    """
    result = await session.execute(
        select(CategoryRecord)
        .where(CategoryRecord.id == category_id)
        .where(CategoryRecord.tenant_id == tenant_id)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def require_by_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    category_id: UUID,
) -> CategoryModel:
    category = await get_by_id(session, tenant_id=tenant_id, category_id=category_id)
    if category is None:
        raise NotFoundError(
            operation="fetch_category",
            entity="category",
            identifier=str(category_id),
            detail="no category matched in this business",
        )
    return category


async def get_by_slug(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    slug: str,
) -> CategoryModel | None:
    """Return a category by the slug derived from its name."""
    result = await session.execute(
        select(CategoryRecord)
        .where(CategoryRecord.tenant_id == tenant_id)
        .where(CategoryRecord.slug == slug)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def list_for_tenant(session: AsyncSession, tenant_id: UUID) -> list[CategoryModel]:
    """Return every category in a business, in the order a person reads them."""
    result = await session.execute(
        select(CategoryRecord)
        .where(CategoryRecord.tenant_id == tenant_id)
        .order_by(CategoryRecord.name, CategoryRecord.id)
    )
    return [to_entity(record) for record in result.scalars().all()]


async def update(session: AsyncSession, category: CategoryModel) -> CategoryModel:
    """Persist changes to an existing category, scoped to its business."""
    result = await session.execute(
        select(CategoryRecord)
        .where(CategoryRecord.id == category.id)
        .where(CategoryRecord.tenant_id == category.tenant_id)
    )
    stored = result.scalar_one_or_none()
    if stored is None:
        raise NotFoundError(
            operation="update_category",
            entity="category",
            identifier=str(category.id),
            detail="no category matched in this business",
        )
    apply_entity(stored, category)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise translate_integrity_violation(
            conflict,
            operation="update_category",
            entity="category",
            identifier=str(category.id),
            conflict_detail="the update collides with an existing category",
        ) from conflict
    return to_entity(stored)


async def count_for_tenant(session: AsyncSession, tenant_id: UUID) -> int:
    """Return the number of categories in a business."""
    result = await session.execute(
        select(func.count())
        .select_from(CategoryRecord)
        .where(CategoryRecord.tenant_id == tenant_id)
    )
    return int(result.scalar_one())
