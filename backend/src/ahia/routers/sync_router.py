"""HTTP transport for offline synchronization.

Three routes on `/tenants/{tenant_id}/sync`: push a queue, pull the feed, and record how far the
device has read.

**The router re-implements nothing.** Push hands each parsed operation to `SyncService`, which
hands it to the use case that owns it. The only work done here is what transport does: parse the
queue, translate each validated payload into the service's request shape, and render the answers.
A rule that lived here would be a rule an offline client did not get.

**The tenant is in the path, as it is for every other business endpoint.** The specification
sketches `POST /sync/push`; this product resolves a business from the path and the membership on
every business route, and a sync route with an implicit tenant would be the one endpoint where a
client's business was guessed from a token rather than stated. When the mobile client ships, the
URL it uses is `/tenants/{tenant_id}/sync/push`.

**The whole feature is behind `FEATURE_OFFLINE_SYNC`, which is off by default.** While it is off,
these routes answer as if they did not exist - the same 404 an unknown path produces, saying
nothing about whether the feature exists in this deployment. A flag that answered 403 would tell
a caller that sync is a thing this server can do, and it would make "not enabled" distinguishable
from "not deployed".

**A conflict is a 200 with a conflict in it.** One operation's stale version must not hide the
answers to the queue behind it; each result carries its own status and a client reads
`needs_attention` for the ones a person has to look at. Authorization is per operation, in the use
case, so the status codes here are about the batch rather than about one operation inside it.

**Pull does not advance the cursor.** The device says how far it applied, through
`POST /sync/cursor`, because a client that applied half a page and died must not be told it is
further along than it is. The separate call is what makes the client the authority on its own
progress, and the cursor only moves forward.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request

from ahia.core.config import Settings
from ahia.core.errors import NotFoundError
from ahia.core.tenant_context import TenantContext
from ahia.routers.tenant_router import require_tenant_context
from ahia.schemas.sync_schema import (
    SyncChangeSchema,
    SyncCursorRequestSchema,
    SyncCursorResponseSchema,
    SyncOperationResultSchema,
    SyncPullRequestSchema,
    SyncPullResponseSchema,
    SyncPushRequestSchema,
    SyncPushResponseSchema,
    payload_as_mapping,
)
from ahia.services.sync_service import SyncOperationRequest, SyncService

_TENANT_SCOPE_PREFIX: Final[str] = "/tenants/{tenant_id}"

router = APIRouter(prefix=_TENANT_SCOPE_PREFIX, tags=["sync"])


def get_sync_service(request: Request) -> SyncService:
    """Return the sync service for this request."""
    service: SyncService = request.app.state.container.sync_service
    return service


def require_offline_sync(request: Request) -> None:
    """Refuse as if the route did not exist, while the feature flag is off.

    The refusal is the same shape as an unknown path so that a caller cannot tell a deployment
    with the feature switched off from one that has never had it. It is not a security control -
    the use cases behind it authorize every operation themselves - so switching it on grants
    nothing a caller did not already have.
    """
    settings: Settings = request.app.state.settings
    if not settings.is_feature_enabled("feature_offline_sync"):
        raise NotFoundError(
            operation="offline_sync",
            entity="sync_endpoint",
            detail="offline synchronization is not enabled in this deployment",
        )


SyncServiceDependency = Annotated[SyncService, Depends(get_sync_service)]
TenantContextDependency = Annotated[TenantContext, Depends(require_tenant_context)]


@router.post(
    "/sync/push",
    response_model=SyncPushResponseSchema,
    dependencies=[Depends(require_offline_sync)],
    summary="Push a device's queued operations",
)
async def push_operations(
    payload: SyncPushRequestSchema,
    tenant_context: TenantContextDependency,
    service: SyncServiceDependency,
) -> SyncPushResponseSchema:
    """Apply a queue of offline operations, one answer each.

    Every operation is executed by the use case that owns it, so the permission checked is the same
    one an online request meets. An operation whose identifier has already been recorded is
    answered from the first attempt and nothing runs.
    """
    pushed = await service.push_operations(
        tenant_context,
        operations=[
            SyncOperationRequest(
                operation_id=operation.operation_id,
                operation_type=operation.operation_type,
                payload=payload_as_mapping(operation.payload),
            )
            for operation in payload.operations
        ],
    )
    return SyncPushResponseSchema(
        results=[SyncOperationResultSchema.from_result(result) for result in pushed.results]
    )


@router.post(
    "/sync/pull",
    response_model=SyncPullResponseSchema,
    dependencies=[Depends(require_offline_sync)],
    summary="Pull the changes a device is owed",
)
async def pull_changes(
    payload: SyncPullRequestSchema,
    tenant_context: TenantContextDependency,
    service: SyncServiceDependency,
) -> SyncPullResponseSchema:
    """Return the changes this caller may read, after the sequence it reported.

    Filtered by permission per entity type: a salesperson receives the catalogue, the customers
    and the sales, and never an expense. The latest sequence is the business's, not the caller's,
    so a client can tell whether it is behind.
    """
    page = await service.pull_changes(
        tenant_context, after_sequence=payload.after_sequence, limit=payload.limit
    )
    return SyncPullResponseSchema(
        changes=[SyncChangeSchema.from_entity(change) for change in page.changes],
        latest_sequence=page.latest_sequence,
        has_more=page.has_more,
    )


@router.post(
    "/sync/cursor",
    response_model=SyncCursorResponseSchema,
    dependencies=[Depends(require_offline_sync)],
    summary="Record how far this device has read",
)
async def advance_cursor(
    payload: SyncCursorRequestSchema,
    tenant_context: TenantContextDependency,
    service: SyncServiceDependency,
) -> SyncCursorResponseSchema:
    """Move this device's cursor forward, and return where it now is.

    The device identifier comes from the authenticated context, so this request cannot move another
    phone's cursor. A sequence below the current position is refused: a cursor that moved backwards
    would make the device re-apply changes it has already applied.
    """
    sequence = await service.advance_cursor(tenant_context, sequence=payload.sequence)
    return SyncCursorResponseSchema(last_server_sequence=sequence)


@router.get(
    "/sync/cursor",
    response_model=SyncCursorResponseSchema,
    dependencies=[Depends(require_offline_sync)],
    summary="Read how far this device has read",
)
async def read_cursor(
    tenant_context: TenantContextDependency,
    service: SyncServiceDependency,
) -> SyncCursorResponseSchema:
    """Return this device's position, or zero when it has never synchronized."""
    return SyncCursorResponseSchema(
        last_server_sequence=await service.current_cursor(tenant_context)
    )
