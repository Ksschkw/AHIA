"""Tenant storage quota accounting.

The product operates on a zero-cost budget, so AHIA enforces its own storage
limits. A provider will accept any bytes it is sent; the only thing standing
between a runaway client and a bill is this service.

The protocol is two-phase, because an upload is not atomic with respect to the
database:

1. **reserve** - in a short transaction, lock the tenant's accounting row, check
   that the processed size fits under the quota, and claim it. No network call
   happens inside this transaction.
2. the caller performs the provider upload.
3. **commit** on success, converting the reservation into stored bytes, or
   **release** on failure, returning the claim.

Reserving before uploading and committing after is what makes the check
meaningful under concurrency: two devices uploading at the same moment cannot
both pass a check that reads the same remaining quota, because the second one
waits on the row lock and then sees the first one's claim.

A process that dies between reserve and commit leaves a reservation behind. That
is why `release_stale_reservations` exists: reconciliation is an explicit
operation with a stated threshold, not a silent assumption that nothing crashed.
"""

# Audit exemption: quota accounting is bookkeeping derived from the product-image use case,
# which writes its own event. Recording both would put two entries in the trail for one
# upload, one of them about a byte counter.

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ahia.core.database import UnitOfWork
from ahia.core.errors import DomainError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.tenant_context import TenantContext
from ahia.crud import tenant_storage_usage_crud
from ahia.models.entities.tenant_storage_usage_model import TenantStorageUsage

_STORAGE_QUOTA_LOGGER_NAME: Final[str] = "ahia.services.storage_quota"

#: How long a reservation may stay unresolved before reconciliation reclaims it.
#: Long enough to outlast a slow provider call, short enough that a crash does
#: not lock a tenant out of uploading for a day.
DEFAULT_RESERVATION_TIMEOUT: Final[timedelta] = timedelta(minutes=15)

#: Permission required to change a tenant's storage accounting outside the
#: normal upload path. Reconciliation is an administrative action.
RECONCILE_PERMISSION: Final[str] = "storefront.manage"


@dataclass(frozen=True, slots=True)
class StorageReservation:
    """A claim on a tenant's storage, held across the provider call."""

    tenant_id: UUID
    reserved_bytes: int
    quota_bytes: int
    remaining_bytes: int


