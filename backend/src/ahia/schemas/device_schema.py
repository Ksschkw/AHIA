"""Transport contracts for devices.

The identifier is opaque to the server: the client generates it once per
installation and presents it on every launch. Nothing here interprets it, and the
platform is a closed set so an unexpected value is a 422 rather than a new
category of client appearing in an audit record.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from ahia.models.entities.device_model import KNOWN_PLATFORMS, DeviceModel

DeviceIdentifier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=8, max_length=128)
]
DevicePlatform = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True)]
DeviceName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
AppVersion = Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)]


class DeviceRegisterSchema(BaseModel):
    """A client presenting itself.

    The same request registers a new installation and renews a known one: a client
    cannot tell its first launch from its hundredth, and it should not have to.
    """

    model_config = ConfigDict(extra="forbid")

    device_identifier: DeviceIdentifier
    platform: DevicePlatform
    device_name: DeviceName | None = None
    app_version: AppVersion | None = None

    @field_validator("platform")
    @classmethod
    def _check_platform(cls, value: str) -> str:
        if value not in KNOWN_PLATFORMS:
            raise ValueError("unknown platform")
        return value


class DeviceResponseSchema(BaseModel):
    """One installation, as the business sees it.

    The identifier is not returned. An operator needs to know that a device is
    registered, who it belongs to and when it was last seen; the opaque string adds
    nothing and is not theirs to hold.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    user_id: UUID
    platform: str
    device_name: str | None
    app_version: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    revoked_at: datetime | None
    is_revoked: bool

    @classmethod
    def from_entity(cls, device: DeviceModel) -> DeviceResponseSchema:
        return cls(
            id=device.id,
            user_id=device.user_id,
            platform=device.platform,
            device_name=device.device_name,
            app_version=device.app_version,
            first_seen_at=device.created_at,
            last_seen_at=device.last_seen_at,
            revoked_at=device.revoked_at,
            is_revoked=device.is_revoked(),
        )


class DeviceRevocationResponseSchema(BaseModel):
    """The result of revoking a device.

    The session count is reported because it is the part that matters: a revocation
    that ended no sessions is worth noticing, since it means the phone had none.
    """

    model_config = ConfigDict(extra="forbid")

    device: DeviceResponseSchema
    sessions_ended: int
