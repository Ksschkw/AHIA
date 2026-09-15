"""Persistence for report exports.

One table, one entity, one file, and no update path. A report is what the numbers were when somebody
asked, and the artifact that answered is immutable - re-running it produces a second row with its
own
key and timestamp, because the two are different answers to the same question. Changing the key
under
a share link already sent would make the link open a different document from the one it was sent
with.

A failed export keeps its row
    The status, the reason, the key that was attempted and the checksum of what was built are all
    recorded, so an operator can tell a failed upload from a request that was never made. A test
    asserts the absence of any function that could delete a row.

Reads are by what a business asks
    "Which exports does this business have" is `(tenant_id, created_at)`; "what was exported of this
    report" is `(tenant_id, report_type, created_at)`. Both are indexed here rather than discovered
    from a slow screen later.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.models.entities.report_export_model import (
    MAXIMUM_FAILURE_REASON_LENGTH,
    MAXIMUM_STORAGE_KEY_LENGTH,
    MAXIMUM_STORAGE_PROVIDER_LENGTH,
    SHA256_HEX_LENGTH,
    ExportStatus,
    ReportExportModel,
    ReportType,
)

_TABLE_NAME: Final[str] = "report_exports"
_REPORT_TYPE_LENGTH: Final[int] = 32
_STATUS_LENGTH: Final[int] = 16


class ReportExportRecord(Base):
    """The persistence representation of one written-out report."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    report_type: Mapped[str] = mapped_column(String(_REPORT_TYPE_LENGTH), nullable=False)
    storage_provider: Mapped[str] = mapped_column(
        String(MAXIMUM_STORAGE_PROVIDER_LENGTH), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(MAXIMUM_STORAGE_KEY_LENGTH), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(SHA256_HEX_LENGTH), nullable=False)
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(_STATUS_LENGTH), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(
        String(MAXIMUM_FAILURE_REASON_LENGTH), nullable=True
    )
    # Copied rather than referenced: it is who asked for the export, and the answer to "who has this
    # file" must not change because a user row was edited later.
    created_by_user_id: Mapped[UUID | None] = mapped_column(nullable=True)
    period_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_report_exports_tenant_created", "tenant_id", "created_at"),
        Index("ix_report_exports_tenant_type_created", "tenant_id", "report_type", "created_at"),
    )


def to_entity(record: ReportExportRecord) -> ReportExportModel:
    return ReportExportModel(
        id=record.id,
        tenant_id=record.tenant_id,
        report_type=ReportType(record.report_type),
        storage_provider=record.storage_provider,
        storage_key=record.storage_key,
        size_bytes=record.size_bytes,
        checksum_sha256=record.checksum_sha256,
        row_count=record.row_count,
        status=ExportStatus(record.status),
        created_at=record.created_at,
        created_by_user_id=record.created_by_user_id,
        period_since=record.period_since,
        period_until=record.period_until,
        failure_reason=record.failure_reason,
    )


def apply_entity(record: ReportExportRecord, entity: ReportExportModel) -> None:
    record.tenant_id = entity.tenant_id
    record.report_type = entity.report_type.value
    record.storage_provider = entity.storage_provider
    record.storage_key = entity.storage_key
    record.size_bytes = entity.size_bytes
    record.checksum_sha256 = entity.checksum_sha256
    record.row_count = entity.row_count
    record.status = entity.status.value
    record.failure_reason = entity.failure_reason
    record.created_by_user_id = entity.created_by_user_id
    record.period_since = entity.period_since
    record.period_until = entity.period_until
    record.created_at = entity.created_at


async def create(session: AsyncSession, export: ReportExportModel) -> ReportExportModel:
    """Insert the record of a written-out report."""
    record = ReportExportRecord(id=export.id)
    apply_entity(record, export)
    session.add(record)
    await session.flush()
    return to_entity(record)


async def get_for_tenant(
    session: AsyncSession, *, tenant_id: UUID, export_id: UUID
) -> ReportExportModel | None:
    """Return one export, scoped to the business that asked for it."""
    result = await session.execute(
        select(ReportExportRecord)
        .where(ReportExportRecord.tenant_id == tenant_id)
        .where(ReportExportRecord.id == export_id)
    )
    record = result.scalar_one_or_none()
    return None if record is None else to_entity(record)


async def list_for_tenant(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    limit: int = 50,
) -> list[ReportExportModel]:
    """Return a business's exports, most recent first."""
    result = await session.execute(
        select(ReportExportRecord)
        .where(ReportExportRecord.tenant_id == tenant_id)
        .order_by(ReportExportRecord.created_at.desc(), ReportExportRecord.id.desc())
        .limit(limit)
    )
    return [to_entity(record) for record in result.scalars().all()]
