"""A report that was written out as a file: where it is, and what it is of.

The report itself lives in the object store and the record of it lives here, which is the split the
specification asks for: PostgreSQL holds metadata, R2 holds bytes. What this row knows is which
report, over which period, produced which object - and that is enough for a support conversation,
for a reconciliation after a provider outage, and for a share link to point at something.

**The artifact is immutable, and so is the row.** A report is what the numbers were when somebody
asked; re-running it produces a second export with its own key and its own timestamp, because the
two are different answers to the same question asked twice. There is no update path: a key that
changed under a share link already sent to somebody would be a link that opens a different document
from the one it was sent with.

**A failed export is recorded, not hidden.** When the upload does not complete, the row says so and
carries the reason; the key and the checksum are still recorded, so an operator can see what was
attempted and reconcile afterwards. A missing row would leave a business asking why nothing arrived
with no way to tell a failed upload from a request that was never made.

**The period is optional and travels with the artifact.** A stock report is about a moment rather
than a range; a sales report is about both ends of one. When a period is recorded, both ends are, so
a reader never has to reconstruct half of it.

**The key is built by the service and checked against the tenant prefix there.** A key suggested
by a client would let a caller name a path, so the service builds it from server-side identifiers,
and the storage port refuses any key outside the business's prefix before a byte is stored. The
prefix rule does not live here because an entity may import `core.errors` and nothing else from
`core`: the shape of the key - present and bounded - is what this entity checks, and the rule about
whose prefix it belongs under is enforced where the object is stored.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError

MAXIMUM_STORAGE_PROVIDER_LENGTH: Final[int] = 32
MAXIMUM_STORAGE_KEY_LENGTH: Final[int] = 512
MAXIMUM_FAILURE_REASON_LENGTH: Final[int] = 500
SHA256_HEX_LENGTH: Final[int] = 64
HEXADECIMAL_CHARACTERS: Final[str] = "0123456789abcdef"


class ReportType(StrEnum):
    """Which report an artifact holds.

    A closed set: an export of a report this version does not have is a file nobody can read, and
    the
    name is what a client uses to decide how to render it.
    """

    DAILY_SALES = "DAILY_SALES"
    PRODUCT_PERFORMANCE = "PRODUCT_PERFORMANCE"
    LOW_STOCK = "LOW_STOCK"


class ExportStatus(StrEnum):
    """Whether the bytes are where the record says they are."""

    READY = "READY"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ReportExportModel:
    """One written-out report."""

    id: UUID
    tenant_id: UUID
    report_type: ReportType
    storage_provider: str
    storage_key: str
    size_bytes: int
    checksum_sha256: str
    row_count: int
    status: ExportStatus
    created_at: datetime
    created_by_user_id: UUID | None = None
    period_since: datetime | None = None
    period_until: datetime | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.created_at, field_name="created_at", export_id=self.id)
        if not isinstance(self.report_type, ReportType):
            raise EntityInvariantError(
                operation="record_report_export",
                entity="report_export",
                identifier=str(self.id),
                detail=f"report_type must be a ReportType, not {type(self.report_type).__name__}",
            )
        if not isinstance(self.status, ExportStatus):
            raise EntityInvariantError(
                operation="record_report_export",
                entity="report_export",
                identifier=str(self.id),
                detail=f"status must be an ExportStatus, not {type(self.status).__name__}",
            )

        self._check_period()
        self._check_object()
        self._check_outcome()

    def _check_period(self) -> None:
        if (self.period_since is None) != (self.period_until is None):
            raise EntityInvariantError(
                operation="record_report_export",
                entity="report_export",
                identifier=str(self.id),
                detail=(
                    "a period is both ends or neither; half a period is a range a reader has to "
                    "reconstruct"
                ),
            )
        if self.period_since is None or self.period_until is None:
            return
        _require_aware(self.period_since, field_name="period_since", export_id=self.id)
        _require_aware(self.period_until, field_name="period_until", export_id=self.id)
        if self.period_until <= self.period_since:
            raise EntityInvariantError(
                operation="record_report_export",
                entity="report_export",
                identifier=str(self.id),
                detail="the period ends before it starts",
            )

    def _check_object(self) -> None:
        provider = self.storage_provider.strip()
        if not provider or len(provider) > MAXIMUM_STORAGE_PROVIDER_LENGTH:
            raise EntityInvariantError(
                operation="record_report_export",
                entity="report_export",
                identifier=str(self.id),
                detail="storage_provider is required and bounded",
            )
        key = self.storage_key.strip()
        if not key or len(key) > MAXIMUM_STORAGE_KEY_LENGTH:
            raise EntityInvariantError(
                operation="record_report_export",
                entity="report_export",
                identifier=str(self.id),
                detail="storage_key is required and bounded",
            )
        if len(self.checksum_sha256) != SHA256_HEX_LENGTH or any(
            character not in HEXADECIMAL_CHARACTERS for character in self.checksum_sha256
        ):
            raise EntityInvariantError(
                operation="record_report_export",
                entity="report_export",
                identifier=str(self.id),
                detail="checksum_sha256 must be the lowercase hex digest of the object",
            )
        if self.size_bytes < 0:
            raise EntityInvariantError(
                operation="record_report_export",
                entity="report_export",
                identifier=str(self.id),
                detail="size_bytes cannot be negative",
            )
        if self.row_count < 0:
            raise EntityInvariantError(
                operation="record_report_export",
                entity="report_export",
                identifier=str(self.id),
                detail="row_count cannot be negative",
            )

    def _check_outcome(self) -> None:
        if self.status is ExportStatus.READY:
            if self.size_bytes <= 0:
                raise EntityInvariantError(
                    operation="record_report_export",
                    entity="report_export",
                    identifier=str(self.id),
                    detail="a ready export has bytes; an empty one is a failed one",
                )
            if self.failure_reason is not None:
                raise EntityInvariantError(
                    operation="record_report_export",
                    entity="report_export",
                    identifier=str(self.id),
                    detail="a ready export cannot carry a failure reason",
                )
            return
        if not (self.failure_reason or "").strip():
            raise EntityInvariantError(
                operation="record_report_export",
                entity="report_export",
                identifier=str(self.id),
                detail=(
                    "a failed export must record why; a bare failure leaves a business asking why "
                    "nothing arrived"
                ),
            )
        if len(self.failure_reason or "") > MAXIMUM_FAILURE_REASON_LENGTH:
            raise EntityInvariantError(
                operation="record_report_export",
                entity="report_export",
                identifier=str(self.id),
                detail=f"failure_reason exceeds {MAXIMUM_FAILURE_REASON_LENGTH} characters",
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def ready(
        cls,
        *,
        export_id: UUID,
        tenant_id: UUID,
        report_type: ReportType,
        storage_provider: str,
        storage_key: str,
        size_bytes: int,
        checksum_sha256: str,
        row_count: int,
        now: datetime,
        created_by_user_id: UUID | None = None,
        period_since: datetime | None = None,
        period_until: datetime | None = None,
    ) -> ReportExportModel:
        """Build the record of an export whose bytes are in the object store."""
        return cls(
            id=export_id,
            tenant_id=tenant_id,
            report_type=report_type,
            storage_provider=storage_provider.strip(),
            storage_key=storage_key.strip(),
            size_bytes=size_bytes,
            checksum_sha256=checksum_sha256.strip().lower(),
            row_count=row_count,
            status=ExportStatus.READY,
            created_at=now,
            created_by_user_id=created_by_user_id,
            period_since=period_since,
            period_until=period_until,
        )

    @classmethod
    def failed(
        cls,
        *,
        export_id: UUID,
        tenant_id: UUID,
        report_type: ReportType,
        storage_provider: str,
        storage_key: str,
        checksum_sha256: str,
        now: datetime,
        reason: str,
        created_by_user_id: UUID | None = None,
        period_since: datetime | None = None,
        period_until: datetime | None = None,
        row_count: int = 0,
    ) -> ReportExportModel:
        """Build the record of an export that did not complete.

        `row_count` is zero and `size_bytes` is zero because nothing was stored: recording the row
        that *would* have been stored would make a support conversation unable to tell what
        happened.
        """
        return cls(
            id=export_id,
            tenant_id=tenant_id,
            report_type=report_type,
            storage_provider=storage_provider.strip(),
            storage_key=storage_key.strip(),
            size_bytes=0,
            checksum_sha256=checksum_sha256.strip().lower(),
            row_count=row_count,
            status=ExportStatus.FAILED,
            created_at=now,
            created_by_user_id=created_by_user_id,
            period_since=period_since,
            period_until=period_until,
            failure_reason=reason.strip(),
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True when the bytes are where this record says they are."""
        return self.status is ExportStatus.READY

    def filename(self) -> str:
        """Return the name a browser should save the artifact under.

        Built from the report, the period and the identifier rather than from anything a caller
        supplied: a filename is rendered by a client, and a client-supplied one is a place to put
        whatever a client likes.
        """
        period = (
            f"{self.period_since.date()}_{self.period_until.date()}"
            if self.period_since is not None and self.period_until is not None
            else "snapshot"
        )
        return f"{self.report_type.value.lower()}_{period}_{self.id.hex[:8]}.csv"

    def describe_for_audit(self) -> dict[str, str]:
        """Return identifiers and the outcome, and never the storage key.

        The key is what an operator needs to find the object, and it is also a path in somebody
        else's system: the audit trail names the export, and support reads the key from this table
        when it is needed.
        """
        description = {
            "report_export_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "report_type": self.report_type.value,
            "status": self.status.value,
            "storage_provider": self.storage_provider,
            "row_count": str(self.row_count),
            "size_bytes": str(self.size_bytes),
        }
        if self.period_since is not None and self.period_until is not None:
            description["period"] = (
                f"{self.period_since.isoformat()}/{self.period_until.isoformat()}"
            )
        return description


def _require_aware(moment: datetime, *, field_name: str, export_id: UUID) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="record_report_export",
            entity="report_export",
            identifier=str(export_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
