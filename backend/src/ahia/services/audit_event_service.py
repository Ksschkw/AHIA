"""Audit use cases: writing the trail, and answering questions from it.

**`record_audit_event` writes inside the caller's transaction.** It takes the session the use
case is already using rather than opening its own unit of work, because an event that describes
a change has to land with that change: a trail entry for a rolled-back write would claim
something happened that did not, and a change that committed without its entry would leave the
one gap a trail exists to close. This is the same reasoning that makes the stock ledger's
`apply_stock_change` take a session.

**Recording needs no permission, and that is deliberate.** The caller has already decided the
action is allowed - that is what `require_permission` in the use case is for. Requiring a
permission to write the record of an allowed action would mean a caller could be allowed to act
and not allowed to be audited, which is the opposite of what a trail is for. Reading the trail
is a different question, and it needs `reports.read`.

**The actor and the device come from the authorized context, never from the arguments.** A
caller cannot record that somebody else did something, which is the only way an audit trail
stays worth reading. The operation identifier is a parameter because an offline operation's
identifier is known to the use case, not to the identity that authenticated.

**Reading is owner-facing and scoped.** `list_events` and `list_history_for_entity` require
`reports.read`, which in this product is held by the owner and the manager: the trail names who
did what, and it is not a screen a salesperson needs. Both are scoped to the caller's tenant by
the query itself rather than by a filter a caller supplies.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions.report_permissions import REPORTS_READ
from ahia.core.tenant_context import TenantContext
from ahia.crud import audit_event_crud
from ahia.models.entities.audit_event_model import AuditEventModel, AuditOutcome

_AUDIT_LOGGER_NAME: Final[str] = "ahia.services.audit"

#: The default page size. A trail is read in windows: the whole history of a business is not
#: something a screen shows, and an unbounded query is a query that one day takes a minute.
DEFAULT_EVENT_LIMIT: Final[int] = 100


class AuditEventService:
    """Audit use cases."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._logger = (logger or get_logger(_AUDIT_LOGGER_NAME)).bind(
            component="audit_event_service", layer="service"
        )

    # ------------------------------------------------------------------
    # Writing, inside the caller's transaction
    # ------------------------------------------------------------------

    async def record_audit_event(
        self,
        session: object,
        tenant_context: TenantContext,
        *,
        action: str,
        entity_type: str,
        now: datetime,
        outcome: AuditOutcome = AuditOutcome.SUCCEEDED,
        entity_id: UUID | None = None,
        operation_id: UUID | None = None,
        detail: dict[str, str] | None = None,
    ) -> AuditEventModel:
        """Append one event to the trail, in the transaction the caller owns.

        `now` is passed in rather than read here so that the event and the change it describes
        carry one instant. Two calls to the clock inside a transaction can differ, and a trail
        whose timestamps disagree with the record it audits is a trail nobody can order.

        Raises whatever the persistence layer raises: a trail entry that cannot be written fails
        the use case, because a change nobody can attribute is a change this product does not
        make.
        """
        event = AuditEventModel.record(
            event_id=uuid4(),
            tenant_id=tenant_context.tenant_id,
            action=action,
            entity_type=entity_type,
            now=now,
            outcome=outcome,
            actor_id=tenant_context.user_id,
            device_id=tenant_context.device_id,
            operation_id=operation_id,
            entity_id=entity_id,
            detail=detail,
        )
        stored = await audit_event_crud.record(session, event)  # type: ignore[arg-type]
        self._logger.info("audit_event_recorded", **stored.as_log_fields())
        return stored

    # ------------------------------------------------------------------
    # Reading, for the owner
    # ------------------------------------------------------------------

    async def list_events(
        self,
        tenant_context: TenantContext,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        actor_id: UUID | None = None,
        limit: int = DEFAULT_EVENT_LIMIT,
    ) -> list[AuditEventModel]:
        """Return the business's events, most recent first.

        The filters are the three questions a person asks: what happened in this period, what
        happened to this record, and what did this person do. They are combined rather than
        choosing one, because "what did this person do to this record" is the question that
        follows the first two.
        """
        tenant_context.require_permission(
            REPORTS_READ,
            operation="list_audit_events",
            resource_type="audit_event",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            if entity_type is not None and entity_id is not None:
                return await audit_event_crud.list_for_entity(
                    session,
                    tenant_id=tenant_context.tenant_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    since=since,
                    until=until,
                    limit=limit,
                )
            if actor_id is not None:
                return await audit_event_crud.list_for_actor(
                    session,
                    tenant_id=tenant_context.tenant_id,
                    actor_id=actor_id,
                    since=since,
                    until=until,
                    limit=limit,
                )
            return await audit_event_crud.list_for_tenant(
                session,
                tenant_context.tenant_id,
                since=since,
                until=until,
                limit=limit,
            )

    async def get_entity_history(
        self,
        tenant_context: TenantContext,
        *,
        entity_type: str,
        entity_id: UUID,
        limit: int = DEFAULT_EVENT_LIMIT,
    ) -> list[AuditEventModel]:
        """Return one record's history, oldest first.

        Ordered the other way round from the listing on purpose: "what happened to this record"
        is a story, and a story is read from the beginning.
        """
        tenant_context.require_permission(
            REPORTS_READ,
            operation="read_entity_history",
            resource_type="audit_event",
            resource_id=str(entity_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await audit_event_crud.list_for_entity(
                unit_of_work.session_handle,
                tenant_id=tenant_context.tenant_id,
                entity_type=entity_type,
                entity_id=entity_id,
                limit=limit,
            )
