"""Persistence for a business's public shop.

One table, one entity, one file. Three properties are worth stating.

One storefront per business, and the database says so
    `UNIQUE(tenant_id)`. A second row would be a second answer to "is this shop open", and the
    first question a customer's link asks is exactly that. The uniqueness makes the second answer
    impossible rather than unlikely.

The public address is resolved through the tenant, not through this table
    `/shop/{tenant_slug}` is the address a business gives out, and the slug lives on `tenants`
    where it is globally unique. This table holds whether the shop answers, so the reader joins the
    two - and there is no second slug that could disagree with the first.

A shop is found by its business, never by an identifier
    There is no `get_by_id` used by a public reader: a customer arrives with a slug, and an internal
    identifier in a public URL is the enumeration the specification's sharing section forbids. The
    service resolves the tenant first, then this row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.models.entities.storefront_model import (
    MAXIMUM_CONTACT_PHONE_LENGTH,
    MAXIMUM_HEADLINE_LENGTH,
    StorefrontModel,
)

_TABLE_NAME: Final[str] = "storefronts"


class StorefrontRecord(Base):
    """The persistence representation of one business's shop."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    # One shop per business. The constraint is declared by name in `__table_args__` rather than
    # as `unique=True` on the column: the first version had both, and autogenerate emitted two
    # unique constraints on the same column.
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    headline: Mapped[str | None] = mapped_column(String(MAXIMUM_HEADLINE_LENGTH), nullable=True)
    # TEXT rather than a bounded VARCHAR: the entity is where the bound lives, and a second,
    # weaker bound on the column would only be a second answer.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(
        String(MAXIMUM_CONTACT_PHONE_LENGTH), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unpublished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("tenant_id", name="uq_storefronts_tenant_id"),)


def to_entity(record: StorefrontRecord) -> StorefrontModel:
    return StorefrontModel(
        id=record.id,
        tenant_id=record.tenant_id,
        is_published=record.is_published,
        created_at=record.created_at,
        updated_at=record.updated_at,
        headline=record.headline,
        description=record.description,
        contact_phone=record.contact_phone,
        published_at=record.published_at,
        unpublished_at=record.unpublished_at,
    )


def apply_entity(record: StorefrontRecord, entity: StorefrontModel) -> None:
    record.tenant_id = entity.tenant_id
    record.is_published = entity.is_published
    record.headline = entity.headline
    record.description = entity.description
    record.contact_phone = entity.contact_phone
    record.published_at = entity.published_at
    record.unpublished_at = entity.unpublished_at
    record.created_at = entity.created_at
    record.updated_at = entity.updated_at


async def create(session: AsyncSession, storefront: StorefrontModel) -> StorefrontModel:
    """Insert the business's shop."""
    record = StorefrontRecord(id=storefront.id)
    apply_entity(record, storefront)
    session.add(record)
    await session.flush()
    return to_entity(record)


async def get_for_tenant(session: AsyncSession, tenant_id: UUID) -> StorefrontModel | None:
    """Return a business's shop, if it has one."""
    result = await session.execute(
        select(StorefrontRecord).where(StorefrontRecord.tenant_id == tenant_id)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def update(session: AsyncSession, storefront: StorefrontModel) -> StorefrontModel:
    """Persist a change to a business's shop."""
    result = await session.execute(
        select(StorefrontRecord).where(StorefrontRecord.tenant_id == storefront.tenant_id)
    )
    stored = result.scalar_one_or_none()
    if stored is None:
        return await create(session, storefront)
    apply_entity(stored, storefront)
    await session.flush()
    return to_entity(stored)


async def is_published_for_tenant(session: AsyncSession, tenant_id: UUID) -> bool:
    """Return True when this business's shop answers at its public address.

    A boolean read rather than a row read, because the public path asks only this question and a
    business that has never opened a shop must not need a row to exist for the answer to be no.
    """
    result = await session.execute(
        select(StorefrontRecord.is_published).where(StorefrontRecord.tenant_id == tenant_id)
    )
    return bool(result.scalar_one_or_none())
