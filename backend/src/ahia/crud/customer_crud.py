"""Persistence for the customer entity.

One table, one entity, one file. Four properties are worth stating.

A sale references a customer as a pair, so the anchor exists
    `UNIQUE(id, tenant_id)`, which the sales table references as `(customer_id, tenant_id)`.
    It arrived with the table that needed it, exactly as the anchors in the catalogue did.

A phone number is not unique, and the index says why
    Two people in a household share a phone, and one person may be entered twice by
    mistake. The specification asks for duplicate *detection* by phone within a business,
    not prevention, so the column is indexed - a partial index, since most customers of a
    shop that only keeps names have no number at all - and the service reports a possible
    duplicate. A unique constraint would refuse to record a real customer, and the
    shopkeeper would write a fake phone number to get past it.

Every lookup takes the tenant
    A customer belongs to the business that recorded them. There is no function here that
    can read one without naming the tenant, which is the mechanical half of "customer data
    belongs to the tenant"; the service is the other half.

Updates can be checked against a version
    An offline client sends the version it was working from. `expected_version` compares it
    to the stored one inside the transaction and refuses the write when somebody else got
    there first, so two edits to the same customer's notes produce a conflict the client
    can resolve rather than a silent overwrite. Passing None means "last writer wins",
    which is what the specification allows for notes and what an online client wants.

Deactivation is not deletion
    There is no delete function. A customer is referenced by the sales that were made to
    them, and a vanished customer is a receipt nobody can explain.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.core.errors import ConflictError, NotFoundError
from ahia.crud.integrity_violations import translate_integrity_violation
from ahia.models.entities.customer_model import (
    MAXIMUM_EMAIL_LENGTH,
    MAXIMUM_NAME_LENGTH,
    CustomerModel,
)
from ahia.models.entities.phone_number import MAXIMUM_PHONE_LENGTH

_TABLE_NAME: Final[str] = "customers"


class CustomerRecord(Base):
    """The persistence representation of one customer."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(MAXIMUM_NAME_LENGTH), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(MAXIMUM_PHONE_LENGTH), nullable=True)
    email: Mapped[str | None] = mapped_column(String(MAXIMUM_EMAIL_LENGTH), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Incremented by every change, so an offline client can say which state it edited.
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # The cross-tenant anchor a sale references as `(customer_id, tenant_id)`, which is
        # what makes it impossible to record a sale against another business's customer. It
        # was added in the revision that created the sales table, which is the table that
        # needed it - the same rule the catalogue follows.
        UniqueConstraint("id", "tenant_id", name="uq_customers_id_tenant_id"),
        # The picker: a business's active customers, by the name a person reads.
        Index("ix_customers_tenant_active_name", "tenant_id", "is_active", "name"),
        # Duplicate detection by phone, only where a phone exists.
        Index(
            "ix_customers_tenant_phone",
            "tenant_id",
            "phone",
            postgresql_where=text("phone IS NOT NULL"),
        ),
        Index(
            "ix_customers_tenant_email",
            "tenant_id",
            "email",
            postgresql_where=text("email IS NOT NULL"),
        ),
    )


def to_entity(record: CustomerRecord) -> CustomerModel:
    return CustomerModel(
        id=record.id,
        tenant_id=record.tenant_id,
        name=record.name,
        created_at=record.created_at,
        updated_at=record.updated_at,
        phone=record.phone,
        email=record.email,
        address=record.address,
        notes=record.notes,
        marketing_opt_in=record.marketing_opt_in,
        is_active=record.is_active,
        version=record.version,
    )


def apply_entity(record: CustomerRecord, entity: CustomerModel) -> None:
    record.tenant_id = entity.tenant_id
    record.name = entity.name
    record.phone = entity.phone
    record.email = entity.email
    record.address = entity.address
    record.notes = entity.notes
    record.marketing_opt_in = entity.marketing_opt_in
    record.is_active = entity.is_active
    record.version = entity.version
    record.created_at = entity.created_at
    record.updated_at = entity.updated_at


