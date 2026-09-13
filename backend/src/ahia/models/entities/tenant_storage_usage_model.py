"""Tenant storage usage.

Storage is a metered resource with a ceiling the platform enforces itself. The
provider will happily accept bytes that cost money, so the limit lives here, not
in a provider dashboard.

The record separates bytes that are **used** from bytes that are **reserved**.
A reservation exists because an upload is not instantaneous: the bytes are
counted, quota is claimed, the provider call happens, and only then does the
usage become real. Without the reserved counter, two devices uploading at the
same moment would both read the same remaining quota, both decide they fit, and
both write, over-allocating the tenant by the sum of what they added.

The reservation is deliberately short-lived and must always be resolved: a
release on failure, or a commit on success. A process that dies between the two
leaves a reservation behind, which is why the service offers a reconciliation
path rather than pretending it cannot happen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ahia.core.errors import EntityInvariantError, StorageQuotaExceededError


@dataclass(frozen=True, slots=True)
class TenantStorageUsage:
    """One tenant's storage accounting."""

    tenant_id: UUID
    used_bytes: int
    reserved_bytes: int
    version: int
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.used_bytes < 0:
            raise EntityInvariantError(
                operation="build_tenant_storage_usage",
                entity="tenant_storage_usage",
                identifier=str(self.tenant_id),
                detail=f"used_bytes is negative: {self.used_bytes}",
            )
        if self.reserved_bytes < 0:
            raise EntityInvariantError(
                operation="build_tenant_storage_usage",
                entity="tenant_storage_usage",
                identifier=str(self.tenant_id),
                detail=f"reserved_bytes is negative: {self.reserved_bytes}",
            )

    @property
    def committed_bytes(self) -> int:
        """Return bytes that are actually stored."""
        return self.used_bytes

    @property
    def claimed_bytes(self) -> int:
        """Return bytes stored plus bytes promised to an in-flight upload."""
        return self.used_bytes + self.reserved_bytes

    def remaining_bytes(self, quota_bytes: int) -> int:
        """Return bytes still available under the quota.

        Never negative: a tenant already over quota, for example because the
        quota was lowered after the fact, reports zero available rather than a
        negative number that could invert a comparison.
        """
        return max(0, quota_bytes - self.claimed_bytes)

    def can_accept(self, incoming_bytes: int, *, quota_bytes: int) -> bool:
        """Return True when the incoming bytes fit under the quota."""
        if incoming_bytes < 0:
            return False
        return self.claimed_bytes + incoming_bytes <= quota_bytes

    def require_capacity(self, incoming_bytes: int, *, quota_bytes: int) -> None:
        """Raise when the incoming bytes do not fit.

        The numbers stay internal: the caller learns that the workspace is at its
        storage limit, which is actionable, and not the exact accounting, which
        is not.
        """
        if self.can_accept(incoming_bytes, quota_bytes=quota_bytes):
            return
        raise StorageQuotaExceededError(
            operation="reserve_storage",
            entity="tenant_storage_usage",
            identifier=str(self.tenant_id),
            detail=(
                f"used_bytes={self.used_bytes} reserved_bytes={self.reserved_bytes} "
                f"incoming_bytes={incoming_bytes} quota_bytes={quota_bytes}"
            ),
        )

    def with_reservation(self, incoming_bytes: int, *, at: datetime) -> TenantStorageUsage:
        """Return the record with a new reservation claimed."""
        if incoming_bytes < 0:
            raise EntityInvariantError(
                operation="reserve_storage",
                entity="tenant_storage_usage",
                identifier=str(self.tenant_id),
                detail="a reservation may not be negative",
            )
        return TenantStorageUsage(
            tenant_id=self.tenant_id,
            used_bytes=self.used_bytes,
            reserved_bytes=self.reserved_bytes + incoming_bytes,
            version=self.version + 1,
            updated_at=at,
        )

    def with_commit(self, incoming_bytes: int, *, at: datetime) -> TenantStorageUsage:
        """Return the record with a reservation converted into stored bytes."""
        if incoming_bytes > self.reserved_bytes:
            raise EntityInvariantError(
                operation="commit_storage_reservation",
                entity="tenant_storage_usage",
                identifier=str(self.tenant_id),
                detail=(
                    f"commit of {incoming_bytes} exceeds the reserved "
                    f"{self.reserved_bytes}; a commit without a reservation is a defect"
                ),
            )
        return TenantStorageUsage(
            tenant_id=self.tenant_id,
            used_bytes=self.used_bytes + incoming_bytes,
            reserved_bytes=self.reserved_bytes - incoming_bytes,
            version=self.version + 1,
            updated_at=at,
        )

    def with_release(self, incoming_bytes: int, *, at: datetime) -> TenantStorageUsage:
        """Return the record with a reservation released after a failure."""
        return TenantStorageUsage(
            tenant_id=self.tenant_id,
            used_bytes=self.used_bytes,
            reserved_bytes=max(0, self.reserved_bytes - incoming_bytes),
            version=self.version + 1,
            updated_at=at,
        )

    def with_deletion(self, removed_bytes: int, *, at: datetime) -> TenantStorageUsage:
        """Return the record with stored bytes removed from the total.

        A deletion that would drive the total below zero is a bookkeeping defect,
        so the total floors at zero and the discrepancy is caught by the
        reconciliation path rather than by a negative number propagating.
        """
        return TenantStorageUsage(
            tenant_id=self.tenant_id,
            used_bytes=max(0, self.used_bytes - max(0, removed_bytes)),
            reserved_bytes=self.reserved_bytes,
            version=self.version + 1,
            updated_at=at,
        )

    @classmethod
    def empty(cls, tenant_id: UUID, *, now: datetime) -> TenantStorageUsage:
        """Return the starting record for a tenant with no stored files."""
        return cls(
            tenant_id=tenant_id,
            used_bytes=0,
            reserved_bytes=0,
            version=0,
            updated_at=now,
        )
