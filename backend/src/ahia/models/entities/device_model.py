"""The device entity: an identity for synchronization, audit and security.

A device never grants permission. This entity is the clearest expression of that
rule: it records which physical installation is talking to the service, and
nothing here decides what its holder may do. The person's membership does that, and
it follows them from phone to phone.

What a device is for, and therefore what it stores:

Synchronization
    Offline operations are attributed to a device, so a conflict can be traced to
    the installation it came from.

Audit
    "Which phone recorded this sale" is answerable after the fact, which is usually
    the first question when a trader disputes a figure.

Security
    A lost or stolen phone is revoked, which ends its sessions. That is the whole
    reason a device needs an identity of its own rather than being implied by the
    user.

Identity is a client-generated string, not a hardware identifier
    The identifier comes from the installation and is opaque here. Reading a real
    hardware identifier would be a privacy problem and would not survive a device
    reset anyway.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError

_MAXIMUM_IDENTIFIER_LENGTH: Final[int] = 128
_MAXIMUM_NAME_LENGTH: Final[int] = 100
_MAXIMUM_PLATFORM_LENGTH: Final[int] = 32
_MAXIMUM_APP_VERSION_LENGTH: Final[int] = 32

#: Platforms the product ships a client for. A closed set, because an unknown
#: platform means either a new client nobody registered here or a claim.
KNOWN_PLATFORMS: Final[frozenset[str]] = frozenset({"android", "ios", "web", "desktop"})


@dataclass(frozen=True, slots=True)
class DeviceModel:
    """One installation of a client, belonging to one person in one business."""

    id: UUID
    tenant_id: UUID
    user_id: UUID
    device_identifier: str
    platform: str
    created_at: datetime
    last_seen_at: datetime
    device_name: str | None = None
    app_version: str | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_aware(self.created_at, field_name="created_at", device_id=self.id)
        _require_aware(self.last_seen_at, field_name="last_seen_at", device_id=self.id)

        if self.last_seen_at < self.created_at:
            raise EntityInvariantError(
                operation="build_device",
                entity="device",
                identifier=str(self.id),
                detail="last_seen_at is earlier than created_at",
            )

        identifier = self.device_identifier.strip()
        if not identifier:
            raise EntityInvariantError(
                operation="build_device",
                entity="device",
                identifier=str(self.id),
                detail="device_identifier is empty",
            )
        if len(identifier) > _MAXIMUM_IDENTIFIER_LENGTH:
            raise EntityInvariantError(
                operation="build_device",
                entity="device",
                identifier=str(self.id),
                detail=f"device_identifier exceeds {_MAXIMUM_IDENTIFIER_LENGTH} characters",
            )

        if self.platform not in KNOWN_PLATFORMS:
            raise EntityInvariantError(
                operation="build_device",
                entity="device",
                identifier=str(self.id),
                detail=f"unknown platform: {self.platform}",
            )

        if self.device_name is not None and len(self.device_name) > _MAXIMUM_NAME_LENGTH:
            raise EntityInvariantError(
                operation="build_device",
                entity="device",
                identifier=str(self.id),
                detail=f"device_name exceeds {_MAXIMUM_NAME_LENGTH} characters",
            )
        if self.app_version is not None and len(self.app_version) > _MAXIMUM_APP_VERSION_LENGTH:
            raise EntityInvariantError(
                operation="build_device",
                entity="device",
                identifier=str(self.id),
                detail=f"app_version exceeds {_MAXIMUM_APP_VERSION_LENGTH} characters",
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def register(
        cls,
        *,
        device_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
        device_identifier: str,
        platform: str,
        now: datetime,
        device_name: str | None = None,
        app_version: str | None = None,
    ) -> DeviceModel:
        return cls(
            id=device_id,
            tenant_id=tenant_id,
            user_id=user_id,
            device_identifier=device_identifier.strip(),
            platform=platform,
            device_name=device_name.strip() if device_name else None,
            app_version=app_version.strip() if app_version else None,
            created_at=now,
            last_seen_at=now,
        )

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def grants_no_authority(self) -> bool:
        """Always true, and stated so a reader cannot mistake this entity's role.

        A device is an identity, not an authorization. It is written as a property
        rather than as a comment because a test asserts it, which is the difference
        between a documented rule and an enforced one.
        """
        return True

    def describe_for_audit(self) -> dict[str, str]:
        """Return identifiers and platform, never a hardware or network identifier."""
        description = {
            "device_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "platform": self.platform,
            "is_revoked": "true" if self.is_revoked() else "false",
        }
        if self.app_version is not None:
            description["app_version"] = self.app_version
        return description

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def seen(self, *, at: datetime, app_version: str | None = None) -> DeviceModel:
        """Return the device with its last-seen timestamp updated.

        This is the heartbeat: a client that opens the app reports in, which is what
        makes an abandoned installation distinguishable from an active one.
        """
        if self.is_revoked():
            raise EntityInvariantError(
                operation="record_device_heartbeat",
                entity="device",
                identifier=str(self.id),
                detail="a revoked device cannot report in",
            )
        return replace(
            self,
            last_seen_at=at,
            app_version=app_version.strip() if app_version else self.app_version,
        )

    def revoke(self, *, at: datetime) -> DeviceModel:
        """Return the device revoked.

        Revocation is terminal: a device that comes back is the same installation,
        and silently reinstating it would undo the decision somebody made when they
        reported the phone lost.
        """
        if self.is_revoked():
            return self
        return replace(self, revoked_at=at)

    def belongs_to(self, *, tenant_id: UUID, user_id: UUID) -> bool:
        """Return True when this device is the given person's in the given business."""
        return self.tenant_id == tenant_id and self.user_id == user_id


def _require_aware(moment: datetime, *, field_name: str, device_id: UUID) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="build_device",
            entity="device",
            identifier=str(device_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
