"""Inventory use cases: every way stock changes, through one path.

**One execution path, and that is the design.** Receiving stock, adjusting a count,
recording damage and transferring between products all end in `_apply_movement`, which
does five things inside one transaction:

    1. resolve the product in the authorized tenant
    2. lock the product's projection row
    3. read the tenant's negative-stock policy
    4. build the movement from the locked quantity - the entity derives the result
    5. append the movement, save the projection, commit

A second path that wrote stock without a movement would be a hole in the ledger, and the
house rule that a quantity cannot change without one is only true if there is no way to
change it. There is no other way in this module.

**Why the lock is not optional.** Two workers selling the last item at the same time
arrive as two transactions. Without the row lock, both read `quantity_on_hand = 1`, both
compute a new value, and the second write wins: one sale disappears from the projection
while its movement stays in the ledger. The ledger would be right and the number on the
screen wrong, which is the worst possible failure for a business that trusts the screen.
The lock serializes the read-modify-write, so the two sales produce two movements and a
projection that reflects both.

**The tenant's policy decides what a negative result means.** `BLOCK_NEGATIVE_STOCK`
refuses the movement and leaves the ledger untouched; `ALLOW_WITH_WARNING` records it and
flags it as an overdraw; `ALLOW_NEGATIVE_STOCK` records it. The decision is read from the
tenant inside the same transaction that holds the lock, so a policy changed mid-flight
cannot be applied to half of one movement.

**A note is not a reason.** `adjust_stock` and `record_damage` require a reason, because
"why is there 3 kg less rice than yesterday" is the question the ledger exists to answer.
The reason is stored on the movement, which is append-only, so it cannot be tidied up
afterwards.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.errors import DomainError, InvalidInputError, NotFoundError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions.inventory_permissions import (
    INVENTORY_ADJUST,
    INVENTORY_READ,
    INVENTORY_STOCK_IN,
)
from ahia.core.tenant_context import TenantContext
from ahia.crud import inventory_crud, inventory_movement_crud, product_crud, tenant_crud
from ahia.models.entities.inventory_model import ZERO_QUANTITY, InventoryModel
from ahia.models.entities.inventory_movement_model import (
    InventoryMovementModel,
    MovementType,
)
from ahia.models.entities.negative_stock_policy import NegativeStockPolicy
from ahia.models.entities.product_model import ProductModel

_INVENTORY_LOGGER_NAME: Final[str] = "ahia.services.inventory"

#: How many movements a listing returns unless a caller asks for fewer.
DEFAULT_MOVEMENT_LIMIT: Final[int] = 100


@dataclass(frozen=True, slots=True)
class InventoryLevel:
    """A product's stock, with the product it describes.

    The two come from different tables, and this is the shape a screen needs: the name a
    person reads beside the number that matters. Assembling it in the service is what
    keeps the repository layer free of joins.
    """

    product: ProductModel
    inventory: InventoryModel


@dataclass(frozen=True, slots=True)
class StockChange:
    """What a movement did, as the caller sees it."""

    inventory: InventoryModel
    movement: InventoryMovementModel

    @property
    def is_overdraw(self) -> bool:
        return self.movement.is_overdraw()


class InventoryService:
    """Stock use cases."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._logger = (logger or get_logger(_INVENTORY_LOGGER_NAME)).bind(
            component="inventory_service", layer="service"
        )

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    async def get_inventory_for_product(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
    ) -> InventoryLevel:
        """Return one product's stock, or refuse as if the product did not exist."""
        tenant_context.require_permission(
            INVENTORY_READ,
            operation="get_inventory_for_product",
            resource_type="inventory",
            resource_id=str(product_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            product = await self._require_product(
                session, tenant_context=tenant_context, product_id=product_id
            )
            inventory = await inventory_crud.get_for_product(
                session, tenant_id=tenant_context.tenant_id, product_id=product_id
            )
            if inventory is None:
                # Never counted is not an error: a product that was just added has nothing
                # in the shop, and inventing a missing state would make every caller handle
                # two shapes of the same answer.
                inventory = InventoryModel.empty(
                    inventory_id=uuid4(),
                    tenant_id=tenant_context.tenant_id,
                    product_id=product_id,
                    now=datetime.now(UTC),
                )
        return InventoryLevel(product=product, inventory=inventory)

    async def list_inventory(self, tenant_context: TenantContext) -> list[InventoryLevel]:
        """Return the stock of every product in the business, by product name.

        Every product appears, including the ones nobody has counted: a stock screen that
        omits them makes a product look new when it is merely uncounted.
        """
        tenant_context.require_permission(
            INVENTORY_READ,
            operation="list_inventory",
            resource_type="inventory",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )
        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            products = await product_crud.list_for_tenant(session, tenant_context.tenant_id)
            stored = {
                inventory.product_id: inventory
                for inventory in await inventory_crud.list_for_tenant(
                    session, tenant_context.tenant_id
                )
            }

        return [
            InventoryLevel(
                product=product,
                inventory=stored.get(product.id)
                or InventoryModel.empty(
                    inventory_id=uuid4(),
                    tenant_id=tenant_context.tenant_id,
                    product_id=product.id,
                    now=now,
                ),
            )
            for product in products
        ]

    async def list_movements(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID | None = None,
        limit: int = DEFAULT_MOVEMENT_LIMIT,
    ) -> list[InventoryMovementModel]:
        """Return stock history, most recent first, for one product or the business."""
        tenant_context.require_permission(
            INVENTORY_READ,
            operation="list_inventory_movements",
            resource_type="inventory",
            resource_id=str(product_id or tenant_context.tenant_id),
            logger=self._logger,
        )
        if limit < 1:
            raise InvalidInputError(
                operation="list_inventory_movements",
                entity="inventory_movement",
                detail="limit must be a positive number of movements",
            )

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            if product_id is None:
                return await inventory_movement_crud.list_for_tenant(
                    session, tenant_context.tenant_id, limit=limit
                )
            await self._require_product(
                session, tenant_context=tenant_context, product_id=product_id
            )
            return await inventory_movement_crud.list_for_product(
                session, tenant_id=tenant_context.tenant_id, product_id=product_id, limit=limit
            )

    # ------------------------------------------------------------------
    # Stock in
    # ------------------------------------------------------------------

    async def receive_stock(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
        quantity: object,
        note: str | None = None,
        reference_type: str | None = None,
        reference_id: UUID | None = None,
    ) -> StockChange:
        """Record stock arriving.

        The quantity is positive by definition: a receipt that takes stock away is a
        different operation, and the movement type says which one happened.
        """
        tenant_context.require_permission(
            INVENTORY_STOCK_IN,
            operation="receive_stock",
            resource_type="product",
            resource_id=str(product_id),
            logger=self._logger,
        )
        delta = _require_positive_quantity(
            quantity, field_name="quantity", operation="receive_stock"
        )

        return await self._apply_movement(
            tenant_context,
            product_id=product_id,
            movement_type=MovementType.STOCK_RECEIVED,
            delta=delta,
            note=note,
            reference_type=reference_type,
            reference_id=reference_id,
        )

    # ------------------------------------------------------------------
    # Corrections
    # ------------------------------------------------------------------

    async def adjust_stock(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
        delta: object,
        reason: str,
        reference_type: str | None = None,
        reference_id: UUID | None = None,
    ) -> StockChange:
        """Record a correction after a count, in either direction.

        A reason is required. An adjustment with no reason is a number that changed and
        nobody knows why, which is exactly the thing a ledger cannot fix afterwards.
        """
        tenant_context.require_permission(
            INVENTORY_ADJUST,
            operation="adjust_stock",
            resource_type="product",
            resource_id=str(product_id),
            logger=self._logger,
        )
        signed_delta = _require_non_zero_quantity(
            delta, field_name="delta", operation="adjust_stock"
        )
        resolved_reason = _require_reason(reason, operation="adjust_stock")

        return await self._apply_movement(
            tenant_context,
            product_id=product_id,
            movement_type=MovementType.ADJUSTMENT,
            delta=signed_delta,
            note=resolved_reason,
            reference_type=reference_type,
            reference_id=reference_id,
        )

    async def record_damage(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
        quantity: object,
        reason: str,
        note: str | None = None,
    ) -> StockChange:
        """Record stock that can no longer be sold.

        Separate from an adjustment because the cause matters: damage is a loss the
        business can often prevent, and a report that cannot tell damage from a miscount
        cannot tell anybody what to fix.
        """
        tenant_context.require_permission(
            INVENTORY_ADJUST,
            operation="record_damage",
            resource_type="product",
            resource_id=str(product_id),
            logger=self._logger,
        )
        damaged = _require_positive_quantity(
            quantity, field_name="quantity", operation="record_damage"
        )
        resolved_reason = _require_reason(reason, operation="record_damage")

        return await self._apply_movement(
            tenant_context,
            product_id=product_id,
            movement_type=MovementType.DAMAGE,
            delta=-damaged,
            note=_join_notes(resolved_reason, note),
        )

    async def transfer_stock(
        self,
        tenant_context: TenantContext,
        *,
        source_product_id: UUID,
        destination_product_id: UUID,
        quantity: object,
        reason: str,
        note: str | None = None,
    ) -> tuple[InventoryModel, InventoryModel]:
        """Move stock from one product record to another, inside one business.

        This is the repackaging case: a shop buys a carton and sells units, and those are
        two product records. Two movements are written, one out of the source and one into
        the destination, in a single transaction - so a crash between them cannot leave the
        stock in neither place.

        Locations do not exist yet; moving stock between a shop and a store would be the
        same operation with a location field, and that arrives with the milestone that adds
        locations.

        Both rows are locked in identifier order. Locking in the order the caller happened
        to pass them is how two simultaneous transfers between the same pair deadlock.
        """
        tenant_context.require_permission(
            INVENTORY_ADJUST,
            operation="transfer_stock",
            resource_type="product",
            resource_id=str(source_product_id),
            logger=self._logger,
        )
        if source_product_id == destination_product_id:
            raise InvalidInputError(
                operation="transfer_stock",
                entity="inventory",
                identifier=str(source_product_id),
                detail="a transfer needs two different products",
            )
        moved = _require_positive_quantity(
            quantity, field_name="quantity", operation="transfer_stock"
        )
        resolved_reason = _require_reason(reason, operation="transfer_stock")
        transfer_note = _join_notes(resolved_reason, note)

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            first_id, second_id = sorted((source_product_id, destination_product_id), key=str)
            await self._require_product(
                session, tenant_context=tenant_context, product_id=source_product_id
            )
            await self._require_product(
                session, tenant_context=tenant_context, product_id=destination_product_id
            )
            policy = await self._tenant_policy(session, tenant_context)

            # Both locks taken in a fixed order, inside one transaction.
            first = await inventory_crud.lock_for_product(
                session,
                inventory_id=uuid4(),
                tenant_id=tenant_context.tenant_id,
                product_id=first_id,
                now=now,
            )
            second = await inventory_crud.lock_for_product(
                session,
                inventory_id=uuid4(),
                tenant_id=tenant_context.tenant_id,
                product_id=second_id,
                now=now,
            )
            locked = {first.product_id: first, second.product_id: second}

            source = locked[source_product_id]
            destination = locked[destination_product_id]
            outgoing = self._build_movement(
                tenant_context,
                product_id=source_product_id,
                movement_type=MovementType.TRANSFER,
                delta=-moved,
                quantity_before=source.quantity_on_hand,
                note=transfer_note,
                now=now,
                reference_type="product_transfer",
                reference_id=destination_product_id,
            )
            incoming = self._build_movement(
                tenant_context,
                product_id=destination_product_id,
                movement_type=MovementType.TRANSFER,
                delta=moved,
                quantity_before=destination.quantity_on_hand,
                note=transfer_note,
                now=now,
                reference_type="product_transfer",
                reference_id=source_product_id,
            )
            self._refuse_overdraw(
                tenant_context, policy=policy, movement=outgoing, product_id=source_product_id
            )

            await inventory_movement_crud.record(session, outgoing)
            await inventory_movement_crud.record(session, incoming)
            stored_source = await inventory_crud.save(
                session, source.with_movement(delta=-moved, at=now)
            )
            stored_destination = await inventory_crud.save(
                session, destination.with_movement(delta=moved, at=now)
            )
            await unit_of_work.commit()

        self._logger.warning(
            "stock_transferred",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            source_product_id=str(source_product_id),
            destination_product_id=str(destination_product_id),
            quantity=str(moved),
            source_quantity_after=str(stored_source.quantity_on_hand),
        )
        return stored_source, stored_destination

    # ------------------------------------------------------------------
    # The one path every movement takes
    # ------------------------------------------------------------------

    async def _apply_movement(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
        movement_type: MovementType,
        delta: Decimal,
        note: str | None = None,
        reference_type: str | None = None,
        reference_id: UUID | None = None,
        device_id: UUID | None = None,
        operation_id: UUID | None = None,
    ) -> StockChange:
        """Apply one movement in a transaction of its own, then report it.

        The transaction belongs to this method because its callers are single stock
        operations - a receipt, an adjustment, damage. A caller that has a transaction
        already, such as a sale being completed, calls `apply_stock_change` with the session
        it is holding instead, so the stock change commits or rolls back with everything else
        rather than beside it.
        """
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            change = await self.apply_stock_change(
                unit_of_work.session_handle,
                tenant_context,
                product_id=product_id,
                movement_type=movement_type,
                delta=delta,
                note=note,
                reference_type=reference_type,
                reference_id=reference_id,
                device_id=device_id,
                operation_id=operation_id,
            )
            await unit_of_work.commit()

        self._log_movement(tenant_context, change)
        return change

    async def apply_stock_change(
        self,
        session: object,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
        movement_type: MovementType,
        delta: Decimal,
        note: str | None = None,
        reference_type: str | None = None,
        reference_id: UUID | None = None,
        device_id: UUID | None = None,
        operation_id: UUID | None = None,
        now: datetime | None = None,
    ) -> StockChange:
        """Apply one movement inside the transaction the caller is holding.

        This is the whole ledger rule in one place: resolve the product in the authorized
        tenant, lock its projection so two concurrent writers serialize, read the business's
        negative-stock policy, build the movement from the locked quantity, refuse the
        write if the policy refuses the result, append the movement and save the projection.

        It does not commit. A sale that has to write a sale, its lines, its payments, its
        stock movements and its ledger entry must commit them together, and a stock change
        that committed on its own would leave half a sale behind.
        """
        resolved_moment = now or datetime.now(UTC)
        await self._require_product(session, tenant_context=tenant_context, product_id=product_id)
        inventory = await inventory_crud.lock_for_product(
            session,  # type: ignore[arg-type]
            inventory_id=uuid4(),
            tenant_id=tenant_context.tenant_id,
            product_id=product_id,
            now=resolved_moment,
        )
        policy = await self._tenant_policy(session, tenant_context)

        movement = self._build_movement(
            tenant_context,
            product_id=product_id,
            movement_type=movement_type,
            delta=delta,
            quantity_before=inventory.quantity_on_hand,
            note=note,
            now=resolved_moment,
            reference_type=reference_type,
            reference_id=reference_id,
            device_id=device_id,
            operation_id=operation_id,
        )
        self._refuse_overdraw(
            tenant_context, policy=policy, movement=movement, product_id=product_id
        )

        await inventory_movement_crud.record(session, movement)  # type: ignore[arg-type]
        updated = await inventory_crud.save(
            session,  # type: ignore[arg-type]
            inventory.with_movement(delta=movement.quantity_delta, at=resolved_moment),
        )
        return StockChange(inventory=updated, movement=movement)

    def _log_movement(self, tenant_context: TenantContext, change: StockChange) -> None:
        """Report a movement at the level its outcome deserves."""
        log_method = self._logger.warning if change.movement.is_overdraw() else self._logger.info
        log_method(
            "inventory_movement_recorded",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            product_id=str(change.movement.product_id),
            movement_id=str(change.movement.id),
            movement_type=change.movement.movement_type.value,
            quantity_delta=str(change.movement.quantity_delta),
            quantity_after=str(change.movement.quantity_after),
            is_overdraw=change.movement.is_overdraw(),
            reference_type=change.movement.reference_type,
        )

    def _build_movement(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
        movement_type: MovementType,
        delta: Decimal,
        quantity_before: Decimal,
        note: str | None,
        now: datetime,
        reference_type: str | None = None,
        reference_id: UUID | None = None,
        device_id: UUID | None = None,
        operation_id: UUID | None = None,
    ) -> InventoryMovementModel:
        """Build a movement, letting the entity reject a delta that does not fit its type."""
        return InventoryMovementModel.record(
            movement_id=uuid4(),
            tenant_id=tenant_context.tenant_id,
            product_id=product_id,
            movement_type=movement_type,
            quantity_delta=delta,
            quantity_before=quantity_before,
            actor_id=tenant_context.user_id,
            now=now,
            reference_type=reference_type,
            reference_id=reference_id,
            device_id=device_id or tenant_context.device_id,
            operation_id=operation_id,
            note=note,
        )

    def _refuse_overdraw(
        self,
        tenant_context: TenantContext,
        *,
        policy: NegativeStockPolicy,
        movement: InventoryMovementModel,
        product_id: UUID,
    ) -> None:
        """Apply the business's rule when a movement would take stock below zero."""
        if not movement.is_overdraw():
            return

        if policy.refuses_the_movement:
            self._logger.warning(
                "inventory_overdraw_refused",
                tenant_id=str(tenant_context.tenant_id),
                actor_id=str(tenant_context.user_id),
                product_id=str(product_id),
                movement_type=movement.movement_type.value,
                quantity_delta=str(movement.quantity_delta),
                quantity_before=str(movement.quantity_before),
                policy=policy.value,
                security_event="negative_stock_refused",
            )
            raise DomainError(
                operation="record_inventory_movement",
                entity="inventory",
                identifier=str(product_id),
                detail=(
                    "this business does not allow stock to go negative: "
                    f"{movement.quantity_before} {movement.quantity_delta} "
                    f"would leave {movement.quantity_after}"
                ),
            )

        if policy.flags_the_movement:
            self._logger.warning(
                "inventory_overdraw_allowed",
                tenant_id=str(tenant_context.tenant_id),
                actor_id=str(tenant_context.user_id),
                product_id=str(product_id),
                quantity_after=str(movement.quantity_after),
                policy=policy.value,
                security_event="negative_stock_allowed",
            )

    # ------------------------------------------------------------------
    # Shared lookups
    # ------------------------------------------------------------------

    async def _require_product(
        self,
        session: object,
        *,
        tenant_context: TenantContext,
        product_id: UUID,
    ) -> ProductModel:
        product = await product_crud.get_by_id(
            session,  # type: ignore[arg-type]
            tenant_id=tenant_context.tenant_id,
            product_id=product_id,
        )
        if product is None:
            self._logger.warning(
                "inventory_access_denied",
                reason="product_not_in_tenant",
                tenant_id=str(tenant_context.tenant_id),
                product_id=str(product_id),
                security_event="tenant_isolation",
            )
            raise NotFoundError(
                operation="fetch_inventory",
                entity="product",
                identifier=str(product_id),
                detail="no product matched in this business",
            )
        return product

    async def _tenant_policy(
        self, session: object, tenant_context: TenantContext
    ) -> NegativeStockPolicy:
        """Return the business's rule about stock going negative.

        Read inside the transaction that holds the product lock, so a policy changed while
        a movement is in flight cannot be applied to half of it.
        """
        tenant = await tenant_crud.require_by_id(
            session,  # type: ignore[arg-type]
            tenant_context.tenant_id,
        )
        return tenant.negative_stock_policy


# ---------------------------------------------------------------------------
# Input narrowing
# ---------------------------------------------------------------------------


def _require_positive_quantity(value: object, *, field_name: str, operation: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise InvalidInputError(
            operation=operation,
            entity="inventory",
            detail=f"{field_name} must be a decimal quantity",
        )
    if value <= ZERO_QUANTITY:
        raise InvalidInputError(
            operation=operation,
            entity="inventory",
            detail=f"{field_name} must be greater than zero",
        )
    return value


def _require_non_zero_quantity(value: object, *, field_name: str, operation: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise InvalidInputError(
            operation=operation,
            entity="inventory",
            detail=f"{field_name} must be a decimal quantity",
        )
    if value == ZERO_QUANTITY:
        raise InvalidInputError(
            operation=operation,
            entity="inventory",
            detail=f"{field_name} must not be zero: a movement that changes nothing is not one",
        )
    return value


def _require_reason(reason: object, *, operation: str) -> str:
    if not isinstance(reason, str) or not reason.strip():
        raise InvalidInputError(
            operation=operation,
            entity="inventory_movement",
            detail="a reason is required: the ledger is the only place this is recorded",
        )
    return reason.strip()


def _join_notes(reason: str, note: str | None) -> str:
    if note is None or not note.strip():
        return reason
    return f"{reason}: {note.strip()}"
