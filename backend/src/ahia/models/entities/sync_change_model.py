"""A change to a business's data, in the order the server applied it.

The feed exists because timestamps cannot order changes across devices. Two phones recording a
sale a second apart, a clock that is four minutes fast, and a client that asks "what happened
since 10:04" gets an answer that depends on whose clock was right. A sequence assigned by the
one server that wrote the row does not have that problem: it is a total order, and a client that
has seen 1000 knows the next thing it is owed is 1001.

**The sequence is the server's, never the client's.** The column is an identity column, so the
database assigns it and an insert that tries to choose one is refused. A caller-supplied
sequence would let a device place its own change wherever it liked in every other device's feed.

**A change names a record; it does not carry one.** The row says which record changed, how, and
when. A client that is behind fetches the current record through the endpoint that owns it -
which already checks the permission and already knows the wire format. Copying the record into
the feed would be a second representation of the domain that can disagree with the first, and it
would grow the table by the size of everything that has ever changed. The cost is one extra
round trip per changed record, and the alternative is a feed that lies.

**A deletion is a change like any other.** `change_type` distinguishes a record that appeared,
one that changed and one that is gone. Nothing in this product hard-deletes business records -
financial history is reversed and customers are deactivated - so a `DELETED` change is rare and
means a record whose removal the client must mirror, such as a gallery image.

**Only changes worth synchronizing are here.** An event about a session being refreshed or a
namespace being provisioned is real, and it is in the audit trail, but no client holds it
offline. `AuditEventService` writes a change row only for the entity types declared as
synchronizable, which is what keeps the feed small enough to be useful.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError

MAXIMUM_ENTITY_TYPE_LENGTH: Final[int] = 64

#: The characters an entity type may use, matching the audit vocabulary: lower-case words joined
#: by underscores. The feed and the trail name entities the same way on purpose, because the feed
#: is a projection of the trail and two spellings of one entity is a client that misses changes.
_LOWER_SNAKE_CASE: Final[str] = "abcdefghijklmnopqrstuvwxyz0123456789_"


#: The entity types a client can hold offline, and therefore the ones the feed carries. An
#: event about a session being refreshed or a role's grants changing is real, and it is in the
#: audit trail, but no client holds either offline - putting them in the feed would make every
#: device fetch records it has no use for and cannot display.
SYNCHRONIZABLE_ENTITY_TYPES: Final[frozenset[str]] = frozenset(
    {
        "category",
        "product",
        "product_image",
        "inventory",
        "inventory_movement",
        "customer",
        "sale",
        "expense",
    }
)


class ChangeType(StrEnum):
    """What happened to the record."""

    CREATED = "CREATED"
    UPDATED = "UPDATED"
    DELETED = "DELETED"


@dataclass(frozen=True, slots=True)
class SyncChangeModel:
    """One change in a business's feed."""

    id: UUID
    tenant_id: UUID
    change_sequence: int
    entity_type: str
    entity_id: UUID
    change_type: ChangeType
    occurred_at: datetime
    operation_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.change_sequence < 1:
            raise EntityInvariantError(
                operation="record_change",
                entity="sync_change",
                identifier=str(self.id),
                detail=(
                    f"change_sequence must be positive, not {self.change_sequence}; a client "
                    "that has seen 0 is owed the first change"
                ),
            )
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise EntityInvariantError(
                operation="record_change",
                entity="sync_change",
                identifier=str(self.id),
                detail="occurred_at is a naive datetime; timestamps must carry a timezone",
            )
        if not isinstance(self.change_type, ChangeType):
            raise EntityInvariantError(
                operation="record_change",
                entity="sync_change",
                identifier=str(self.id),
                detail=f"change_type must be a ChangeType, not {type(self.change_type).__name__}",
            )
        _require_lower_snake_case(self.entity_type, field_name="entity_type", change_id=self.id)
        if len(self.entity_type) > MAXIMUM_ENTITY_TYPE_LENGTH:
            raise EntityInvariantError(
                operation="record_change",
                entity="sync_change",
                identifier=str(self.id),
                detail=f"entity_type exceeds {MAXIMUM_ENTITY_TYPE_LENGTH} characters",
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def for_record(
        cls,
        *,
        change_id: UUID,
        tenant_id: UUID,
        change_sequence: int,
        entity_type: str,
        entity_id: UUID,
        change_type: ChangeType,
        now: datetime,
        operation_id: UUID | None = None,
    ) -> SyncChangeModel:
        """Build a change entry.

        `change_sequence` is passed in rather than generated here because it is the database's
        to assign: the entity validates what came back, so an identity column that somehow
        produced a zero is caught at the boundary rather than by a client that never advances.
        """
        return cls(
            id=change_id,
            tenant_id=tenant_id,
            change_sequence=change_sequence,
            entity_type=entity_type.strip(),
            entity_id=entity_id,
            change_type=change_type,
            occurred_at=now,
            operation_id=operation_id,
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    def describe_for_audit(self) -> dict[str, str]:
        """Return the identifiers a log line needs."""
        return {
            "sync_change_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "change_sequence": str(self.change_sequence),
            "entity_type": self.entity_type,
            "entity_id": str(self.entity_id),
            "change_type": self.change_type.value,
        }


def _require_lower_snake_case(value: str, *, field_name: str, change_id: UUID) -> None:
    if not isinstance(value, str) or not value.strip():
        raise EntityInvariantError(
            operation="record_change",
            entity="sync_change",
            identifier=str(change_id),
            detail=f"{field_name} is required",
        )
    if any(character not in _LOWER_SNAKE_CASE for character in value):
        raise EntityInvariantError(
            operation="record_change",
            entity="sync_change",
            identifier=str(change_id),
            detail=(
                f"{field_name} {value!r} must be lower-case words joined by underscores; "
                "the feed and the audit trail name entities the same way"
            ),
        )