class StorageQuotaService:
    """Reserves, commits and releases tenant storage capacity.

    Constructed in the composition root with a unit-of-work factory and the
    configured quota. It has no database dependency of its own: the session
    arrives through the unit of work, exactly as it does for any other service.
    """

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        quota_bytes: int,
        logger: StructuredLogger | None = None,
    ) -> None:
        if quota_bytes <= 0:
            raise DomainError(
                operation="configure_storage_quota",
                entity="tenant_storage_usage",
                detail="the tenant quota must be a positive number of bytes",
            )
        self._unit_of_work_factory = unit_of_work_factory
        self._quota_bytes = quota_bytes
        self._logger = (logger or get_logger(_STORAGE_QUOTA_LOGGER_NAME)).bind(
            component="storage_quota"
        )

    @property
    def quota_bytes(self) -> int:
        return self._quota_bytes

    async def reserve(
        self,
        tenant_context: TenantContext,
        *,
        incoming_bytes: int,
        operation: str = "attach_product_image",
    ) -> StorageReservation:
        """Claim capacity for an upload, or refuse it.

        The check and the claim happen inside one transaction under a row lock,
        so a refusal is a decision made against committed state rather than
        against a value that another request is about to change.
        """
        if incoming_bytes <= 0:
            raise DomainError(
                operation=operation,
                entity="tenant_storage_usage",
                detail="a reservation must be for a positive number of bytes",
            )

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session: AsyncSession = unit_of_work.session_handle
            usage = await tenant_storage_usage_crud.lock_for_tenant(
                session, tenant_context.tenant_id
            )
            usage.require_capacity(incoming_bytes, quota_bytes=self._quota_bytes)
            updated = await tenant_storage_usage_crud.save(
                session, usage.with_reservation(incoming_bytes, at=datetime.now(UTC))
            )
            await unit_of_work.commit()

        self._logger.info(
            "storage_reserved",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            operation=operation,
            incoming_bytes=incoming_bytes,
            used_bytes=updated.used_bytes,
            reserved_bytes=updated.reserved_bytes,
        )
        return StorageReservation(
            tenant_id=tenant_context.tenant_id,
            reserved_bytes=incoming_bytes,
            quota_bytes=self._quota_bytes,
            remaining_bytes=updated.remaining_bytes(self._quota_bytes),
        )

    async def commit_reservation(
        self,
        reservation: StorageReservation,
        *,
        operation: str = "attach_product_image",
    ) -> TenantStorageUsage:
        """Convert a reservation into stored bytes after a successful upload."""
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session: AsyncSession = unit_of_work.session_handle
            usage = await tenant_storage_usage_crud.lock_for_tenant(session, reservation.tenant_id)
            updated = await tenant_storage_usage_crud.save(
                session, usage.with_commit(reservation.reserved_bytes, at=datetime.now(UTC))
            )
            await unit_of_work.commit()

        self._logger.info(
            "storage_committed",
            tenant_id=str(reservation.tenant_id),
            operation=operation,
            committed_bytes=reservation.reserved_bytes,
            used_bytes=updated.used_bytes,
        )
        return updated

    async def release_reservation(
        self,
        reservation: StorageReservation,
        *,
        reason: str,
        operation: str = "attach_product_image",
    ) -> TenantStorageUsage:
        """Return a claim after a failed upload.

        Called on every failure path. A reservation that is never released is a
        quota the tenant paid for and cannot use.
        """
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session: AsyncSession = unit_of_work.session_handle
            usage = await tenant_storage_usage_crud.lock_for_tenant(session, reservation.tenant_id)
            updated = await tenant_storage_usage_crud.save(
                session, usage.with_release(reservation.reserved_bytes, at=datetime.now(UTC))
            )
            await unit_of_work.commit()

        self._logger.warning(
            "storage_reservation_released",
            tenant_id=str(reservation.tenant_id),
            operation=operation,
            released_bytes=reservation.reserved_bytes,
            reason=reason,
        )
        return updated

    async def record_deletion(
        self,
        tenant_context: TenantContext,
        *,
        removed_bytes: int,
        operation: str = "delete_product_image",
    ) -> TenantStorageUsage:
        """Return bytes to the tenant after an object is deleted."""
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session: AsyncSession = unit_of_work.session_handle
            usage = await tenant_storage_usage_crud.lock_for_tenant(
                session, tenant_context.tenant_id
            )
            updated = await tenant_storage_usage_crud.save(
                session, usage.with_deletion(removed_bytes, at=datetime.now(UTC))
            )
            await unit_of_work.commit()

        self._logger.info(
            "storage_released_after_deletion",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            operation=operation,
            removed_bytes=removed_bytes,
            used_bytes=updated.used_bytes,
        )
        return updated

    async def get_usage(self, tenant_context: TenantContext) -> TenantStorageUsage:
        """Return the tenant's accounting, creating a zero row when absent."""
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session: AsyncSession = unit_of_work.session_handle
            usage = await tenant_storage_usage_crud.lock_for_tenant(
                session, tenant_context.tenant_id
            )
            await unit_of_work.commit()
        return usage

    async def release_stale_reservations(
        self,
        tenant_context: TenantContext,
        *,
        older_than: timedelta = DEFAULT_RESERVATION_TIMEOUT,
    ) -> int:
        """Release reservations left behind by a crashed or abandoned upload.

        Requires an administrative permission, because zeroing a reservation that
        a healthy upload is still using would let that upload exceed the quota.
        The threshold is a parameter rather than a constant so an operator can
        reason about it in one place.
        """
        tenant_context.require_permission(
            RECONCILE_PERMISSION,
            operation="release_stale_storage_reservations",
            resource_type="tenant_storage_usage",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )

        cutoff = datetime.now(UTC) - older_than
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session: AsyncSession = unit_of_work.session_handle
            usage = await tenant_storage_usage_crud.lock_for_tenant(
                session, tenant_context.tenant_id
            )
            if usage.reserved_bytes == 0 or usage.updated_at > cutoff:
                await unit_of_work.commit()
                return 0
            released = usage.reserved_bytes
            await tenant_storage_usage_crud.save(
                session, usage.with_release(released, at=datetime.now(UTC))
            )
            await unit_of_work.commit()

        self._logger.warning(
            "stale_storage_reservations_released",
            tenant_id=str(tenant_context.tenant_id),
            released_bytes=released,
            older_than_seconds=int(older_than.total_seconds()),
        )
        return released

    async def reconcile(
        self,
        tenant_context: TenantContext,
        *,
        stored_bytes_by_metadata: int,
    ) -> TenantStorageUsage:
        """Set the stored total to the value implied by the metadata rows.

        The accounting is a projection of the image rows. When they disagree -
        an interrupted upload, a manual deletion in the provider console, a bug -
        this is how the projection is corrected, deliberately and with a log
        record, rather than by drifting silently.
        """
        tenant_context.require_permission(
            RECONCILE_PERMISSION,
            operation="reconcile_storage_usage",
            resource_type="tenant_storage_usage",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session: AsyncSession = unit_of_work.session_handle
            usage = await tenant_storage_usage_crud.lock_for_tenant(
                session, tenant_context.tenant_id
            )
            corrected = TenantStorageUsage(
                tenant_id=usage.tenant_id,
                used_bytes=max(0, stored_bytes_by_metadata),
                reserved_bytes=usage.reserved_bytes,
                version=usage.version + 1,
                updated_at=usage.updated_at,
            )
            await tenant_storage_usage_crud.save(session, corrected)
            await unit_of_work.commit()

        self._logger.warning(
            "storage_usage_reconciled",
            tenant_id=str(tenant_context.tenant_id),
            previous_used_bytes=usage.used_bytes,
            reconciled_used_bytes=corrected.used_bytes,
        )
        return corrected

    async def count_unresolved_reservation_age_seconds(
        self,
        session: AsyncSession,
        tenant_id: UUID,
    ) -> float | None:
        """Return the age of the current reservation in seconds, or None.

        A read-only diagnostic used by operations tooling and by the
        reconciliation test. It takes a session directly because it is a query,
        not a use case, and it changes nothing.
        """
        usage = await tenant_storage_usage_crud.get_for_tenant(session, tenant_id)
        if usage is None or usage.reserved_bytes == 0:
            return None
        return (datetime.now(UTC) - usage.updated_at).total_seconds()
