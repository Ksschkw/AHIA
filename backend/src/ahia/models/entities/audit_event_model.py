"""An audit event: who did what, to which record, and what came of it.

The audit trail answers the question a business asks after something has gone wrong and the
question a regulator asks before anything has: *who changed this, and when*. Logs answer the
same question only until they are rotated, so the record that has to survive lives in a table.

**Append-only, enforced by a trigger.** An audit event is never updated and never deleted, and
`audit_event_crud` has no function that could do either. A row that can be edited is not
evidence. The database refuses the change for a psql session, a migration and a future service
that has not read this docstring.

**Every event carries its own context rather than being joined to one.** The tenant, the actor,
the device, the offline operation and the moment are copied in at the time the action happened.
Joining to `users` or `devices` at read time would let a later edit to those tables change what
the trail says about the past, which is the one thing a trail must never do.

**`action` names the use case, not the table.** `record_expense`, `complete_sale`,
`deactivate_account`: the audit reads as a list of things people did, and a use case that spans
four tables produces one event rather than four that nobody can line up.

**`outcome` records the failures too, and that is half its value.** A refusal that is only
logged disappears when the log does; "this person tried to cancel a sale ten times" is a
question somebody eventually asks. `DENIED` is an authorization refusal, `FAILED` is an
operation that was permitted and did not complete.

**`detail` holds identifiers and vocabulary values, never free text.** It is a mapping of
short strings, which is what lets a trail record "sale_id, receipt_number, amount" without
becoming a second copy of the database - and without becoming the place where a password or a
customer's phone number quietly accumulates. The entity refuses the key names that indicate a
secret, so the mistake fails at the write rather than being discovered in an incident review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError

MAXIMUM_ACTION_LENGTH: Final[int] = 64
MAXIMUM_ENTITY_TYPE_LENGTH: Final[int] = 64
MAXIMUM_DETAIL_KEYS: Final[int] = 24
MAXIMUM_DETAIL_KEY_LENGTH: Final[int] = 64
MAXIMUM_DETAIL_VALUE_LENGTH: Final[int] = 256

#: Key names that indicate a secret or a credential. This is a safety net, not the primary
#: control: the primary control is that callers pass the entity's own `describe_for_audit`,
#: which returns identifiers and vocabulary values only. A name that looks like a secret is
#: refused here so that a mistake in a call site fails at the write rather than in an incident
#: review. It is deliberately a substring match: `user_password`, `PASSWORD` and `api_key_id`
#: all mean the same mistake.
_SENSITIVE_DETAIL_KEY_FRAGMENTS: Final[tuple[str, ...]] = (
    "password",
    "secret",
    "token",
    "credential",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "private_key",
    "pin",
    "card_number",
    "cvv",
    "ssn",
)

#: The characters an action or entity type may use: lower-case words joined by underscores.
#: Bounded and shaped, because these columns are what a trail is grouped and filtered by, and
#: `Record Expense` next to `record_expense` is two actions as far as a report is concerned.
_LOWER_SNAKE_CASE: Final[str] = "abcdefghijklmnopqrstuvwxyz0123456789_"


class AuditOutcome(StrEnum):
    """What came of the action the event describes."""

    SUCCEEDED = "SUCCEEDED"
    DENIED = "DENIED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class AuditEventModel:
    """One recorded action."""

    id: UUID
    tenant_id: UUID
    action: str
    entity_type: str
    outcome: AuditOutcome
    occurred_at: datetime
    actor_id: UUID | None = None
    device_id: UUID | None = None
    operation_id: UUID | None = None
    entity_id: UUID | None = None
    detail: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_aware(self.occurred_at, event_id=self.id)
        _require_lower_snake_case(self.action, field_name="action", event_id=self.id)
        _require_lower_snake_case(self.entity_type, field_name="entity_type", event_id=self.id)

        if not isinstance(self.outcome, AuditOutcome):
            raise EntityInvariantError(
                operation="record_audit_event",
                entity="audit_event",
                identifier=str(self.id),
                detail=f"outcome must be an AuditOutcome, not {type(self.outcome).__name__}",
            )
        if len(self.action) > MAXIMUM_ACTION_LENGTH:
            raise EntityInvariantError(
                operation="record_audit_event",
                entity="audit_event",
                identifier=str(self.id),
                detail=f"action exceeds {MAXIMUM_ACTION_LENGTH} characters",
            )
        if len(self.entity_type) > MAXIMUM_ENTITY_TYPE_LENGTH:
            raise EntityInvariantError(
                operation="record_audit_event",
                entity="audit_event",
                identifier=str(self.id),
                detail=f"entity_type exceeds {MAXIMUM_ENTITY_TYPE_LENGTH} characters",
            )

        self._check_detail()

    def _check_detail(self) -> None:
        if len(self.detail) > MAXIMUM_DETAIL_KEYS:
            raise EntityInvariantError(
                operation="record_audit_event",
                entity="audit_event",
                identifier=str(self.id),
                detail=f"detail exceeds {MAXIMUM_DETAIL_KEYS} keys",
            )
        for key, value in self.detail.items():
            _require_lower_snake_case(key, field_name="detail key", event_id=self.id)
            if len(key) > MAXIMUM_DETAIL_KEY_LENGTH:
                raise EntityInvariantError(
                    operation="record_audit_event",
                    entity="audit_event",
                    identifier=str(self.id),
                    detail=f"detail key exceeds {MAXIMUM_DETAIL_KEY_LENGTH} characters",
                )
            if not isinstance(value, str):
                raise EntityInvariantError(
                    operation="record_audit_event",
                    entity="audit_event",
                    identifier=str(self.id),
                    detail=(
                        f"detail value for {key!r} must be a string, not {type(value).__name__}"
                    ),
                )
            if len(value) > MAXIMUM_DETAIL_VALUE_LENGTH:
                raise EntityInvariantError(
                    operation="record_audit_event",
                    entity="audit_event",
                    identifier=str(self.id),
                    detail=f"detail value for {key!r} exceeds {MAXIMUM_DETAIL_VALUE_LENGTH} chars",
                )
            lowered = key.lower()
            for fragment in _SENSITIVE_DETAIL_KEY_FRAGMENTS:
                if fragment in lowered:
                    raise EntityInvariantError(
                        operation="record_audit_event",
                        entity="audit_event",
                        identifier=str(self.id),
                        detail=(
                            f"detail key {key!r} names a credential; the trail records "
                            "identifiers, never secrets"
                        ),
                    )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def record(
        cls,
        *,
        event_id: UUID,
        tenant_id: UUID,
        action: str,
        entity_type: str,
        now: datetime,
        outcome: AuditOutcome = AuditOutcome.SUCCEEDED,
        actor_id: UUID | None = None,
        device_id: UUID | None = None,
        operation_id: UUID | None = None,
        entity_id: UUID | None = None,
        detail: dict[str, str] | None = None,
    ) -> AuditEventModel:
        """Build an event, taking the moment it happened as the only clock.

        `now` is passed in rather than read here so that the event and the change it describes
        carry the same instant: two calls to the clock inside one transaction can differ, and
        an audit trail whose timestamps disagree with the record it audits is a trail nobody
        can order.
        """
        return cls(
            id=event_id,
            tenant_id=tenant_id,
            action=action.strip(),
            entity_type=entity_type.strip(),
            outcome=outcome,
            occurred_at=now,
            actor_id=actor_id,
            device_id=device_id,
            operation_id=operation_id,
            entity_id=entity_id,
            detail=dict(detail or {}),
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    def is_refusal(self) -> bool:
        """Return True when the action did not take effect.

        A refusal is the half of a trail that logs alone cannot hold on to, and it is what
        makes "who tried" answerable as well as "who did".
        """
        return self.outcome is not AuditOutcome.SUCCEEDED

    def as_log_fields(self) -> dict[str, str]:
        """Return the event as identifiers for a structured log line.

        No `detail`: the trail is where detail belongs, and a log line that repeated it would
        put the same values in a second store with different retention.
        """
        fields = {
            "audit_event_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": str(self.entity_id) if self.entity_id is not None else "",
            "outcome": self.outcome.value,
        }
        if self.actor_id is not None:
            fields["actor_id"] = str(self.actor_id)
        if self.operation_id is not None:
            fields["operation_id"] = str(self.operation_id)
        return fields


def _require_lower_snake_case(value: str, *, field_name: str, event_id: UUID) -> None:
    if not isinstance(value, str) or not value.strip():
        raise EntityInvariantError(
            operation="record_audit_event",
            entity="audit_event",
            identifier=str(event_id),
            detail=f"{field_name} is required",
        )
    if any(character not in _LOWER_SNAKE_CASE for character in value):
        raise EntityInvariantError(
            operation="record_audit_event",
            entity="audit_event",
            identifier=str(event_id),
            detail=(
                f"{field_name} {value!r} must be lower-case words joined by underscores; "
                "a trail is grouped and filtered by this value"
            ),
        )


def _require_aware(moment: datetime, *, event_id: UUID) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="record_audit_event",
            entity="audit_event",
            identifier=str(event_id),
            detail="occurred_at is a naive datetime; timestamps must carry a timezone",
        )
