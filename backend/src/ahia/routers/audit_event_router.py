"""HTTP transport for the audit trail.

Two read routes on `/tenants/{tenant_id}/audit-events`, and nothing else.

**No write route exists, and none can be added here by accident.** An audit event is written by
the use case that performed the action, inside that use case's transaction, through
`AuditEventService.record_audit_event`. A `POST` would let a client invent history; a `PATCH` or
a `DELETE` would let one rewrite it, and the table refuses both at the database level anyway.
This module offers `GET` twice, and a test asserts that every other method reaches no handler.

**The permission is `reports.read`, held by the owner and the manager.** The trail names who did
what, so it is not a screen a salesperson needs, and the check is enforced in the service rather
than here: a CLI or a scheduled job calling the same use case gets the same answer.

**A period on the listing is optional; on a record's history it is not accepted at all.** The
history of one record is short enough to read whole, and a boundary there would invite a reader
to believe a record has no history because they chose the wrong window.

Every handler parses, calls one service method and shapes the response.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from ahia.core.tenant_context import TenantContext
from ahia.routers.tenant_router import require_tenant_context
from ahia.schemas.audit_event_schema import (
    AuditEventLimit,
    AuditEventResponseSchema,
    AuditVocabularyFilter,
)
from ahia.services.audit_event_service import AuditEventService

_TENANT_SCOPE_PREFIX: Final[str] = "/tenants/{tenant_id}"

router = APIRouter(prefix=_TENANT_SCOPE_PREFIX, tags=["audit"])


def get_audit_event_service(request: Request) -> AuditEventService:
    """Return the audit service for this request."""
    service: AuditEventService = request.app.state.container.audit_event_service
    return service


AuditEventServiceDependency = Annotated[AuditEventService, Depends(get_audit_event_service)]
TenantContextDependency = Annotated[TenantContext, Depends(require_tenant_context)]


@dataclass(frozen=True, slots=True)
class AuditTrailQuery:
    """The three questions a person asks of a trail, as the caller sent them.

    Grouped rather than passed one at a time because they are read together: "what did this
    person do to this record last Tuesday" is one question with three parts.
    """

    since: Annotated[
        datetime | None,
        Query(description="Start of the period, inclusive. Must carry a timezone."),
    ] = None
    until: Annotated[
        datetime | None,
        Query(description="End of the period, exclusive. Must carry a timezone."),
    ] = None
    entity_type: Annotated[
        AuditVocabularyFilter | None,
        Query(description="Only events about this kind of record."),
    ] = None
    entity_id: Annotated[UUID | None, Query(description="Only events about this record.")] = None
    actor_id: Annotated[UUID | None, Query(description="Only what this person did.")] = None

    @property
    def paired_entity_id(self) -> UUID | None:
        """Return the record identifier only when the caller also said which kind it is.

        A record identifier on its own identifies nothing: two tables can hold the same value,
        and answering from it alone would return events about whichever table matched first.
        """
        return self.entity_id if self.entity_type is not None else None


AuditTrailQueryDependency = Annotated[AuditTrailQuery, Depends()]


# Declared before the parameterised route: FastAPI matches in registration order, and a literal
# `history` would otherwise be parsed as a filter value.
@router.get(
    "/audit-events/history/{entity_type}/{entity_id}",
    response_model=list[AuditEventResponseSchema],
    summary="What happened to one record",
)
async def read_entity_history(
    entity_type: AuditVocabularyFilter,
    entity_id: UUID,
    tenant_context: TenantContextDependency,
    service: AuditEventServiceDependency,
    limit: Annotated[AuditEventLimit, Query(description="How many events to return.")] = 100,
) -> list[AuditEventResponseSchema]:
    """Return one record's history, oldest first.

    A story is read from the beginning: "what happened to this expense" is answered in order,
    and the first entry is the one that created it.
    """
    events = await service.get_entity_history(
        tenant_context, entity_type=entity_type, entity_id=entity_id, limit=limit
    )
    return [AuditEventResponseSchema.from_entity(event) for event in events]


@router.get(
    "/audit-events",
    response_model=list[AuditEventResponseSchema],
    summary="Read this business's audit trail",
)
async def list_audit_events(
    tenant_context: TenantContextDependency,
    service: AuditEventServiceDependency,
    trail_query: AuditTrailQueryDependency,
    limit: Annotated[AuditEventLimit, Query(description="How many events to return.")] = 100,
) -> list[AuditEventResponseSchema]:
    """Return the events, most recent first.

    `entity_type` and `entity_id` are a pair: sending one without the other is answered from the
    period alone rather than guessing which record was meant, and the response says which events
    were returned rather than which were not.
    """
    events = await service.list_events(
        tenant_context,
        since=trail_query.since,
        until=trail_query.until,
        entity_type=trail_query.entity_type,
        entity_id=trail_query.paired_entity_id,
        actor_id=trail_query.actor_id,
        limit=limit,
    )
    return [AuditEventResponseSchema.from_entity(event) for event in events]
