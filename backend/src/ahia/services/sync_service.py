"""Offline synchronization: what a device pushes, and what it is owed.

Named after the use case rather than an entity, because it spans three of them - the operation
record, the device cursor and the change feed - and coordinating them is exactly what this file
does. It is the same exception `auth_service` and `iam_seed_service` take: an operation that
belongs to no single table is named after the operation.

**A pushed operation is executed by the use case that owns it, never by this service.** A sale
arrives as `complete_sale` and is handed to `SalesService`, which checks the permission, prices
the lines, moves the stock, writes the ledger entry and writes its audit event. This file decides
which use case an operation means and what to tell the client afterwards. A second implementation
of selling, written for offline clients, would be a second place for the arithmetic to be wrong -
and the offline one would be the one nobody tested.

**Idempotency is checked before the use case runs, and enforced by it as well.** The operation
identifier is looked up in `sync_operations`; if it is there, the first attempt's answer is
returned and nothing executes. If two retries arrive at the same moment, the use cases' own
uniqueness - `sales.operation_id`, `expenses.operation_id` - is what keeps the business fact from
happening twice, and the second `sync_operations` insert is answered from the first. Two
mechanisms, because they answer different questions: this one answers a retry cheaply and without
knowing which use case it was, and the use cases' own constraints hold even when an operation
arrives through another route.

**One bad operation does not fail the batch.** A phone that has been offline for a day pushes a
queue, and a permission it no longer holds or a payload the server now refuses must not throw away
the sales behind it. Each operation gets its own answer: applied, replayed, conflicted, or
rejected with a reason. What a device does with a rejected operation is its business; what this
service guarantees is that it is told, once per operation, in order.

**Conflict classification follows the specification's matrix.** A transactional fact - a sale, an
expense, a stock movement - is operation-based: it is an event that already happened, and two
devices recording two different sales is not a conflict, it is a busy afternoon. A metadata field
is safe to overwrite, which is what a customer edit does when the client sends no version. A
high-value field gets an explicit conflict: `update_customer` carrying a version the server has
moved past is answered with `CONFLICT` and the version the server holds, so the client merges and
retries rather than one of the two edits disappearing.

**Pulling is a cursor and a page.** `pull_changes` returns the changes this caller may read, the
latest sequence in the business, and whether more remain. It does not advance the cursor: the
client says how far it got, because a device that applied half a page and died must not be told it
is further along than it is. `advance_cursor` records a position, only ever forward, and the
device identifier comes from the authenticated context so a client cannot move another phone's
cursor.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.errors import AhiaError, ConflictError, InvalidInputError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.tenant_context import TenantContext
from ahia.crud import sync_cursor_crud, sync_operation_crud
from ahia.models.entities.expense_category import ExpenseCategory
from ahia.models.entities.payment_model import PaymentMethod
from ahia.models.entities.sync_cursor_model import SyncCursorModel
from ahia.models.entities.sync_operation_model import (
    SyncOperationModel,
    SyncOperationStatus,
)
from ahia.services.customer_service import CustomerService
from ahia.services.expense_service import ExpenseService
from ahia.services.inventory_service import InventoryService
from ahia.services.sale_service import PaymentRequest, SaleLineRequest, SalesService
from ahia.services.sync_change_service import ChangePage, SyncChangeService

_SYNC_LOGGER_NAME: Final[str] = "ahia.services.sync"

#: How a repeat of an operation is reconciled. `OPERATION_BASED` means the operation is an event
#: that already happened, so a second arrival of the *same* identifier is a retry and a different
#: identifier is a different event; `VERSIONED` means the payload edits a record the server may
#: also have edited, so the client states the version it was working from.
OPERATION_BASED: Final[str] = "OPERATION_BASED"
VERSIONED: Final[str] = "VERSIONED"

CONFLICT_POLICY_FOR_OPERATION: Final[dict[str, str]] = {
    "complete_sale": OPERATION_BASED,
    "record_expense": OPERATION_BASED,
    "create_customer": OPERATION_BASED,
    "receive_stock": OPERATION_BASED,
    "adjust_stock": OPERATION_BASED,
    "update_customer": VERSIONED,
}

SUPPORTED_OPERATION_TYPES: Final[frozenset[str]] = frozenset(CONFLICT_POLICY_FOR_OPERATION)

#: The keys an `update_customer` payload uses for addressing rather than for editing. They are
#: removed before the rest is handed to the use case as the change map.
_CUSTOMER_ADDRESSING_KEYS: Final[frozenset[str]] = frozenset({"customer_id", "expected_version"})


@dataclass(frozen=True, slots=True)
class SyncOperationRequest:
    """One operation as it arrived, already validated at the edge.

    The payload stays a mapping rather than a typed object because the schema layer is where the
    wire shape is validated, and this service has no business importing a transport contract. What
    it does with the mapping is translation: the keys it reads are the ones the contract promises
    for that operation type, and the values have already been checked once.
    """

    operation_id: UUID
    operation_type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SyncOperationResult:
    """What happened to one operation, in the terms a device can act on."""

    operation_id: UUID
    operation_type: str
    status: SyncOperationStatus
    entity_type: str | None = None
    entity_id: UUID | None = None
    detail: dict[str, str] = field(default_factory=dict)

    @property
    def was_applied(self) -> bool:
        return self.status is SyncOperationStatus.APPLIED

    @property
    def needs_the_clients_attention(self) -> bool:
        """Return True when a human or the client has to do something with this answer."""
        return self.status in {
            SyncOperationStatus.CONFLICT,
            SyncOperationStatus.REJECTED,
        }


@dataclass(frozen=True, slots=True)
class PushResult:
    """Every operation's outcome, in the order they were pushed."""

    results: list[SyncOperationResult]

    @property
    def applied_count(self) -> int:
        return sum(1 for result in self.results if result.status is SyncOperationStatus.APPLIED)

    @property
    def replayed_count(self) -> int:
        return sum(1 for result in self.results if result.status is SyncOperationStatus.REPLAYED)

    @property
    def needs_the_clients_attention(self) -> list[SyncOperationResult]:
        return [result for result in self.results if result.needs_the_clients_attention]


