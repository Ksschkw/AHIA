"""The record of an operation a device pushed, so it is applied exactly once.

A phone in a market loses signal between the moment it records a sale and the moment the server
answers. It retries. Without a record of what has already been applied, the business sells the
same bag of rice twice, and the second sale is not a duplicate the person can spot - it looks
like a busy morning. The operation identifier is what makes the retry safe, and this row is
where the answer lives.

**The row is written by the sync layer, and the operation itself is the use case's.** A pushed
sale goes through `SalesService.complete_sale`, which already refuses to complete the same
operation twice; this table records the envelope - which device sent it, which use case ran, what
came back - so the next arrival of the same identifier is answered from here without executing
anything. Two mechanisms for one guarantee sounds like one too many, and they answer different
questions: the use case's own uniqueness keeps the *business fact* from happening twice even
when it arrives through another route, and this row lets the sync endpoint answer a retry
without knowing which use case it was.

**The outcome is recorded for every answer.** `APPLIED` means the server did the work,
`REPLAYED` means it had already done it and is returning the same result, `CONFLICT` means the
operation was valid and the client's copy was stale, and `REJECTED` means the work was refused by
a permission or by validation. A device that keeps retrying a rejected operation must be able to
learn that retrying will not help; a device that hit a conflict must be able to learn what to
merge against.

**The payload is not stored.** What the client sent is in the client's queue; what matters here
is the outcome and the entity it produced. Storing the payload would copy customer names and
prices into a second table with its own retention, and the audit trail already records who did
what.

**Immutable.** An operation's outcome is a fact about a request that has already been answered.
There is no update path: a change would let a later arrival of the same identifier be answered
differently from the first, which is precisely the failure the row exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError

MAXIMUM_OPERATION_TYPE_LENGTH: Final[int] = 64
MAXIMUM_RESULT_LENGTH: Final[int] = 500
MAXIMUM_DETAIL_KEYS: Final[int] = 24
MAXIMUM_DETAIL_VALUE_LENGTH: Final[int] = 256

_LOWER_SNAKE_CASE: Final[str] = "abcdefghijklmnopqrstuvwxyz0123456789_"


class SyncOperationStatus(StrEnum):
    """What the server did with the operation."""

    APPLIED = "APPLIED"
    REPLAYED = "REPLAYED"
    #: The operation was valid and the server refused it because the client's copy was stale.
    #: Distinct from `REJECTED`, which means retrying will not help: a conflict is answered with
    #: the server's current version so the client can merge and try again.
    CONFLICT = "CONFLICT"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class SyncOperationModel:
    """One pushed operation, and what became of it."""

    id: UUID
    tenant_id: UUID
    operation_type: str
    status: SyncOperationStatus
    occurred_at: datetime
    actor_id: UUID | None = None
    device_id: UUID | None = None
    entity_type: str | None = None
    entity_id: UUID | None = None
    detail: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise EntityInvariantError(
                operation="record_sync_operation",
                entity="sync_operation",
                identifier=str(self.id),
                detail="occurred_at is a naive datetime; timestamps must carry a timezone",
            )
        if not isinstance(self.status, SyncOperationStatus):
            raise EntityInvariantError(
                operation="record_sync_operation",
                entity="sync_operation",
                identifier=str(self.id),
                detail=(f"status must be a SyncOperationStatus, not {type(self.status).__name__}"),
            )
        _require_lower_snake_case(self.operation_type, field_name="operation_type", job_id=self.id)
        if len(self.operation_type) > MAXIMUM_OPERATION_TYPE_LENGTH:
            raise EntityInvariantError(
                operation="record_sync_operation",
                entity="sync_operation",
                identifier=str(self.id),
                detail=f"operation_type exceeds {MAXIMUM_OPERATION_TYPE_LENGTH} characters",
            )
        if self.entity_type is not None:
            _require_lower_snake_case(self.entity_type, field_name="entity_type", job_id=self.id)
        if self.status is SyncOperationStatus.APPLIED and self.entity_type is None:
            raise EntityInvariantError(
                operation="record_sync_operation",
                entity="sync_operation",
                identifier=str(self.id),
                detail=(
                    "an applied operation must name the kind of record it produced; otherwise a "
                    "retry cannot be told what it already did"
                ),
            )
        self._check_detail()

    def _check_detail(self) -> None:
        if self.detail is None:
            return
        if len(self.detail) > MAXIMUM_DETAIL_KEYS:
            raise EntityInvariantError(
                operation="record_sync_operation",
                entity="sync_operation",
                identifier=str(self.id),
                detail=f"detail exceeds {MAXIMUM_DETAIL_KEYS} keys",
            )
        for key, value in self.detail.items():
            _require_lower_snake_case(key, field_name="detail key", job_id=self.id)
            if not isinstance(value, str) or len(value) > MAXIMUM_DETAIL_VALUE_LENGTH:
                raise EntityInvariantError(
                    operation="record_sync_operation",
                    entity="sync_operation",
                    identifier=str(self.id),
                    detail=(
                        f"detail value for {key!r} must be a string of at most "
                        f"{MAXIMUM_DETAIL_VALUE_LENGTH} characters"
                    ),
                )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def record(
        cls,
        *,
        operation_id: UUID,
        tenant_id: UUID,
        operation_type: str,
        status: SyncOperationStatus,
        now: datetime,
        actor_id: UUID | None = None,
        device_id: UUID | None = None,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        detail: dict[str, str] | None = None,
    ) -> SyncOperationModel:
        """Build the record of one operation. The identifier is the client's own."""
        return cls(
            id=operation_id,
            tenant_id=tenant_id,
            operation_type=operation_type.strip(),
            status=status,
            occurred_at=now,
            actor_id=actor_id,
            device_id=device_id,
            entity_type=entity_type.strip() if entity_type else None,
            entity_id=entity_id,
            detail=dict(detail) if detail else None,
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    def is_settled(self) -> bool:
        """Return True when a retry of this operation has an answer already."""
        return self.status in {SyncOperationStatus.APPLIED, SyncOperationStatus.REPLAYED}

    def describe_for_audit(self) -> dict[str, str]:
        """Return the identifiers a log line needs, and never the payload."""
        fields = {
            "sync_operation_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "operation_type": self.operation_type,
            "status": self.status.value,
        }
        if self.device_id is not None:
            fields["device_id"] = str(self.device_id)
        if self.entity_type is not None:
            fields["entity_type"] = self.entity_type
        if self.entity_id is not None:
            fields["entity_id"] = str(self.entity_id)
        return fields


def _require_lower_snake_case(value: str, *, field_name: str, job_id: UUID) -> None:
    if not isinstance(value, str) or not value.strip():
        raise EntityInvariantError(
            operation="record_sync_operation",
            entity="sync_operation",
            identifier=str(job_id),
            detail=f"{field_name} is required",
        )
    if any(character not in _LOWER_SNAKE_CASE for character in value):
        raise EntityInvariantError(
            operation="record_sync_operation",
            entity="sync_operation",
            identifier=str(job_id),
            detail=(
                f"{field_name} {value!r} must be lower-case words joined by underscores; the "
                "client and the server have to agree on what an operation is called"
            ),
        )
