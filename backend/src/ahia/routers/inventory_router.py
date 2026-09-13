"""HTTP transport for inventory.

Seven routes on `/tenants/{tenant_id}/inventory`. The tenant's stock policy lives on the
tenant surface instead, because it is a property of the business rather than an inventory
operation.

**Route order matters here.** `GET /inventory/movements` is declared before
`GET /inventory/{product_id}`, because FastAPI matches in the order routes are registered:
with the parameterised route first, the literal word "movements" would be parsed as a
product identifier and answered with a 422 that says nothing about the real mistake.

Every handler parses, calls one service method and shapes the response. The permission
checks, the row lock, the ledger write and the projection update all live in the service,
where a CLI or a scheduled job gets the same answers as an HTTP request.
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from ahia.core.tenant_context import TenantContext
from ahia.routers.tenant_router import require_tenant_context
from ahia.schemas.inventory_schema import (
    InventoryLevelResponseSchema,
    InventoryMovementResponseSchema,
    InventoryStateResponseSchema,
    MovementLimit,
    StockAdjustmentSchema,
    StockChangeResponseSchema,
    StockDamageSchema,
    StockReceiveSchema,
    StockTransferResponseSchema,
    StockTransferSchema,
)
from ahia.services.inventory_service import InventoryService, StockChange

_TENANT_SCOPE_PREFIX: Final[str] = "/tenants/{tenant_id}"

router = APIRouter(prefix=_TENANT_SCOPE_PREFIX, tags=["inventory"])


def get_inventory_service(request: Request) -> InventoryService:
    """Return the inventory service for this request."""
    service: InventoryService = request.app.state.container.inventory_service
    return service


InventoryServiceDependency = Annotated[InventoryService, Depends(get_inventory_service)]
TenantContextDependency = Annotated[TenantContext, Depends(require_tenant_context)]


def stock_change_response(change: StockChange) -> StockChangeResponseSchema:
    """Shape one movement and the state it produced."""
    return StockChangeResponseSchema(
        inventory=InventoryStateResponseSchema.from_entity(change.inventory),
        movement=InventoryMovementResponseSchema.from_entity(change.movement),
    )


@router.get(
    "/inventory",
    response_model=list[InventoryLevelResponseSchema],
    summary="List stock for every product",
)
async def list_inventory(
    tenant_context: TenantContextDependency,
    service: InventoryServiceDependency,
) -> list[InventoryLevelResponseSchema]:
    """Return every product's stock, including the ones nobody has counted yet."""
    levels = await service.list_inventory(tenant_context)
    return [
        InventoryLevelResponseSchema.from_entities(level.product, level.inventory)
        for level in levels
    ]


@router.get(
    "/inventory/movements",
    response_model=list[InventoryMovementResponseSchema],
    summary="Read stock history",
)
async def list_movements(
    tenant_context: TenantContextDependency,
    service: InventoryServiceDependency,
    product_id: Annotated[
        UUID | None, Query(description="Limit the history to one product.")
    ] = None,
    limit: Annotated[MovementLimit, Query(description="How many movements to return.")] = 100,
) -> list[InventoryMovementResponseSchema]:
    """Return the ledger, most recent first, for one product or the whole business."""
    movements = await service.list_movements(tenant_context, product_id=product_id, limit=limit)
    return [InventoryMovementResponseSchema.from_entity(movement) for movement in movements]


@router.get(
    "/inventory/{product_id}",
    response_model=InventoryLevelResponseSchema,
    summary="Read one product's stock",
)
async def get_inventory_for_product(
    product_id: UUID,
    tenant_context: TenantContextDependency,
    service: InventoryServiceDependency,
) -> InventoryLevelResponseSchema:
    """Return one product's stock. An uncounted product reads as zero, not as missing."""
    level = await service.get_inventory_for_product(tenant_context, product_id=product_id)
    return InventoryLevelResponseSchema.from_entities(level.product, level.inventory)


@router.post(
    "/inventory/{product_id}/receipts",
    response_model=StockChangeResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Record stock arriving",
)
async def receive_stock(
    product_id: UUID,
    payload: StockReceiveSchema,
    tenant_context: TenantContextDependency,
    service: InventoryServiceDependency,
) -> StockChangeResponseSchema:
    """Record a receipt. The quantity is positive by definition."""
    change = await service.receive_stock(
        tenant_context,
        product_id=product_id,
        quantity=payload.quantity,
        note=payload.note,
        reference_type=payload.reference_type,
        reference_id=payload.reference_id,
    )
    return stock_change_response(change)


@router.post(
    "/inventory/{product_id}/adjustments",
    response_model=StockChangeResponseSchema,
    summary="Record a stock correction",
)
async def adjust_stock(
    product_id: UUID,
    payload: StockAdjustmentSchema,
    tenant_context: TenantContextDependency,
    service: InventoryServiceDependency,
) -> StockChangeResponseSchema:
    """Record a correction, in either direction, with the reason it happened."""
    change = await service.adjust_stock(
        tenant_context,
        product_id=product_id,
        delta=payload.delta,
        reason=payload.reason,
        reference_type=payload.reference_type,
        reference_id=payload.reference_id,
    )
    return stock_change_response(change)


@router.post(
    "/inventory/{product_id}/damage",
    response_model=StockChangeResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Record stock that can no longer be sold",
)
async def record_damage(
    product_id: UUID,
    payload: StockDamageSchema,
    tenant_context: TenantContextDependency,
    service: InventoryServiceDependency,
) -> StockChangeResponseSchema:
    """Record a loss. Damage is kept apart from a miscount so a report can tell them."""
    change = await service.record_damage(
        tenant_context,
        product_id=product_id,
        quantity=payload.quantity,
        reason=payload.reason,
        note=payload.note,
    )
    return stock_change_response(change)


@router.post(
    "/inventory/transfers",
    response_model=StockTransferResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Move stock from one product record to another",
)
async def transfer_stock(
    payload: StockTransferSchema,
    tenant_context: TenantContextDependency,
    service: InventoryServiceDependency,
) -> StockTransferResponseSchema:
    """Repackaging: a carton becomes units, and the total does not change."""
    source, destination = await service.transfer_stock(
        tenant_context,
        source_product_id=payload.source_product_id,
        destination_product_id=payload.destination_product_id,
        quantity=payload.quantity,
        reason=payload.reason,
        note=payload.note,
    )
    return StockTransferResponseSchema(
        source=InventoryStateResponseSchema.from_entity(source),
        destination=InventoryStateResponseSchema.from_entity(destination),
    )