class SyncService:
    """Offline synchronization use cases: push, pull, and the cursor between them."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        sales_service: SalesService,
        expense_service: ExpenseService,
        customer_service: CustomerService,
        inventory_service: InventoryService,
        sync_change_service: SyncChangeService,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._sales = sales_service
        self._expenses = expense_service
        self._customers = customer_service
        self._inventory = inventory_service
        self._changes = sync_change_service
        self._logger = (logger or get_logger(_SYNC_LOGGER_NAME)).bind(
            component="sync_service", layer="service"
        )

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------

    async def push_operations(
        self,
        tenant_context: TenantContext,
        *,
        operations: Sequence[SyncOperationRequest],
    ) -> PushResult:
        """Apply a queue of operations, one answer each.

        No permission is checked here. Each operation is dispatched to the use case that owns it,
        and that use case checks the permission it needs - the same check an online request gets,
        and the reason an offline client cannot reach anything a phone could not reach directly.
        """
        results: list[SyncOperationResult] = []
        for operation in operations:
            results.append(await self._apply_one(tenant_context, operation=operation))
        return PushResult(results=results)

    async def _apply_one(
        self,
        tenant_context: TenantContext,
        *,
        operation: SyncOperationRequest,
    ) -> SyncOperationResult:
        already_recorded = await self._find_recorded(tenant_context, operation.operation_id)
        if already_recorded is not None:
            # The record's own description already carries the tenant and the operation's
            # identifiers; passing the tenant again as well is a duplicate keyword, which is how
            # this line first failed - on the replay path, the one an offline device depends on.
            self._logger.info(
                "sync_operation_replayed",
                actor_id=str(tenant_context.user_id),
                **already_recorded.describe_for_audit(),
            )
            # The stored status is the *first* attempt's outcome and never changes. What this
            # arrival did is a replay, and saying so is the difference between a client that can
            # tell "I just sold this" from "I already sold this" - so the result is built here
            # rather than copied from the record.
            return SyncOperationResult(
                operation_id=already_recorded.id,
                operation_type=already_recorded.operation_type,
                status=SyncOperationStatus.REPLAYED,
                entity_type=already_recorded.entity_type,
                entity_id=already_recorded.entity_id,
                detail=dict(already_recorded.detail or {}),
            )

        if operation.operation_type not in SUPPORTED_OPERATION_TYPES:
            return await self._record_answer(
                tenant_context,
                operation=operation,
                status=SyncOperationStatus.REJECTED,
                detail={"reason": "unsupported_operation_type"},
            )

        try:
            outcome = await self._dispatch(tenant_context, operation=operation)
        except _StaleVersionError as conflict:
            self._logger.warning(
                "sync_operation_conflicted",
                tenant_id=str(tenant_context.tenant_id),
                actor_id=str(tenant_context.user_id),
                operation_id=str(operation.operation_id),
                operation_type=operation.operation_type,
                server_version=str(conflict.server_version),
                security_event="sync_operation_conflicted",
            )
            return await self._record_answer(
                tenant_context,
                operation=operation,
                status=SyncOperationStatus.CONFLICT,
                entity_type="customer",
                detail={
                    "reason": "stale_version",
                    "server_version": str(conflict.server_version),
                },
            )
        except AhiaError as refused:
            self._logger.warning(
                "sync_operation_refused",
                tenant_id=str(tenant_context.tenant_id),
                actor_id=str(tenant_context.user_id),
                operation_id=str(operation.operation_id),
                operation_type=operation.operation_type,
                reason=refused.error_code,
                security_event="sync_operation_refused",
            )
            return await self._record_answer(
                tenant_context,
                operation=operation,
                status=SyncOperationStatus.REJECTED,
                detail={"reason": refused.error_code.lower()},
            )

        stored = await self._record_answer(
            tenant_context,
            operation=operation,
            status=SyncOperationStatus.APPLIED,
            entity_type=outcome.entity_type,
            entity_id=outcome.entity_id,
            detail=outcome.detail,
        )
        self._logger.info(
            "sync_operation_applied",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            operation_id=str(operation.operation_id),
            operation_type=operation.operation_type,
            entity_type=outcome.entity_type,
            entity_id=str(outcome.entity_id) if outcome.entity_id else "",
        )
        return stored

    async def _dispatch(
        self,
        tenant_context: TenantContext,
        *,
        operation: SyncOperationRequest,
    ) -> _Outcome:
        """Hand one operation to the use case that owns it.

        A declared dispatch rather than a table of callables, because each operation needs a
        different translation from payload to use-case arguments and a uniform signature would
        hide that behind something that lies about it.
        """
        handlers: dict[str, Callable[[], Any]] = {
            "complete_sale": lambda: self._push_sale(tenant_context, operation=operation),
            "record_expense": lambda: self._push_expense(tenant_context, operation=operation),
            "create_customer": lambda: self._push_customer(tenant_context, operation=operation),
            "update_customer": lambda: self._push_customer_edit(
                tenant_context, operation=operation
            ),
            "receive_stock": lambda: self._push_stock_receipt(tenant_context, operation=operation),
            "adjust_stock": lambda: self._push_stock_adjustment(
                tenant_context, operation=operation
            ),
        }
        handler = handlers.get(operation.operation_type)
        if handler is None:
            # Unreachable through `push_operations`, which checks the supported set first. It
            # exists so adding an operation type to the policy map without a handler fails loudly
            # here rather than silently applying nothing.
            raise InvalidInputError(
                operation="push_operations",
                entity="sync_operation",
                identifier=str(operation.operation_id),
                detail=f"no handler for {operation.operation_type!r}",
            )
        outcome: _Outcome = await handler()
        return outcome

    async def _push_sale(
        self, tenant_context: TenantContext, *, operation: SyncOperationRequest
    ) -> _Outcome:
        payload = operation.payload
        result = await self._sales.complete_sale(
            tenant_context,
            lines=[
                SaleLineRequest(
                    product_id=_uuid(line, "product_id"),
                    quantity=_decimal(line, "quantity"),
                    unit_price=_optional_decimal(line, "unit_price"),
                    discount_amount=_optional_decimal(line, "discount_amount") or Decimal("0.00"),
                )
                for line in _records(payload, "lines", required=True)
            ],
            payments=[
                PaymentRequest(
                    amount=_decimal(payment, "amount"),
                    method=(
                        PaymentMethod(_text(payment, "method"))
                        if payment.get("method") is not None
                        else PaymentMethod.CASH
                    ),
                    reference=_optional_text(payment, "reference"),
                )
                for payment in _records(payload, "payments", required=False)
            ],
            customer_id=_optional_uuid(payload, "customer_id"),
            operation_id=operation.operation_id,
        )
        return _Outcome(
            entity_type="sale",
            entity_id=result.sale.id,
            detail={"receipt_number": result.sale.receipt_number},
        )

    async def _push_expense(
        self, tenant_context: TenantContext, *, operation: SyncOperationRequest
    ) -> _Outcome:
        payload = operation.payload
        recorded = await self._expenses.record_expense(
            tenant_context,
            category=ExpenseCategory(_text(payload, "category")),
            amount=_decimal(payload, "amount"),
            payment_method=(
                PaymentMethod(_text(payload, "payment_method"))
                if payload.get("payment_method") is not None
                else PaymentMethod.CASH
            ),
            description=_optional_text(payload, "description"),
            operation_id=operation.operation_id,
        )
        return _Outcome(
            entity_type="expense",
            entity_id=recorded.expense.id,
            detail={"category": recorded.expense.category.value},
        )

    async def _push_customer(
        self, tenant_context: TenantContext, *, operation: SyncOperationRequest
    ) -> _Outcome:
        payload = operation.payload
        creation = await self._customers.create_customer(
            tenant_context,
            name=_text(payload, "name"),
            phone=_optional_text(payload, "phone"),
            email=_optional_text(payload, "email"),
            address=_optional_text(payload, "address"),
            notes=_optional_text(payload, "notes"),
        )
        detail = {"version": str(creation.customer.version)}
        if creation.possible_duplicate_of is not None:
            # Reported rather than refused, exactly as it is online: the person at the counter
            # decides whether a shared phone number is the same customer.
            detail["possible_duplicate_of"] = str(creation.possible_duplicate_of)
        return _Outcome(
            entity_type="customer",
            entity_id=creation.customer.id,
            detail=detail,
            server_version=creation.customer.version,
        )

    async def _push_customer_edit(
        self, tenant_context: TenantContext, *, operation: SyncOperationRequest
    ) -> _Outcome:
        """Apply a versioned customer edit, or answer with the version the server holds."""
        payload = operation.payload
        expected_version = int(_decimal(payload, "expected_version"))
        customer_id = _uuid(payload, "customer_id")
        changes = {
            key: value for key, value in payload.items() if key not in _CUSTOMER_ADDRESSING_KEYS
        }
        try:
            customer = await self._customers.update_customer(
                tenant_context,
                customer_id=customer_id,
                changes=changes,
                expected_version=expected_version,
            )
        except ConflictError as stale:
            current = await self._customers.get_customer(tenant_context, customer_id=customer_id)
            raise _StaleVersionError(
                operation="update_customer",
                entity="customer",
                identifier=str(customer_id),
                detail=f"expected version {expected_version}, server holds {current.version}",
                server_version=current.version,
            ) from stale
        return _Outcome(
            entity_type="customer",
            entity_id=customer.id,
            detail={"version": str(customer.version)},
            server_version=customer.version,
        )

    async def _push_stock_receipt(
        self, tenant_context: TenantContext, *, operation: SyncOperationRequest
    ) -> _Outcome:
        payload = operation.payload
        change = await self._inventory.receive_stock(
            tenant_context,
            product_id=_uuid(payload, "product_id"),
            quantity=_decimal(payload, "quantity"),
            note=_optional_text(payload, "note"),
            reference_type="sync_operation",
            reference_id=operation.operation_id,
        )
        return _Outcome(
            entity_type="inventory_movement",
            entity_id=change.movement.id,
            detail={"quantity_after": str(change.inventory.quantity_on_hand)},
        )

    async def _push_stock_adjustment(
        self, tenant_context: TenantContext, *, operation: SyncOperationRequest
    ) -> _Outcome:
        payload = operation.payload
        change = await self._inventory.adjust_stock(
            tenant_context,
            product_id=_uuid(payload, "product_id"),
            delta=_decimal(payload, "delta"),
            reason=_text(payload, "reason"),
            reference_type="sync_operation",
            reference_id=operation.operation_id,
        )
        return _Outcome(
            entity_type="inventory_movement",
            entity_id=change.movement.id,
            detail={"quantity_after": str(change.inventory.quantity_on_hand)},
        )

    # ------------------------------------------------------------------
    # Recording the answers
    # ------------------------------------------------------------------

    async def _find_recorded(
        self, tenant_context: TenantContext, operation_id: UUID
    ) -> SyncOperationModel | None:
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await sync_operation_crud.get_by_id(
                unit_of_work.session_handle,
                tenant_id=tenant_context.tenant_id,
                operation_id=operation_id,
            )

    async def _record_answer(
        self,
        tenant_context: TenantContext,
        *,
        operation: SyncOperationRequest,
        status: SyncOperationStatus,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        detail: dict[str, str] | None = None,
    ) -> SyncOperationResult:
        record = SyncOperationModel.record(
            operation_id=operation.operation_id,
            tenant_id=tenant_context.tenant_id,
            operation_type=operation.operation_type,
            status=status,
            now=datetime.now(UTC),
            actor_id=tenant_context.user_id,
            device_id=tenant_context.device_id,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            stored, _created = await sync_operation_crud.record_or_get(
                unit_of_work.session_handle, record
            )
            await unit_of_work.commit()
        return _result_from_record(stored)

    # ------------------------------------------------------------------
    # Pull
    # ------------------------------------------------------------------

    async def pull_changes(
        self,
        tenant_context: TenantContext,
        *,
        after_sequence: int,
        limit: int = 500,
    ) -> ChangePage:
        """Return the changes this caller may read, after the sequence it reported."""
        return await self._changes.pull_changes(
            tenant_context, after_sequence=after_sequence, limit=limit
        )

    async def advance_cursor(
        self,
        tenant_context: TenantContext,
        *,
        sequence: int,
    ) -> int:
        """Record how far this device has read, and return the position it now holds."""
        if tenant_context.device_id is None:
            raise InvalidInputError(
                operation="advance_cursor",
                entity="sync_cursor",
                detail=(
                    "a cursor belongs to a device, and this request was not made from one; a "
                    "client that advances a cursor must identify itself as a device"
                ),
            )
        device_id = tenant_context.device_id
        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            stored_cursor = await sync_cursor_crud.get_for_device(
                session, tenant_id=tenant_context.tenant_id, device_id=device_id
            )
            advanced = (
                SyncCursorModel.starting_at(
                    cursor_id=uuid4(),
                    tenant_id=tenant_context.tenant_id,
                    device_id=device_id,
                    now=now,
                    last_server_sequence=sequence,
                )
                if stored_cursor is None
                else stored_cursor.advanced_to(sequence=sequence, at=now)
            )
            saved = await sync_cursor_crud.save(session, advanced)
            await unit_of_work.commit()

        self._logger.info(
            "sync_cursor_advanced",
            tenant_id=str(tenant_context.tenant_id),
            device_id=str(saved.device_id),
            actor_id=str(tenant_context.user_id),
            last_server_sequence=saved.last_server_sequence,
        )
        return saved.last_server_sequence

    async def current_cursor(self, tenant_context: TenantContext) -> int:
        """Return how far this device has read, or zero when it has never synchronized."""
        if tenant_context.device_id is None:
            raise InvalidInputError(
                operation="read_sync_cursor",
                entity="sync_cursor",
                detail="a cursor belongs to a device, and this request was not made from one",
            )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            stored = await sync_cursor_crud.get_for_device(
                unit_of_work.session_handle,
                tenant_id=tenant_context.tenant_id,
                device_id=tenant_context.device_id,
            )
        return 0 if stored is None else stored.last_server_sequence


@dataclass(frozen=True, slots=True)
class _Outcome:
    """What a dispatched operation produced, in the terms the sync layer records."""

    entity_type: str
    entity_id: UUID
    detail: dict[str, str] = field(default_factory=dict)
    server_version: int | None = None


class _StaleVersionError(AhiaError):
    """A versioned write whose version the server has moved past.

    Internal to this module: a conflict is a normal answer to an offline client, and it is turned
    into a recorded result rather than raised out of the service. It exists so the version handling
    is one path instead of a special case at each call site.
    """

    error_code = "CONFLICT"
    http_status = 409
    safe_message = "This record has changed since you last read it."

    def __init__(self, *, server_version: int, **fields: Any) -> None:
        super().__init__(**fields)
        self.server_version = server_version


def _result_from_record(record: SyncOperationModel) -> SyncOperationResult:
    return SyncOperationResult(
        operation_id=record.id,
        operation_type=record.operation_type,
        status=record.status,
        entity_type=record.entity_type,
        entity_id=record.entity_id,
        detail=dict(record.detail or {}),
    )


def _records(payload: Mapping[str, Any], key: str, *, required: bool) -> list[dict[str, Any]]:
    value = payload.get(key)
    if value is None:
        if required:
            raise InvalidInputError(
                operation="push_operations",
                entity="sync_operation",
                detail=f"{key} is required for this operation",
            )
        return []
    if not isinstance(value, list):
        raise InvalidInputError(
            operation="push_operations",
            entity="sync_operation",
            detail=f"{key} must be a list",
        )
    records = [dict(entry) for entry in value]
    if required and not records:
        raise InvalidInputError(
            operation="push_operations",
            entity="sync_operation",
            detail=f"{key} must not be empty",
        )
    return records


def _text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidInputError(
            operation="push_operations",
            entity="sync_operation",
            detail=f"{key} is required for this operation",
        )
    return value.strip()


def _optional_text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidInputError(
            operation="push_operations",
            entity="sync_operation",
            detail=f"{key} must be text",
        )
    return value.strip() or None


def _uuid(payload: Mapping[str, Any], key: str) -> UUID:
    value = payload.get(key)
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError as invalid:
            raise InvalidInputError(
                operation="push_operations",
                entity="sync_operation",
                detail=f"{key} is not an identifier",
            ) from invalid
    raise InvalidInputError(
        operation="push_operations",
        entity="sync_operation",
        detail=f"{key} is required for this operation",
    )


def _optional_uuid(payload: Mapping[str, Any], key: str) -> UUID | None:
    if payload.get(key) is None:
        return None
    return _uuid(payload, key)


def _decimal(payload: Mapping[str, Any], key: str) -> Decimal:
    value = payload.get(key)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise InvalidInputError(
            operation="push_operations",
            entity="sync_operation",
            detail=f"{key} is required and must be a number",
        )
    try:
        return Decimal(str(value))
    except InvalidOperation as invalid:
        raise InvalidInputError(
            operation="push_operations",
            entity="sync_operation",
            detail=f"{key} is not a number",
        ) from invalid


def _optional_decimal(payload: Mapping[str, Any], key: str) -> Decimal | None:
    if payload.get(key) is None:
        return None
    return _decimal(payload, key)
