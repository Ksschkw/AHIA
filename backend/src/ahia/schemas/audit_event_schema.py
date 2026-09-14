"""Transport contracts for the audit trail.

**The trail is read-only over HTTP, and this contract has no write shape at all.** An event is
written by the use case that performed the action, inside that use case's transaction; there is
no request that creates one, and no request that changes or removes one. A client can read the
trail and nothing else, which is what makes it evidence rather than data.

**The detail travels verbatim, and it is safe to travel because of what is allowed in it.** The
entity refuses a key that names a credential, refuses values that are not short strings and
refuses free text where an identifier belongs, so what a reader sees here is identifiers and
vocabulary values. The alternative - filtering the mapping on the way out - would mean the
rule lived in two places and could disagree.

**`occurred_at` is when the action happened.** It is not the same thing as when the row was
written, and this contract deliberately does not expose the second: a reader asking "when did
this happen" should get one answer.

**The filters are the three questions a person asks.** What happened in this period, what
happened to this record, and what did this person do. They combine, because "what did this
person do to this record" is the question that follows the first two.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ahia.models.entities.audit_event_model import AuditEventModel, AuditOutcome

#: The action or entity type as a filter. Shaped like the stored vocabulary, so a filter that
#: cannot match anything is refused at the edge rather than returning an empty page that looks
#: like "nothing happened".
AuditVocabularyFilter = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$"),
]
AuditEventLimit = Annotated[int, Field(ge=1, le=500)]


class AuditEventResponseSchema(BaseModel):
    """One event in the trail, as a business owner reads it."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    action: str
    entity_type: str
    entity_id: UUID | None
    actor_id: UUID | None
    device_id: UUID | None
    operation_id: UUID | None
    outcome: AuditOutcome
    is_refusal: bool
    detail: dict[str, str]
    occurred_at: datetime

    @classmethod
    def from_entity(cls, event: AuditEventModel) -> AuditEventResponseSchema:
        return cls(
            id=event.id,
            tenant_id=event.tenant_id,
            action=event.action,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            actor_id=event.actor_id,
            device_id=event.device_id,
            operation_id=event.operation_id,
            outcome=event.outcome,
            is_refusal=event.is_refusal(),
            detail=event.detail,
            occurred_at=event.occurred_at,
        )
