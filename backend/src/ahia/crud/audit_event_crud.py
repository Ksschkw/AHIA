"""Persistence for the audit trail.

One table, one entity, one file, and **no update and no delete function exists in this
module**. That absence is the design, exactly as it is for the stock and financial ledgers: a
trail that can be edited is not evidence. A test asserts the absence mechanically, because a
helper added later "to fix a typo in an old event" would quietly turn the trail into a table
somebody can rewrite.

The database enforces the same rule
    A trigger refuses UPDATE and DELETE. The application having no such function is a
    convention; the trigger holds for a psql session, a migration and a future service that has
    not read this docstring.

Events are read by what a person asks
    "What happened in this business" is `(tenant_id, occurred_at)`; "what happened to this
    record" is `(tenant_id, entity_type, entity_id, occurred_at)`; "what did this person do" is
    `(tenant_id, actor_id, occurred_at)`. All three are declared with the table rather than
    discovered from a slow screen later.

`actor_id` and `device_id` are copies, not references, and carry no foreign key
    The trail records who acted at the moment the action happened. An event that pointed at
    `users` would be a copy with a leash: the row could not be written if the actor were
    missing, and - because this table is append-only and refuses deletes - the trail would also
    pin that user row forever, making an erasure of a person impossible to complete. The
    identifier is copied in and belongs to the event. This is the same decision the entity states
    for the context it carries, applied to the constraints.

`detail` is JSON, and it is bounded by the entity rather than by the column
    A second, weaker bound on the column would only be a second answer. The entity refuses
    secrets by key name, refuses values that are not short strings and refuses free text
    where an identifier belongs, so what reaches this column is what the entity allowed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ahia.core.database import Base
from ahia.crud.integrity_violations import translate_integrity_violation
from ahia.models.entities.audit_event_model import (
    MAXIMUM_ACTION_LENGTH,
    MAXIMUM_ENTITY_TYPE_LENGTH,
    AuditEventModel,
    AuditOutcome,
)

_TABLE_NAME: Final[str] = "audit_events"
_OUTCOME_LENGTH: Final[int] = 16

_MISSING_REFERENCE: Final[str] = (
    "the business, actor or device this audit event references does not exist"
)


class AuditEventRecord(Base):
    """The persistence representation of one audit event."""

    __tablename__ = _TABLE_NAME

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(MAXIMUM_ACTION_LENGTH), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(MAXIMUM_ENTITY_TYPE_LENGTH), nullable=False)
    # Nullable: an event caused by the system rather than by a person - the permission
    # registry being provisioned, a scheduled job - has no actor, and inventing one would put
    # a name on an action nobody took. Deliberately not a foreign key: the identifier belongs to
    # the event, so the trail neither requires the user row to exist nor pins it forever.
    actor_id: Mapped[UUID | None] = mapped_column(nullable=True)
    device_id: Mapped[UUID | None] = mapped_column(nullable=True)
    operation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    # The entity the action was about. Nullable because a refusal can be about a record that
    # does not exist, and the reason it was refused is the interesting part.
    entity_id: Mapped[UUID | None] = mapped_column(nullable=True)
    outcome: Mapped[str] = mapped_column(String(_OUTCOME_LENGTH), nullable=False)
    # JSONB rather than TEXT: a trail is queried by the identifiers inside it, and the entity
    # is what bounds it.
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_audit_events_tenant_occurred", "tenant_id", "occurred_at"),
        Index(
            "ix_audit_events_tenant_entity",
            "tenant_id",
            "entity_type",
            "entity_id",
            "occurred_at",
        ),
        Index("ix_audit_events_tenant_actor", "tenant_id", "actor_id", "occurred_at"),
        Index("ix_audit_events_tenant_action", "tenant_id", "action", "occurred_at"),
    )


def to_entity(record: AuditEventRecord) -> AuditEventModel:
    return AuditEventModel(
        id=record.id,
        tenant_id=record.tenant_id,
        action=record.action,
        entity_type=record.entity_type,
        outcome=AuditOutcome(record.outcome),
        occurred_at=record.occurred_at,
        actor_id=record.actor_id,
        device_id=record.device_id,
        operation_id=record.operation_id,
        entity_id=record.entity_id,
        detail={str(key): str(value) for key, value in (record.detail or {}).items()},
    )


def apply_entity(record: AuditEventRecord, entity: AuditEventModel) -> None:
    record.tenant_id = entity.tenant_id
    record.action = entity.action
    record.entity_type = entity.entity_type
    record.actor_id = entity.actor_id
    record.device_id = entity.device_id
    record.operation_id = entity.operation_id
    record.entity_id = entity.entity_id
    record.outcome = entity.outcome.value
    record.detail = dict(entity.detail)
    record.occurred_at = entity.occurred_at


async def record(session: AsyncSession, event: AuditEventModel) -> AuditEventModel:
    """Append one event to the trail.

    There is no `update` and no `delete` beside this function, and the table refuses both at
    the database level. The only way to correct the trail is to append to it.

    Does not commit: the caller owns the transaction, because an event that describes a change
    must land with that change or the trail would claim something happened that did not.
    """
    row = AuditEventRecord(id=event.id)
    apply_entity(row, event)
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as conflict:
        await session.rollback()
        raise translate_integrity_violation(
            conflict,
            operation="record_audit_event",
            entity="audit_event",
            identifier=str(event.id),
            conflict_detail="this audit event collides with an existing one",
            missing_detail=_MISSING_REFERENCE,
        ) from conflict
    return to_entity(row)


async def list_for_tenant(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    limit: int = 100,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[AuditEventModel]:
    """Return a business's events, most recent first.

    The period is inclusive at the start and exclusive at the end, so consecutive periods tile
    without showing the same event twice.
    """
    statement = select(AuditEventRecord).where(AuditEventRecord.tenant_id == tenant_id)
    if since is not None:
        statement = statement.where(AuditEventRecord.occurred_at >= since)
    if until is not None:
        statement = statement.where(AuditEventRecord.occurred_at < until)
    result = await session.execute(
        statement.order_by(AuditEventRecord.occurred_at.desc(), AuditEventRecord.id.desc()).limit(
            limit
        )
    )
    return [to_entity(row) for row in result.scalars().all()]


async def list_for_entity(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    entity_type: str,
    entity_id: UUID,
    limit: int = 100,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[AuditEventModel]:
    """Return the history of one record: what happened to it, and in what order."""
    statement = (
        select(AuditEventRecord)
        .where(AuditEventRecord.tenant_id == tenant_id)
        .where(AuditEventRecord.entity_type == entity_type)
        .where(AuditEventRecord.entity_id == entity_id)
    )
    if since is not None:
        statement = statement.where(AuditEventRecord.occurred_at >= since)
    if until is not None:
        statement = statement.where(AuditEventRecord.occurred_at < until)
    result = await session.execute(
        statement.order_by(AuditEventRecord.occurred_at, AuditEventRecord.id).limit(limit)
    )
    return [to_entity(row) for row in result.scalars().all()]


async def list_for_actor(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    limit: int = 100,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[AuditEventModel]:
    """Return what one person did in one business, most recent first."""
    statement = (
        select(AuditEventRecord)
        .where(AuditEventRecord.tenant_id == tenant_id)
        .where(AuditEventRecord.actor_id == actor_id)
    )
    if since is not None:
        statement = statement.where(AuditEventRecord.occurred_at >= since)
    if until is not None:
        statement = statement.where(AuditEventRecord.occurred_at < until)
    result = await session.execute(
        statement.order_by(AuditEventRecord.occurred_at.desc(), AuditEventRecord.id.desc()).limit(
            limit
        )
    )
    return [to_entity(row) for row in result.scalars().all()]


async def count_for_tenant(session: AsyncSession, tenant_id: UUID) -> int:
    """Return how many events a business's trail holds."""
    result = await session.execute(
        select(func.count())
        .select_from(AuditEventRecord)
        .where(AuditEventRecord.tenant_id == tenant_id)
    )
    return int(result.scalar_one())
