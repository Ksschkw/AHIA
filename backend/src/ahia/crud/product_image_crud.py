"""Persistence for the product image entity.

One table, one entity, one file. Five properties are worth stating.

No column is named after a provider
    `storage_provider` and `storage_key` describe where the bytes are in neutral terms.
    A `r2_key` column would turn a provider change into a migration and make every row
    written before it a lie.

The product reference is composite, so an image cannot cross tenants
    `(product_id, tenant_id)` references `products(id, tenant_id)`. A plain foreign key
    on the product identifier would accept an image in one business pointing at another
    business's product, because the identifier alone is valid everywhere. This is the
    same pattern as products referencing categories, and it is why `products` carries its
    own `(id, tenant_id)` anchor.

At most one primary image per product, enforced by a partial unique index
    `UNIQUE(product_id) WHERE is_primary AND removed_at IS NULL`. The service also
    demotes the previous primary in the same transaction, so the common path never
    relies on the constraint - but two simultaneous requests cannot produce two primary
    images, which is the state a read-then-write check would allow.

The object key is unique
    Two rows may not claim the same stored object. A duplicate would mean deleting one
    image deletes another's bytes, and it is exactly the mistake a server-generated key
    is meant to make impossible - so the database says so as well.

The primary image is never a removed one, stated as a check constraint
    `CHECK (NOT (is_primary AND removed_at IS NOT NULL))`. The entity refuses the
    combination; a raw update could otherwise produce it, because the partial unique
    index only excludes removed rows from the count of primaries - it does not forbid a
    removed row from carrying the flag.

A removed row survives until the object is gone
    `removed_at` marks an image the business no longer wants, and
    `reconciliation_reason` records a provider delete that failed. Deleting the row on
    a failed delete would leave bytes nobody is accounting for: storage the tenant is
    not charged for and an operator cannot find.

There is intentionally no `(id, tenant_id)` anchor on this table: nothing references an
image yet, and a composite key that no foreign key uses is schema complexity bought for
a hypothetical. It is added with the table that needs it, as it was for products.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
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
from ahia.models.entities.product_image_model import (
    MAXIMUM_MIME_TYPE_LENGTH,
    MAXIMUM_RECONCILIATION_REASON_LENGTH,
    MAXIMUM_STORAGE_KEY_LENGTH,
    MAXIMUM_STORAGE_PROVIDER_LENGTH,
    ProductImageModel,
)

_TABLE_NAME: Final[str] = "product_images"

#: Why a write was refused, per constraint. The classification of the failure is
#: shared; what each constraint means is this table's business.
_CONFLICT_DETAILS: Final[dict[str, str]] = {
    "uq_product_images_primary": "this product already has a primary image",
    "uq_product_images_storage_key": "another image already claims this stored object",
}

_MISSING_REFERENCE: Final[str] = "the business or product this image belongs to does not exist"


class ProductImageRecord(Base):
    """The persistence representation of one stored picture."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    # The composite reference is declared in __table_args__; a column-level key on the
    # identifier alone would accept a cross-tenant product.
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    storage_provider: Mapped[str] = mapped_column(
        String(MAXIMUM_STORAGE_PROVIDER_LENGTH), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(
        String(MAXIMUM_STORAGE_KEY_LENGTH), nullable=False, unique=True
    )
    mime_type: Mapped[str] = mapped_column(String(MAXIMUM_MIME_TYPE_LENGTH), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciliation_reason: Mapped[str | None] = mapped_column(
        String(MAXIMUM_RECONCILIATION_REASON_LENGTH), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # The entity refuses a removed image that is also the primary one. Stating it
        # here as well means the rule has one meaning whoever writes the row: an UPDATE
        # that bypasses the entity cannot leave a product whose cover is an image
        # nobody wants. The partial unique index below cannot express this - its
        # predicate excludes removed rows, so such a row simply falls outside it.
        CheckConstraint(
            "NOT (is_primary AND removed_at IS NOT NULL)",
            name="primary_image_not_removed",
        ),
        ForeignKeyConstraint(
            ["product_id", "tenant_id"],
            ["products.id", "products.tenant_id"],
            name="fk_product_images_product_id_tenant_id_products",
        ),
        # At most one primary image per product, and only among the images that are
        # still wanted.
        Index(
            "uq_product_images_primary",
            "product_id",
            unique=True,
            postgresql_where=text("is_primary AND removed_at IS NULL"),
        ),
        # Serves the gallery query, which always filters by both.
        Index("ix_product_images_tenant_product", "tenant_id", "product_id"),
        # Reconciliation looks for rows whose object may still exist.
        Index(
            "ix_product_images_pending_reconciliation",
            "tenant_id",
            postgresql_where=text("reconciliation_reason IS NOT NULL"),
        ),
    )


def to_entity(record: ProductImageRecord) -> ProductImageModel:
    return ProductImageModel(
        id=record.id,
        tenant_id=record.tenant_id,
        product_id=record.product_id,
        storage_provider=record.storage_provider,
        storage_key=record.storage_key,
        mime_type=record.mime_type,
        size_bytes=record.size_bytes,
        width=record.width,
        height=record.height,
        checksum_sha256=record.checksum_sha256,
        sort_order=record.sort_order,
        created_at=record.created_at,
        is_primary=record.is_primary,
        removed_at=record.removed_at,
        reconciliation_reason=record.reconciliation_reason,
    )


def apply_entity(record: ProductImageRecord, entity: ProductImageModel) -> None:
    record.tenant_id = entity.tenant_id
    record.product_id = entity.product_id
    record.storage_provider = entity.storage_provider
    record.storage_key = entity.storage_key
    record.mime_type = entity.mime_type
    record.size_bytes = entity.size_bytes
    record.width = entity.width
    record.height = entity.height
    record.checksum_sha256 = entity.checksum_sha256
    record.sort_order = entity.sort_order
    record.is_primary = entity.is_primary
    record.removed_at = entity.removed_at
    record.reconciliation_reason = entity.reconciliation_reason
    record.created_at = entity.created_at


def _conflict_detail(conflict: IntegrityError) -> str:
    name = constraint_name(conflict)
    return _CONFLICT_DETAILS.get(name, f"this image collides with an existing one ({name})")


async def create(session: AsyncSession, image: ProductImageModel) -> ProductImageModel:
    """Insert an image row, naming the rule that refused it when one does."""
    record = ProductImageRecord(id=image.id)
    apply_entity(record, image)
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise translate_integrity_violation(
            conflict,
            operation="attach_product_image",
            entity="product_image",
            identifier=str(image.id),
            conflict_detail=_conflict_detail(conflict),
            missing_detail=_MISSING_REFERENCE,
        ) from conflict
    return to_entity(record)


async def update(session: AsyncSession, image: ProductImageModel) -> ProductImageModel:
    """Persist changes to an existing image, scoped to its business."""
    result = await session.execute(
        select(ProductImageRecord)
        .where(ProductImageRecord.id == image.id)
        .where(ProductImageRecord.tenant_id == image.tenant_id)
    )
    stored = result.scalar_one_or_none()
    if stored is None:
        raise NotFoundError(
            operation="update_product_image",
            entity="product_image",
            identifier=str(image.id),
            detail="no image matched in this business",
        )
    apply_entity(stored, image)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise translate_integrity_violation(
            conflict,
            operation="update_product_image",
            entity="product_image",
            identifier=str(image.id),
            conflict_detail=_conflict_detail(conflict),
        ) from conflict
    return to_entity(stored)


async def get_by_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    image_id: UUID,
) -> ProductImageModel | None:
    """Return an image by identifier, scoped to the business that owns it."""
    result = await session.execute(
        select(ProductImageRecord)
        .where(ProductImageRecord.id == image_id)
        .where(ProductImageRecord.tenant_id == tenant_id)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def require_by_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    image_id: UUID,
) -> ProductImageModel:
    image = await get_by_id(session, tenant_id=tenant_id, image_id=image_id)
    if image is None:
        raise NotFoundError(
            operation="fetch_product_image",
            entity="product_image",
            identifier=str(image_id),
            detail="no image matched in this business",
        )
    return image


async def list_for_product(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    product_id: UUID,
    include_removed: bool = False,
) -> list[ProductImageModel]:
    """Return a product's gallery, in the order the business arranged it.

    The ordering is `(sort_order, id)`: sort order is not unique, so the identifier
    breaks ties and keeps the result stable across reads. A unique constraint on
    position would make swapping two images a transient conflict for no gain.
    """
    statement = (
        select(ProductImageRecord)
        .where(ProductImageRecord.tenant_id == tenant_id)
        .where(ProductImageRecord.product_id == product_id)
    )
    if not include_removed:
        statement = statement.where(ProductImageRecord.removed_at.is_(None))
    result = await session.execute(
        statement.order_by(ProductImageRecord.sort_order, ProductImageRecord.id)
    )
    return [to_entity(record) for record in result.scalars().all()]


async def count_for_product(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    product_id: UUID,
) -> int:
    """Return how many images the product currently shows."""
    result = await session.execute(
        select(func.count())
        .select_from(ProductImageRecord)
        .where(ProductImageRecord.tenant_id == tenant_id)
        .where(ProductImageRecord.product_id == product_id)
        .where(ProductImageRecord.removed_at.is_(None))
    )
    return int(result.scalar_one())


async def list_pending_reconciliation(
    session: AsyncSession,
    tenant_id: UUID,
) -> list[ProductImageModel]:
    """Return images whose stored object may still exist after a failed delete."""
    result = await session.execute(
        select(ProductImageRecord)
        .where(ProductImageRecord.tenant_id == tenant_id)
        .where(ProductImageRecord.reconciliation_reason.is_not(None))
        .order_by(ProductImageRecord.created_at, ProductImageRecord.id)
    )
    return [to_entity(record) for record in result.scalars().all()]


async def delete_row(session: AsyncSession, image: ProductImageModel) -> None:
    """Remove the row for an image whose object the provider has confirmed is gone."""
    result = await session.execute(
        select(ProductImageRecord)
        .where(ProductImageRecord.id == image.id)
        .where(ProductImageRecord.tenant_id == image.tenant_id)
    )
    stored = result.scalar_one_or_none()
    if stored is None:
        raise NotFoundError(
            operation="delete_product_image_row",
            entity="product_image",
            identifier=str(image.id),
            detail="no image matched in this business",
        )
    await session.delete(stored)
    await session.flush()
