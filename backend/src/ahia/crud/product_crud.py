"""Persistence for the product entity.

One table, one entity, one file. Four properties are worth stating.

Prices are NUMERIC, and the columns say so
    `Numeric(18, 2)` for prices and `Numeric(18, 3)` for quantities. The driver returns
    them as Decimal, so a value read back is the value that was stored - which is the
    whole reason money is not a float in this schema.

The composite anchor the specification's cross-tenant keys depend on
    `UNIQUE(id, tenant_id)` exists so that a later table can reference
    `products(id, tenant_id)` as a pair: a sale line belonging to business A can then
    never point at a product belonging to business B, and the database enforces it
    rather than a service remembering to. M8.1.4 deferred this constraint until the
    table it anchors existed; this is that table.

Uniqueness is per tenant, and the two optional codes are unique only when present
    `UNIQUE(tenant_id, slug)` always applies. SKU and barcode are unique per tenant
    *where they are not null*, because a business that does not use SKUs must be able
    to leave the column empty on every row - a plain unique constraint would forbid
    the second empty one. These are partial unique indexes, which is the only way to
    express "unique when set" in PostgreSQL.

No separate index on `tenant_id`
    The composite unique index on `(tenant_id, slug)` has `tenant_id` as its leading
    column, so it already serves tenant-scoped listings and the foreign key's own
    check. A second index on the same leading column would be storage paid for twice.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy import (
    update as update_stmt,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import NotFoundError
from ahia.crud.integrity_violations import constraint_name, translate_integrity_violation
from ahia.models.entities.money import ZERO_QUANTITY
from ahia.models.entities.product_model import (
    MAXIMUM_IDENTIFIER_LENGTH,
    MAXIMUM_NAME_LENGTH,
    MAXIMUM_SLUG_LENGTH,
    ProductModel,
)

_TABLE_NAME: Final[str] = "products"
_PUBLIC_TOKEN_LENGTH: Final[int] = 64
_PRICE_PRECISION: Final[int] = 18
_PRICE_SCALE: Final[int] = 2
_QUANTITY_SCALE: Final[int] = 3

#: Why a create or an update was refused, per constraint. The classification of the
#: failure (a duplicate rather than a missing reference) is shared; what each
#: constraint *means* is this table's business, so it is answered here.
_CONFLICT_DETAILS: Final[dict[str, str]] = {
    "uq_products_tenant_id_slug": "a product with this name already exists in this business",
    "uq_products_tenant_sku": "another product in this business already uses this SKU",
    "uq_products_tenant_barcode": ("another product in this business already uses this barcode"),
    "uq_products_public_token": "this public token is already in use",
}

_MISSING_REFERENCE: Final[str] = "the business or category this product references does not exist"


class ProductRecord(Base):
    """The persistence representation of one product."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    # The composite unique below leads with tenant_id, so it doubles as this foreign
    # key's supporting index.
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    # No column-level foreign key: the reference is composite, declared in
    # __table_args__ below, so a product cannot point at another business's category.
    category_id: Mapped[UUID | None] = mapped_column(nullable=True)
    name: Mapped[str] = mapped_column(String(MAXIMUM_NAME_LENGTH), nullable=False)
    slug: Mapped[str] = mapped_column(String(MAXIMUM_SLUG_LENGTH), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sku: Mapped[str | None] = mapped_column(String(MAXIMUM_IDENTIFIER_LENGTH), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(MAXIMUM_IDENTIFIER_LENGTH), nullable=True)
    #: Nullable on purpose: an item with no price of its own follows the price its group carries,
    #: which is how "all of the 21D are 350" is one number and not twenty.
    selling_price: Mapped[Decimal | None] = mapped_column(
        Numeric(_PRICE_PRECISION, _PRICE_SCALE), nullable=True
    )
    cost_price: Mapped[Decimal | None] = mapped_column(
        Numeric(_PRICE_PRECISION, _PRICE_SCALE), nullable=True
    )
    #: What it goes for on a list rather than at the counter. Null means the group decides, which is
    #: how a whole grade ends up on one price with a few exceptions that carry their own.
    wholesale_price: Mapped[Decimal | None] = mapped_column(
        Numeric(_PRICE_PRECISION, _PRICE_SCALE), nullable=True
    )
    #: Pieces in a pack, when this item differs from its group. Null means the group decides.
    pieces_per_pack: Mapped[int | None] = mapped_column(Integer, nullable=True)
    low_stock_threshold: Mapped[Decimal] = mapped_column(
        Numeric(_PRICE_PRECISION, _QUANTITY_SCALE), nullable=False, default=ZERO_QUANTITY
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Unique but nullable: PostgreSQL allows any number of nulls in a unique index, so
    # an unpublished product holds no token and no two published products share one.
    public_token: Mapped[str | None] = mapped_column(
        String(_PUBLIC_TOKEN_LENGTH), nullable=True, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # The cross-tenant anchor: a later table references (id, tenant_id), so a row
        # from one business can never point at another business's product.
        UniqueConstraint("id", "tenant_id", name="uq_products_id_tenant_id"),
        UniqueConstraint("tenant_id", "slug", name="uq_products_tenant_id_slug"),
        # The category reference is composite, `(category_id, tenant_id)` against
        # `categories(id, tenant_id)`, so the database itself refuses a product in one
        # business that points at another business's category. A plain foreign key on
        # category_id could not: the identifier is valid in every tenant.
        #
        # MATCH SIMPLE is the default and is what is wanted here: when category_id is
        # null the constraint is not enforced, so an uncategorised product is legal.
        ForeignKeyConstraint(
            ["category_id", "tenant_id"],
            ["categories.id", "categories.tenant_id"],
            name="fk_products_category_id_tenant_id_categories",
        ),
        # Serves the composite foreign key's own check and the storefront's
        # "published products in this category" query, which always filters by tenant.
        Index("ix_products_tenant_category", "tenant_id", "category_id"),
        # Unique only where a value exists. Without the predicate, a business that does
        # not use barcodes could store exactly one product.
        Index(
            "uq_products_tenant_sku",
            "tenant_id",
            "sku",
            unique=True,
            postgresql_where=text("sku IS NOT NULL"),
        ),
        Index(
            "uq_products_tenant_barcode",
            "tenant_id",
            "barcode",
            unique=True,
            postgresql_where=text("barcode IS NOT NULL"),
        ),
    )


def to_entity(record: ProductRecord) -> ProductModel:
    return ProductModel(
        id=record.id,
        tenant_id=record.tenant_id,
        name=record.name,
        slug=record.slug,
        selling_price=record.selling_price,
        created_at=record.created_at,
        updated_at=record.updated_at,
        category_id=record.category_id,
        description=record.description,
        sku=record.sku,
        barcode=record.barcode,
        cost_price=record.cost_price,
        wholesale_price=record.wholesale_price,
        pieces_per_pack=record.pieces_per_pack,
        low_stock_threshold=record.low_stock_threshold,
        is_active=record.is_active,
        is_published=record.is_published,
        public_token=record.public_token,
    )


def apply_entity(record: ProductRecord, entity: ProductModel) -> None:
    record.tenant_id = entity.tenant_id
    record.category_id = entity.category_id
    record.name = entity.name
    record.slug = entity.slug
    record.description = entity.description
    record.sku = entity.sku
    record.barcode = entity.barcode
    record.selling_price = entity.selling_price
    record.wholesale_price = entity.wholesale_price
    record.pieces_per_pack = entity.pieces_per_pack
    record.cost_price = entity.cost_price
    record.low_stock_threshold = entity.low_stock_threshold
    record.is_active = entity.is_active
    record.is_published = entity.is_published
    record.public_token = entity.public_token
    record.created_at = entity.created_at
    record.updated_at = entity.updated_at


def _conflict_detail(conflict: IntegrityError) -> str:
    """Return what the violated constraint means in this table's vocabulary."""
    name = constraint_name(conflict)
    return _CONFLICT_DETAILS.get(name, f"this product collides with an existing one ({name})")


async def create(session: AsyncSession, product: ProductModel) -> ProductModel:
    """Insert a product, naming the rule that refused it when one does."""
    record = ProductRecord(id=product.id)
    apply_entity(record, product)
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise translate_integrity_violation(
            conflict,
            operation="create_product",
            entity="product",
            identifier=str(product.id),
            conflict_detail=_conflict_detail(conflict),
            missing_detail=_MISSING_REFERENCE,
        ) from conflict
    return to_entity(record)


async def get_by_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    product_id: UUID,
) -> ProductModel | None:
    """Return a product by identifier, scoped to the business that owns it.

    The tenant is part of the where clause rather than checked after loading, so a
    product identifier from another business cannot be read even by accident.
    """
    result = await session.execute(
        select(ProductRecord)
        .where(ProductRecord.id == product_id)
        .where(ProductRecord.tenant_id == tenant_id)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def require_by_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    product_id: UUID,
) -> ProductModel:
    product = await get_by_id(session, tenant_id=tenant_id, product_id=product_id)
    if product is None:
        raise NotFoundError(
            operation="fetch_product",
            entity="product",
            identifier=str(product_id),
            detail="no product matched in this business",
        )
    return product


async def get_by_slug(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    slug: str,
) -> ProductModel | None:
    """Return a product by the slug derived from its name."""
    result = await session.execute(
        select(ProductRecord)
        .where(ProductRecord.tenant_id == tenant_id)
        .where(ProductRecord.slug == slug)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def get_by_public_token(session: AsyncSession, public_token: str) -> ProductModel | None:
    """Return the product a public link addresses.

    Not tenant-scoped, and deliberately so: the token *is* the address, it is globally
    unique, and a caller reaching a storefront link does not know which business owns
    it. Every other lookup in this file takes a tenant because every other lookup is
    reached by an authenticated request.
    """
    result = await session.execute(
        select(ProductRecord).where(ProductRecord.public_token == public_token)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def list_for_tenant(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    include_inactive: bool = True,
) -> list[ProductModel]:
    """Return a business's products, in the order a person reads them.

    Inactive products are included by default: this is the management view, and a
    product that has been withdrawn still needs to be findable so it can be brought
    back. The storefront asks for the published ones instead, through its own query.
    """
    statement = select(ProductRecord).where(ProductRecord.tenant_id == tenant_id)
    if not include_inactive:
        statement = statement.where(ProductRecord.is_active.is_(True))
    result = await session.execute(statement.order_by(ProductRecord.name, ProductRecord.id))
    return [to_entity(record) for record in result.scalars().all()]


async def list_by_ids(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    product_ids: set[UUID] | list[UUID],
) -> list[ProductModel]:
    """Return products matching identifiers, scoped to one business."""
    if not product_ids:
        return []
    result = await session.execute(
        select(ProductRecord)
        .where(ProductRecord.tenant_id == tenant_id)
        .where(ProductRecord.id.in_(product_ids))
    )
    return [to_entity(record) for record in result.scalars().all()]


async def list_published_for_tenant(
    session: AsyncSession,
    tenant_id: UUID,
) -> list[ProductModel]:
    """Return the products a business is showing to customers, in reading order."""
    result = await session.execute(
        select(ProductRecord)
        .where(ProductRecord.tenant_id == tenant_id)
        .where(ProductRecord.is_published.is_(True))
        .where(ProductRecord.is_active.is_(True))
        .order_by(ProductRecord.name, ProductRecord.id)
    )
    return [to_entity(record) for record in result.scalars().all()]


async def update(session: AsyncSession, product: ProductModel) -> ProductModel:
    """Persist changes to an existing product, scoped to its business."""
    result = await session.execute(
        select(ProductRecord)
        .where(ProductRecord.id == product.id)
        .where(ProductRecord.tenant_id == product.tenant_id)
    )
    stored = result.scalar_one_or_none()
    if stored is None:
        raise NotFoundError(
            operation="update_product",
            entity="product",
            identifier=str(product.id),
            detail="no product matched in this business",
        )
    apply_entity(stored, product)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise translate_integrity_violation(
            conflict,
            operation="update_product",
            entity="product",
            identifier=str(product.id),
            conflict_detail=_conflict_detail(conflict),
        ) from conflict
    return to_entity(stored)


async def count_for_tenant(session: AsyncSession, tenant_id: UUID) -> int:
    """Return the number of products in a business."""
    result = await session.execute(
        select(func.count()).select_from(ProductRecord).where(ProductRecord.tenant_id == tenant_id)
    )
    return int(result.scalar_one())


async def count_by_category(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    category_id: UUID,
) -> int:
    """Return the count of products assigned to a category in a business."""
    result = await session.execute(
        select(func.count())
        .select_from(ProductRecord)
        .where(ProductRecord.tenant_id == tenant_id)
        .where(ProductRecord.category_id == category_id)
    )
    return int(result.scalar_one())


async def reparent_category_products(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    old_category_id: UUID,
    new_category_id: UUID | None,
) -> int:
    """Move all products of old_category_id to new_category_id (or null)."""
    result = await session.execute(
        update_stmt(ProductRecord)
        .where(ProductRecord.tenant_id == tenant_id)
        .where(ProductRecord.category_id == old_category_id)
        .values(category_id=new_category_id)
    )
    return result.rowcount  # type: ignore[return-value]
