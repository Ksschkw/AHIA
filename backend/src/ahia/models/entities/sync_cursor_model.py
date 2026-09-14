"""How far a device has read the change feed.

A cursor is one row per device, holding the sequence of the last change that device applied.
The client asks for everything after it, applies what comes back, and the cursor advances. That
is the whole protocol: there is no acknowledgement per change, because a device that applied a
change and died before acknowledging it will simply apply it again - the client's own writes are
idempotent by operation identifier, and a read is repeatable.

**Per device, not per business and not per user.** Two phones belonging to the same person are
two positions in the feed; a cursor shared between them would let the second phone skip changes
the first had already seen, and the person would see a stale catalogue on one phone and not the
other. The specification says per device, and the reason is that staleness.

**The cursor only moves forward.** `advanced_to` refuses to lower a sequence, because a client
that asks to move backwards is either confused or replaying an old request, and silently
rewinding would make the device re-apply changes it has already applied - which, for a sales
device, is the expensive kind of mistake.

**A device that has never synced has no row, and that is not an error.** It reads from zero: the
feed's first change is sequence one, so a cursor of zero means "everything", which is exactly
what a new device should receive. Creating the row on first read rather than on registration
keeps the table as small as the number of devices that actually synchronize.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError

#: What a device that has never synchronized has seen.
FIRST_SEQUENCE: Final[int] = 0


@dataclass(frozen=True, slots=True)
class SyncCursorModel:
    """How far one device has read."""

    id: UUID
    tenant_id: UUID
    device_id: UUID
    last_server_sequence: int
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.last_server_sequence < FIRST_SEQUENCE:
            raise EntityInvariantError(
                operation="build_sync_cursor",
                entity="sync_cursor",
                identifier=str(self.id),
                detail=(
                    f"last_server_sequence cannot be negative, not {self.last_server_sequence}"
                ),
            )
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise EntityInvariantError(
                operation="build_sync_cursor",
                entity="sync_cursor",
                identifier=str(self.id),
                detail="updated_at is a naive datetime; timestamps must carry a timezone",
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def starting_at(
        cls,
        *,
        cursor_id: UUID,
        tenant_id: UUID,
        device_id: UUID,
        now: datetime,
        last_server_sequence: int = FIRST_SEQUENCE,
    ) -> SyncCursorModel:
        return cls(
            id=cursor_id,
            tenant_id=tenant_id,
            device_id=device_id,
            last_server_sequence=last_server_sequence,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def advanced_to(self, *, sequence: int, at: datetime) -> SyncCursorModel:
        """Return the cursor moved to the sequence the client reported applying.

        Idempotent and monotonic: a lower sequence is refused, because moving a cursor backwards
        makes a device apply changes it has already applied.
        """
        if sequence < self.last_server_sequence:
            raise EntityInvariantError(
                operation="advance_sync_cursor",
                entity="sync_cursor",
                identifier=str(self.id),
                detail=(
                    f"a cursor cannot move backwards: it is at {self.last_server_sequence} and "
                    f"was asked to move to {sequence}"
                ),
            )
        if sequence == self.last_server_sequence:
            return self
        return replace(self, last_server_sequence=sequence, updated_at=at)

    def describe_for_audit(self) -> dict[str, str]:
        """Return the identifiers a log line needs."""
        return {
            "sync_cursor_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "device_id": str(self.device_id),
            "last_server_sequence": str(self.last_server_sequence),
        }