async def create(session: AsyncSession, customer: CustomerModel) -> CustomerModel:
    """Insert a customer."""
    record = CustomerRecord(id=customer.id)
    apply_entity(record, customer)
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise translate_integrity_violation(
            conflict,
            operation="create_customer",
            entity="customer",
            identifier=str(customer.id),
            conflict_detail="this customer already exists",
            missing_detail="the business this customer belongs to does not exist",
        ) from conflict
    return to_entity(record)


async def get_by_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    customer_id: UUID,
) -> CustomerModel | None:
    """Return a customer by identifier, scoped to the business that recorded them."""
    result = await session.execute(
        select(CustomerRecord)
        .where(CustomerRecord.id == customer_id)
        .where(CustomerRecord.tenant_id == tenant_id)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def require_by_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    customer_id: UUID,
) -> CustomerModel:
    customer = await get_by_id(session, tenant_id=tenant_id, customer_id=customer_id)
    if customer is None:
        raise NotFoundError(
            operation="fetch_customer",
            entity="customer",
            identifier=str(customer_id),
            detail="no customer matched in this business",
        )
    return customer


async def list_for_tenant(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    include_inactive: bool = False,
) -> list[CustomerModel]:
    """Return a business's customers, by the name a person reads.

    Inactive customers are excluded by default: a picker at the counter should not offer
    somebody the business has stopped serving. Asking for them explicitly is how a record
    is found again to reactivate.
    """
    statement = select(CustomerRecord).where(CustomerRecord.tenant_id == tenant_id)
    if not include_inactive:
        statement = statement.where(CustomerRecord.is_active.is_(True))
    result = await session.execute(statement.order_by(CustomerRecord.name, CustomerRecord.id))
    return [to_entity(record) for record in result.scalars().all()]


async def find_by_phone(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    phone: str,
    excluding: UUID | None = None,
) -> list[CustomerModel]:
    """Return the customers in a business who already hold this phone number.

    A list rather than one record: a household shares a number, so a match is a hint that
    the person may already be recorded, not proof that they are.
    """
    statement = (
        select(CustomerRecord)
        .where(CustomerRecord.tenant_id == tenant_id)
        .where(CustomerRecord.phone == phone)
    )
    if excluding is not None:
        statement = statement.where(CustomerRecord.id != excluding)
    result = await session.execute(statement.order_by(CustomerRecord.created_at))
    return [to_entity(record) for record in result.scalars().all()]


async def update(
    session: AsyncSession,
    customer: CustomerModel,
    *,
    expected_version: int | None = None,
) -> CustomerModel:
    """Persist changes to an existing customer, scoped to its business.

    `expected_version` is what an offline client was working from. When it does not match
    the stored version, somebody else changed the record first and the write is refused:
    silently applying it would discard their edit, which is the one outcome a merge cannot
    repair because nobody knows what was lost.
    """
    result = await session.execute(
        select(CustomerRecord)
        .where(CustomerRecord.id == customer.id)
        .where(CustomerRecord.tenant_id == customer.tenant_id)
    )
    stored = result.scalar_one_or_none()
    if stored is None:
        raise NotFoundError(
            operation="update_customer",
            entity="customer",
            identifier=str(customer.id),
            detail="no customer matched in this business",
        )

    if expected_version is not None and stored.version != expected_version:
        raise ConflictError(
            operation="update_customer",
            entity="customer",
            identifier=str(customer.id),
            detail=(
                f"this customer was changed by somebody else: "
                f"expected version {expected_version}, stored version {stored.version}"
            ),
        )

    apply_entity(stored, customer)
    await session.flush()
    return to_entity(stored)


async def count_for_tenant(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    include_inactive: bool = True,
) -> int:
    """Return how many customers a business has recorded."""
    statement = (
        select(func.count())
        .select_from(CustomerRecord)
        .where(CustomerRecord.tenant_id == tenant_id)
    )
    if not include_inactive:
        statement = statement.where(CustomerRecord.is_active.is_(True))
    result = await session.execute(statement)
    return int(result.scalar_one())
