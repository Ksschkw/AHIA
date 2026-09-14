"""Sale use cases: completing a sale, and cancelling one.

**Everything a sale touches is written in one transaction, or none of it is.**

    receipt number   claimed from the business's counter, under a row lock
    sale             with its totals derived from the lines
    sale items       with the product's name and price snapshotted
    payments         the money actually taken
    stock movements  one per line, with the projection updated and the policy applied
    ledger entries   revenue, and the discount when there is one

A sale that was recorded while its stock movement silently failed is the failure this
milestone exists to prevent: the books would say the goods left and the shelf would say
they did not. Every write above happens inside one unit of work, so an injected failure
anywhere rolls back all of it - and the stock rules are applied by the inventory service
through `apply_stock_change`, which takes the session this service is holding rather than
opening a transaction of its own.

**A sale that arrives twice produces one sale.** Offline clients replay operations, and a
basket sent twice must not be sold twice. The `operation_id` is checked first, inside the
transaction, and a replay returns the sale that was already recorded - marked as replayed so
a caller can tell the difference. The unique index behind it is what makes that a guarantee
rather than a hope.

**Cancelling reverses the facts; it does not delete them.** The stock comes back as a return
movement, the payments are marked refunded, the ledger records a refund, and the sale keeps
its number, its lines and its total. The money and the goods both moved, twice, and both
movements are on the record.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.errors import DomainError, InvalidInputError, NotFoundError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions.sales_permissions import SALES_CANCEL, SALES_CREATE, SALES_READ
from ahia.core.tenant_context import TenantContext
from ahia.crud import (
    ledger_entry_crud,
    payment_crud,
    product_crud,
    receipt_counter_crud,
    sale_crud,
    sale_item_crud,
    tenant_crud,
)
from ahia.models.entities.inventory_movement_model import MovementType
from ahia.models.entities.ledger_entry_model import LedgerEntryModel, LedgerEntryType
from ahia.models.entities.money import ZERO_MONEY, quantise_money
from ahia.models.entities.payment_model import PaymentMethod, PaymentModel
from ahia.models.entities.product_model import ProductModel
from ahia.models.entities.sale_item_model import SaleItemModel
from ahia.models.entities.sale_model import SaleModel, SaleStatus
from ahia.services.inventory_service import InventoryService

_SALES_LOGGER_NAME: Final[str] = "ahia.services.sales"

#: The vocabulary a ledger entry uses to point at the sale that caused it.
SALE_REFERENCE_TYPE: Final[str] = "sale"

#: What a sales report reads. Named here rather than repeated at four call sites.
SALE_RETURN_NOTE: Final[str] = "sale cancelled"


@dataclass(frozen=True, slots=True)
class SaleLineRequest:
    """One thing being sold: a product, a quantity, and optionally a price and a discount.

    The price is optional because the usual case is the product's current selling price, and
    requiring a caller to send it would invite a client to invent one. When it is supplied it
    is what is charged, and it is snapshotted - a negotiated price is a real thing in a shop.
    """

    product_id: UUID
    quantity: Decimal
    unit_price: Decimal | None = None
    discount_amount: Decimal = ZERO_MONEY


@dataclass(frozen=True, slots=True)
class PaymentRequest:
    """Money being taken for the sale."""

    amount: Decimal
    method: PaymentMethod = PaymentMethod.CASH
    reference: str | None = None


@dataclass(frozen=True, slots=True)
class SaleResult:
    """What completing a sale produced.

    `was_replayed` is True when the operation had already been recorded: the sale returned is
    the original one, nothing was written, and a caller that shows a receipt can show the
    same receipt again rather than a second one.
    """

    sale: SaleModel
    items: list[SaleItemModel] = field(default_factory=list)
    payments: list[PaymentModel] = field(default_factory=list)
    was_replayed: bool = False


class SalesService:
    """Sale use cases."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        inventory_service: InventoryService,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._inventory = inventory_service
        self._logger = (logger or get_logger(_SALES_LOGGER_NAME)).bind(
            component="sale_service", layer="service"
        )

    # ------------------------------------------------------------------
    # Completing a sale
    # ------------------------------------------------------------------

    async def complete_sale(
        self,
        tenant_context: TenantContext,
        *,
        lines: Sequence[SaleLineRequest],
        payments: Sequence[PaymentRequest],
        customer_id: UUID | None = None,
        discount_amount: Decimal = ZERO_MONEY,
        operation_id: UUID | None = None,
        occurred_at: datetime | None = None,
    ) -> SaleResult:
        """Record a sale: its lines, its payments, the stock it moved and its ledger entry."""
        tenant_context.require_permission(
            SALES_CREATE,
            operation="complete_sale",
            resource_type="sale",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )
        if not lines:
            raise InvalidInputError(
                operation="complete_sale",
                entity="sale",
                detail="a sale needs at least one line",
            )

        now = occurred_at or datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle

            replay = await self._find_replay(
                session, tenant_context=tenant_context, operation_id=operation_id
            )
            if replay is not None:
                return replay

            products = await self._load_products(
                session, tenant_context=tenant_context, lines=lines
            )
            # The sale's identifier is chosen before its lines, because a line already names
            # the sale it belongs to - and the totals are derived from those lines, so the
            # order is: identify, build lines, total, issue.
            sale_id = uuid4()
            items = self._build_items(
                tenant_context,
                sale_id=sale_id,
                lines=lines,
                products=products,
                now=now,
            )
            subtotal = quantise_money(sum((item.line_total for item in items), ZERO_MONEY))
            sale = SaleModel.issue(
                sale_id=sale_id,
                tenant_id=tenant_context.tenant_id,
                receipt_number=await receipt_counter_crud.allocate_receipt_number(
                    session,
                    tenant_id=tenant_context.tenant_id,
                    prefix=await self._receipt_prefix(session, tenant_context),
                    now=now,
                ),
                seller_id=tenant_context.user_id,
                subtotal=subtotal,
                discount_amount=discount_amount,
                customer_id=customer_id,
                device_id=tenant_context.device_id,
                operation_id=operation_id,
                now=now,
            )
            taken = self._sum_payments(payments)
            self._refuse_overpayment(taken=taken, total=sale.total_amount)
            sale = sale.with_payment_status_for(amount_paid=taken, at=now)

            await sale_crud.create(session, sale)
            for item in items:
                await sale_item_crud.create(session, item)

            stored_payments = await self._record_payments(
                tenant_context, session=session, sale=sale, payments=payments, now=now
            )
            await self._move_stock(
                session, tenant_context=tenant_context, sale=sale, items=items, now=now
            )
            await self._write_ledger(session, tenant_context=tenant_context, sale=sale, now=now)
            await unit_of_work.commit()

        self._logger.info(
            "sale_completed",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            sale_id=str(sale.id),
            receipt_number=sale.receipt_number,
            line_count=len(items),
            total_amount=str(sale.total_amount),
            amount_paid=str(taken),
            payment_status=sale.payment_status.value,
            has_customer=customer_id is not None,
        )
        return SaleResult(sale=sale, items=list(items), payments=stored_payments)

    async def _find_replay(
        self,
        session: object,
        *,
        tenant_context: TenantContext,
        operation_id: UUID | None,
    ) -> SaleResult | None:
        """Return the sale this operation already produced, or None.

        Checked before anything is written, so a replayed basket costs one indexed read
        rather than a failed insert. The unique index is still the guarantee: two simultaneous
        replays cannot both pass this check and both write.
        """
        if operation_id is None:
            return None
        existing = await sale_crud.get_by_operation_id(
            session,  # type: ignore[arg-type]
            tenant_id=tenant_context.tenant_id,
            operation_id=operation_id,
        )
        if existing is None:
            return None

        self._logger.info(
            "sale_replayed",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            sale_id=str(existing.id),
            receipt_number=existing.receipt_number,
            operation_id=str(operation_id),
        )
        return SaleResult(
            sale=existing,
            items=await sale_item_crud.list_for_sale(
                session,  # type: ignore[arg-type]
                tenant_id=tenant_context.tenant_id,
                sale_id=existing.id,
            ),
            payments=await payment_crud.list_for_sale(
                session,  # type: ignore[arg-type]
                tenant_id=tenant_context.tenant_id,
                sale_id=existing.id,
            ),
            was_replayed=True,
        )

    async def _load_products(
        self,
        session: object,
        *,
        tenant_context: TenantContext,
        lines: Sequence[SaleLineRequest],
    ) -> dict[UUID, ProductModel]:
        """Load every product the sale names, once each, and refuse what cannot be sold."""
        products: dict[UUID, ProductModel] = {}
        for line in lines:
            if line.product_id in products:
                continue
            product = await product_crud.get_by_id(
                session,  # type: ignore[arg-type]
                tenant_id=tenant_context.tenant_id,
                product_id=line.product_id,
            )
            if product is None:
                self._logger.warning(
                    "sale_line_product_refused",
                    reason="product_not_in_tenant",
                    tenant_id=str(tenant_context.tenant_id),
                    product_id=str(line.product_id),
                    security_event="tenant_isolation",
                )
                raise NotFoundError(
                    operation="complete_sale",
                    entity="product",
                    identifier=str(line.product_id),
                    detail="no product matched in this business",
                )
            if not product.is_active:
                # Selling something the business has withdrawn is a mistake at the till, and
                # the receipt would be for goods the shop says it does not sell.
                raise DomainError(
                    operation="complete_sale",
                    entity="product",
                    identifier=str(product.id),
                    detail="this product is not active and cannot be sold",
                )
            products[line.product_id] = product
        return products

    def _build_items(
        self,
        tenant_context: TenantContext,
        *,
        sale_id: UUID,
        lines: Sequence[SaleLineRequest],
        products: dict[UUID, ProductModel],
        now: datetime,
    ) -> list[SaleItemModel]:
        """Build the lines, snapshotting each product's name and the price being charged."""
        items: list[SaleItemModel] = []
        for line in lines:
            product = products[line.product_id]
            items.append(
                SaleItemModel.for_product(
                    item_id=uuid4(),
                    tenant_id=tenant_context.tenant_id,
                    sale_id=sale_id,
                    product_id=product.id,
                    product_name=product.name,
                    unit_price=line.unit_price or product.selling_price,
                    quantity=line.quantity,
                    discount_amount=line.discount_amount,
                    now=now,
                )
            )
        return items

    @staticmethod
    def _sum_payments(payments: Sequence[PaymentRequest]) -> Decimal:
        return quantise_money(sum((payment.amount for payment in payments), ZERO_MONEY))

    def _refuse_overpayment(self, *, taken: Decimal, total: Decimal) -> None:
        """Refuse a payment larger than the sale.

        Change handed back is not a payment: recording 1000 against a 900 sale would say the
        business took 1000, and every cash report would be wrong by the change. A caller that
        wants to record a deposit records the deposit.
        """
        if taken > total:
            raise InvalidInputError(
                operation="complete_sale",
                entity="sale",
                detail=(
                    "the payments exceed the sale total; change given is not a payment: "
                    f"{taken} > {total}"
                ),
            )

    async def _receipt_prefix(self, session: object, tenant_context: TenantContext) -> str:
        """Return the prefix this business's receipts carry.

        Taken from the business's own slug, so a receipt number is recognisable at a glance,
        and read from the tenant row rather than from the context because a context carries
        identifiers and not names.
        """
        tenant = await tenant_crud.require_by_id(
            session,  # type: ignore[arg-type]
            tenant_context.tenant_id,
        )
        return tenant.slug

    async def _record_payments(
        self,
        tenant_context: TenantContext,
        *,
        session: object,
        sale: SaleModel,
        payments: Sequence[PaymentRequest],
        now: datetime,
    ) -> list[PaymentModel]:
        stored: list[PaymentModel] = []
        for request in payments:
            payment = PaymentModel.received(
                payment_id=uuid4(),
                tenant_id=tenant_context.tenant_id,
                sale_id=sale.id,
                amount=request.amount,
                method=request.method,
                reference=request.reference,
                now=now,
            )
            stored.append(await payment_crud.create(session, payment))  # type: ignore[arg-type]
        return stored

    async def _move_stock(
        self,
        session: object,
        *,
        tenant_context: TenantContext,
        sale: SaleModel,
        items: Sequence[SaleItemModel],
        now: datetime,
    ) -> None:
        """Take the sold quantity out of stock, through the inventory service's rules.

        The inventory service is handed this transaction's session rather than opening its
        own, so a sale whose third line cannot be fulfilled rolls back its first two lines as
        well as the sale itself.
        """
        for item in items:
            await self._inventory.apply_stock_change(
                session,
                tenant_context,
                product_id=item.product_id,
                movement_type=MovementType.SALE,
                delta=-item.quantity,
                reference_type=SALE_REFERENCE_TYPE,
                reference_id=sale.id,
                now=now,
            )

    async def _write_ledger(
        self,
        session: object,
        *,
        tenant_context: TenantContext,
        sale: SaleModel,
        now: datetime,
    ) -> None:
        """Record the revenue the sale earned, and the discount it gave.

        Two entries rather than one net figure: a report that cannot see the discount cannot
        answer "what did we give away this month", and the discount is money the business
        chose not to take.
        """
        await ledger_entry_crud.record(
            session,  # type: ignore[arg-type]
            LedgerEntryModel.record(
                entry_id=uuid4(),
                tenant_id=tenant_context.tenant_id,
                entry_type=LedgerEntryType.SALE_REVENUE,
                amount=sale.subtotal,
                reference_type=SALE_REFERENCE_TYPE,
                reference_id=sale.id,
                now=now,
            ),
        )
        if sale.discount_amount > ZERO_MONEY:
            await ledger_entry_crud.record(
                session,  # type: ignore[arg-type]
                LedgerEntryModel.record(
                    entry_id=uuid4(),
                    tenant_id=tenant_context.tenant_id,
                    entry_type=LedgerEntryType.SALE_DISCOUNT,
                    amount=sale.discount_amount,
                    reference_type=SALE_REFERENCE_TYPE,
                    reference_id=sale.id,
                    now=now,
                ),
            )

    # ------------------------------------------------------------------
    # Cancelling a sale
    # ------------------------------------------------------------------

    async def cancel_sale(
        self,
        tenant_context: TenantContext,
        *,
        sale_id: UUID,
        reason: str,
    ) -> SaleResult:
        """Cancel a sale, returning the stock and the money.

        The sale is not deleted and its lines are not touched. What changes is that the stock
        comes back as a return movement, each payment is marked refunded, the ledger records
        a refund, and the sale carries a status, a timestamp and a reason - because the money
        and the goods both moved, and now they have both moved back.
        """
        tenant_context.require_permission(
            SALES_CANCEL,
            operation="cancel_sale",
            resource_type="sale",
            resource_id=str(sale_id),
            logger=self._logger,
        )
        resolved_reason = _require_reason(reason)

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            sale = await self._require_sale(session, tenant_context=tenant_context, sale_id=sale_id)
            items = await sale_item_crud.list_for_sale(
                session, tenant_id=tenant_context.tenant_id, sale_id=sale.id
            )
            payments = await payment_crud.list_for_sale(
                session, tenant_id=tenant_context.tenant_id, sale_id=sale.id
            )

            if sale.status is SaleStatus.CANCELLED:
                # Idempotent: the first cancellation is the one that moved the stock and the
                # money, so a second must not move them again.
                return SaleResult(sale=sale, items=items, payments=payments)

            for item in items:
                await self._inventory.apply_stock_change(
                    session,
                    tenant_context,
                    product_id=item.product_id,
                    movement_type=MovementType.RETURN,
                    delta=item.quantity,
                    note=resolved_reason,
                    reference_type=SALE_REFERENCE_TYPE,
                    reference_id=sale.id,
                    now=now,
                )

            refunded: list[PaymentModel] = []
            for payment in payments:
                if payment.is_refunded():
                    refunded.append(payment)
                    continue
                refunded.append(await payment_crud.update(session, payment.refunded(at=now)))

            if sale.total_amount > ZERO_MONEY:
                await ledger_entry_crud.record(
                    session,
                    LedgerEntryModel.record(
                        entry_id=uuid4(),
                        tenant_id=tenant_context.tenant_id,
                        entry_type=LedgerEntryType.REFUND,
                        amount=sale.total_amount,
                        reference_type=SALE_REFERENCE_TYPE,
                        reference_id=sale.id,
                        now=now,
                    ),
                )

            cancelled = await sale_crud.update(
                session,
                sale.cancelled(at=now, reason=resolved_reason).with_payment_status_for(
                    amount_paid=ZERO_MONEY, at=now
                ),
            )
            await unit_of_work.commit()

        self._logger.warning(
            "sale_cancelled",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            sale_id=str(cancelled.id),
            receipt_number=cancelled.receipt_number,
            refunded_payments=len(refunded),
            restocked_lines=len(items),
            security_event="sale_cancelled",
        )
        return SaleResult(sale=cancelled, items=items, payments=refunded)

    async def _require_sale(
        self,
        session: object,
        *,
        tenant_context: TenantContext,
        sale_id: UUID,
    ) -> SaleModel:
        sale = await sale_crud.get_by_id(
            session,  # type: ignore[arg-type]
            tenant_id=tenant_context.tenant_id,
            sale_id=sale_id,
        )
        if sale is None:
            self._logger.warning(
                "sale_access_denied",
                reason="sale_not_in_tenant",
                tenant_id=str(tenant_context.tenant_id),
                sale_id=str(sale_id),
                security_event="tenant_isolation",
            )
            raise NotFoundError(
                operation="cancel_sale",
                entity="sale",
                identifier=str(sale_id),
                detail="no sale matched in this business",
            )
        return sale

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    async def get_sale(
        self,
        tenant_context: TenantContext,
        *,
        sale_id: UUID,
    ) -> SaleResult:
        """Return one sale with its lines and payments."""
        tenant_context.require_permission(
            SALES_READ,
            operation="get_sale",
            resource_type="sale",
            resource_id=str(sale_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            sale = await self._require_sale(session, tenant_context=tenant_context, sale_id=sale_id)
            return SaleResult(
                sale=sale,
                items=await sale_item_crud.list_for_sale(
                    session, tenant_id=tenant_context.tenant_id, sale_id=sale.id
                ),
                payments=await payment_crud.list_for_sale(
                    session, tenant_id=tenant_context.tenant_id, sale_id=sale.id
                ),
            )

    async def list_sales(
        self,
        tenant_context: TenantContext,
        *,
        limit: int = 100,
    ) -> list[SaleModel]:
        """Return the business's sales, most recent first."""
        tenant_context.require_permission(
            SALES_READ,
            operation="list_sales",
            resource_type="sale",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await sale_crud.list_for_tenant(
                unit_of_work.session_handle, tenant_context.tenant_id, limit=limit
            )


def _require_reason(reason: object) -> str:
    if not isinstance(reason, str) or not reason.strip():
        raise InvalidInputError(
            operation="cancel_sale",
            entity="sale",
            detail="a reason is required: the ledger is the only place this is recorded",
        )
    return reason.strip()
