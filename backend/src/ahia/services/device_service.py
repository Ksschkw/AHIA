"""Device use cases: registering an installation, listing them, revoking one.

Registering is the caller's own act and needs no permission: a person's phone is
their phone. Listing the business's devices needs `devices.read`, and revoking
somebody else's needs `devices.revoke`. Revoking your own needs nothing beyond
being authenticated, because "sign this phone out" must always be available.

Revocation is the operation with consequences, so it does three things in one
transaction: marks the device revoked, revokes every session bound to it, and
leaves a security log line. Marking it revoked without ending its sessions would
stop the phone registering itself again while its refresh tokens kept working,
which is the opposite of what somebody reporting a lost phone needs.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final, Protocol
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.errors import ConflictError, DomainError, NotFoundError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions.device_permissions import DEVICES_READ, DEVICES_REVOKE
from ahia.core.tenant_context import TenantContext
from ahia.crud import device_crud, session_crud
from ahia.models.entities.device_model import DeviceModel

_DEVICE_LOGGER_NAME: Final[str] = "ahia.services.device"

#: Recorded against the sessions a device revocation ends.
REASON_DEVICE_REVOKED: Final[str] = "device_revoked"


class PrincipalLike(Protocol):
    """The part of a principal this service needs."""

    @property
    def user_id(self) -> UUID: ...


class DeviceService:
    """Device use cases."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._logger = (logger or get_logger(_DEVICE_LOGGER_NAME)).bind(
            component="device_service", layer="service"
        )

    # ------------------------------------------------------------------
    # Registering and heartbeats
    # ------------------------------------------------------------------

    async def register_or_touch_device(
        self,
        tenant_context: TenantContext,
        *,
        device_identifier: str,
        platform: str,
        device_name: str | None = None,
        app_version: str | None = None,
    ) -> DeviceModel:
        """Register an installation, or update one that is already known.

        One endpoint for both, because a client cannot tell the difference between
        its first launch and its hundredth: it presents the same identity, and the
        service decides whether that identity is new, known, or refused.

        An installation belongs to the person who registered it until it is revoked.
        A second person presenting the same identifier is claiming somebody else's
        device, which is a conflict rather than a new registration.
        """
        now = datetime.now(UTC)

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            existing = await device_crud.get_by_identifier(
                session,
                tenant_id=tenant_context.tenant_id,
                device_identifier=device_identifier,
            )

            if existing is not None:
                stored = await self._touch_existing(
                    session,
                    existing=existing,
                    tenant_context=tenant_context,
                    app_version=app_version,
                    now=now,
                )
                await unit_of_work.commit()
                return stored

            device = await device_crud.create(
                session,
                DeviceModel.register(
                    device_id=uuid4(),
                    tenant_id=tenant_context.tenant_id,
                    user_id=tenant_context.user_id,
                    device_identifier=device_identifier,
                    platform=platform,
                    device_name=device_name,
                    app_version=app_version,
                    now=now,
                ),
            )
            await unit_of_work.commit()

        self._logger.info(
            "device_registered",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            device_id=str(device.id),
            platform=device.platform,
        )
        return device

    async def _touch_existing(
        self,
        session: object,
        *,
        existing: DeviceModel,
        tenant_context: TenantContext,
        app_version: str | None,
        now: datetime,
    ) -> DeviceModel:
        """Update a known installation, or refuse the claim."""
        if not existing.belongs_to(
            tenant_id=tenant_context.tenant_id, user_id=tenant_context.user_id
        ):
            self._logger.warning(
                "device_claim_refused",
                tenant_id=str(tenant_context.tenant_id),
                actor_id=str(tenant_context.user_id),
                device_id=str(existing.id),
                owner_user_id=str(existing.user_id),
                security_event="device_claimed_by_another_user",
            )
            raise ConflictError(
                operation="register_device",
                entity="device",
                identifier=str(existing.id),
                detail="this installation is registered to another member of the business",
            )

        if existing.is_revoked():
            # A revoked device is the same installation, so re-registering it would
            # undo the decision somebody made when they reported the phone lost.
            self._logger.warning(
                "revoked_device_registration_refused",
                tenant_id=str(tenant_context.tenant_id),
                actor_id=str(tenant_context.user_id),
                device_id=str(existing.id),
                security_event="revoked_device_rejected",
            )
            raise DomainError(
                operation="register_device",
                entity="device",
                identifier=str(existing.id),
                detail="this installation was revoked and cannot register again",
            )

        return await device_crud.update(
            session,  # type: ignore[arg-type]
            existing.seen(at=now, app_version=app_version),
        )

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    async def list_devices(self, tenant_context: TenantContext) -> list[DeviceModel]:
        """Return the devices that have accessed this business, newest first."""
        tenant_context.require_permission(
            DEVICES_READ,
            operation="list_devices",
            resource_type="device",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await device_crud.list_for_tenant(
                unit_of_work.session_handle, tenant_context.tenant_id
            )

    async def list_own_devices(self, tenant_context: TenantContext) -> list[DeviceModel]:
        """Return the caller's own installations, without needing a permission."""
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await device_crud.list_for_user(
                unit_of_work.session_handle,
                tenant_id=tenant_context.tenant_id,
                user_id=tenant_context.user_id,
            )

    # ------------------------------------------------------------------
    # Revocation
    # ------------------------------------------------------------------

    async def revoke_device(
        self, tenant_context: TenantContext, *, device_id: UUID
    ) -> tuple[DeviceModel, int]:
        """Revoke a device and end the sessions bound to it.

        Revoking your own device needs no permission: "sign this phone out" must
        always be available, including from the phone itself. Revoking somebody
        else's needs `devices.revoke`.
        """
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            device = await self._require_device_in_tenant(
                session, tenant_context=tenant_context, device_id=device_id
            )

            if device.user_id != tenant_context.user_id:
                tenant_context.require_permission(
                    DEVICES_REVOKE,
                    operation="revoke_device",
                    resource_type="device",
                    resource_id=str(device_id),
                    logger=self._logger,
                )

            now = datetime.now(UTC)
            revoked = await device_crud.update(session, device.revoke(at=now))
            sessions_ended = await session_crud.revoke_all_for_device(
                session, device_id=device_id, at=now, reason=REASON_DEVICE_REVOKED
            )
            await unit_of_work.commit()

        self._logger.warning(
            "device_revoked",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            device_id=str(device_id),
            device_owner_user_id=str(device.user_id),
            sessions_ended=sessions_ended,
            security_event="device_revoked",
        )
        return revoked, sessions_ended

    async def _require_device_in_tenant(
        self,
        session: object,
        *,
        tenant_context: TenantContext,
        device_id: UUID,
    ) -> DeviceModel:
        """Load a device, refusing one that belongs to another business.

        The tenant comes from the authorized context, never from the request, so a
        device identifier alone cannot reach across tenants. A mismatch is answered
        exactly as a missing device would be.
        """
        device = await device_crud.get_by_id(session, device_id)  # type: ignore[arg-type]
        if device is None or device.tenant_id != tenant_context.tenant_id:
            self._logger.warning(
                "device_access_denied",
                reason="device_not_in_tenant",
                tenant_id=str(tenant_context.tenant_id),
                device_id=str(device_id),
                security_event="tenant_isolation",
            )
            raise NotFoundError(
                operation="fetch_device",
                entity="device",
                identifier=str(device_id),
                detail="no device matched in this business",
            )
        return device
