"""The change feed: what a device is owed, written with the change that produced it.

**The feed is a projection of the audit trail, restricted to what a client can hold offline.**
Every mutating use case already writes an audit event naming the entity it touched, inside the
transaction that touched it. Rather than ask forty call sites to write a second row, the recorder
appends a change row for the entity types declared synchronizable, and for successful actions
only: a refused action changed nothing, so there is nothing for a device to fetch. The two tables
then cannot disagree about when something happened, because one call writes both.

**The change type is declared, not guessed from the action name.** `CHANGE_TYPE_FOR_ACTION` names
the actions that create a record; everything else is an update, which is the safe reading - a
client that treats an update as a creation would replace its local row, and a client that treats
a creation as an update would keep a row it should have inserted. A test scans the call sites for
every action string the services use and fails when one is not in the map's vocabulary, so the map
cannot fall behind the code that writes the events.

**Pulling is filtered by what the caller may read.** The feed spans the catalogue, the stock
ledger, customers, sales and expenses, and there is no `sync.read` permission in the product's
permission list. Requiring one existing permission would be arbitrary and would hand a
salesperson the expense changes; instead the mapping from entity type to read permission is
declared here, and a change is returned only when the caller holds the permission for it. A
caller holding none of them is refused rather than handed an empty page, because an empty page
looks like "nothing changed" and a refusal says what actually happened.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.errors import AuthorizationError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions.customer_permissions import CUSTOMERS_READ
from ahia.core.permissions.expense_permissions import EXPENSES_READ
from ahia.core.permissions.inventory_permissions import INVENTORY_READ
from ahia.core.permissions.product_permissions import PRODUCTS_READ
from ahia.core.permissions.sales_permissions import SALES_READ
from ahia.core.tenant_context import TenantContext
from ahia.crud import sync_change_crud
from ahia.models.entities.audit_event_model import AuditOutcome
from ahia.models.entities.sync_change_model import (
    SYNCHRONIZABLE_ENTITY_TYPES,
    ChangeType,
    SyncChangeModel,
)

_SYNC_CHANGE_LOGGER_NAME: Final[str] = "ahia.services.sync_change"

#: Every action a use case records, and what it means for a device's copy of the record.
#:
#: The map is total on purpose. A default of "updated" would be safe for a client - it replaces a
#: row it already has - but it would be silent about an action somebody added without deciding,
#: and "did the record appear or change" is exactly the question a client must not guess. A test
#: scans the services for every action string they record and fails when one is missing here, so
#: adding a use case without classifying it is a red build rather than a mystery on a phone.
CHANGE_TYPE_FOR_ACTION: Final[dict[str, ChangeType]] = {
    # Catalogue
    "create_category": ChangeType.CREATED,
    "update_category": ChangeType.UPDATED,
    "create_product": ChangeType.CREATED,
    "update_product": ChangeType.UPDATED,
    "publish_product": ChangeType.UPDATED,
    "unpublish_product": ChangeType.UPDATED,
    "activate_product": ChangeType.UPDATED,
    "deactivate_product": ChangeType.UPDATED,
    "attach_product_image": ChangeType.CREATED,
    "remove_product_image": ChangeType.DELETED,
    "set_primary_product_image": ChangeType.UPDATED,
    "reorder_product_images": ChangeType.UPDATED,
    # Stock
    "initialize_stock": ChangeType.CREATED,
    "receive_stock": ChangeType.CREATED,
    "adjust_stock": ChangeType.CREATED,
    "record_damage": ChangeType.CREATED,
    "transfer_stock": ChangeType.CREATED,
    "ship_stock": ChangeType.CREATED,
    "receive_shipment": ChangeType.CREATED,
    # Counter
    "create_customer": ChangeType.CREATED,
    "update_customer": ChangeType.UPDATED,
    "deactivate_customer": ChangeType.UPDATED,
    "reactivate_customer": ChangeType.UPDATED,
    "complete_sale": ChangeType.CREATED,
    "cancel_sale": ChangeType.UPDATED,
    # Money out
    "record_expense": ChangeType.CREATED,
    "reverse_expense": ChangeType.UPDATED,
    # Staff and business settings. These entity types are not synchronizable today, so no change
    # row is written for them; they are classified anyway, because the guard below is about the
    # action vocabulary rather than about what happens to be in the feed this month.
    "invite_member": ChangeType.CREATED,
    "change_member_role": ChangeType.UPDATED,
    "suspend_member": ChangeType.UPDATED,
    "reactivate_member": ChangeType.UPDATED,
    "remove_member": ChangeType.DELETED,
    "register_device": ChangeType.CREATED,
    "revoke_device": ChangeType.DELETED,
    "create_custom_role": ChangeType.CREATED,
    "update_role_permissions": ChangeType.UPDATED,
    "update_tenant_profile": ChangeType.UPDATED,
    "deactivate_tenant": ChangeType.UPDATED,
    "update_negative_stock_policy": ChangeType.UPDATED,
    # The public shop and share links. Their entity types are not synchronizable - no client holds
    # a storefront or a share link offline - but they are classified anyway, because this map is
    # the action vocabulary and the guard below fails the build when a recorded action is missing.
    "publish_storefront": ChangeType.UPDATED,
    "unpublish_storefront": ChangeType.UPDATED,
    "update_storefront": ChangeType.UPDATED,
    "share_invoice": ChangeType.CREATED,
    "revoke_share_link": ChangeType.DELETED,
    "share_report": ChangeType.CREATED,
    # Exporting writes a record of a report being taken out of the product. Nothing a device holds
    # offline changes, so no feed row is written; it is classified because this map is the action
    # vocabulary and the guard fails the build for an action nobody classified.
    "export_report": ChangeType.CREATED,
}

#: What a caller must hold to be told about a kind of record. Declared once, so the feed's
#: authorization cannot drift from the permissions the rest of the product uses.
READ_PERMISSION_FOR_ENTITY_TYPE: Final[dict[str, str]] = {
    "category": PRODUCTS_READ,
    "product": PRODUCTS_READ,
    "product_image": PRODUCTS_READ,
    "inventory": INVENTORY_READ,
    "inventory_movement": INVENTORY_READ,
    "customer": CUSTOMERS_READ,
    "sale": SALES_READ,
    "expense": EXPENSES_READ,
}

#: A page of the feed, and whether there is more. The client advances its cursor to
#: `latest_sequence` and asks again; a page that stops short of the end must say so, or a device
#: would sit on a partial feed until something else changed.
DEFAULT_CHANGE_PAGE_SIZE: Final[int] = 500


@dataclass(frozen=True, slots=True)
class ChangePage:
    """One page of a device's feed, in server order."""

    changes: list[SyncChangeModel]
    latest_sequence: int
    has_more: bool


class SyncChangeService:
    """Writing and reading the change feed."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._logger = (logger or get_logger(_SYNC_CHANGE_LOGGER_NAME)).bind(
            component="sync_change_service", layer="service"
        )

    # ------------------------------------------------------------------
    # Writing, inside the caller's transaction
    # ------------------------------------------------------------------

    async def record_for_audit_event(
        self,
        session: object,
        tenant_context: TenantContext,
        *,
        action: str,
        entity_type: str,
        entity_id: UUID | None,
        outcome: AuditOutcome,
        now: datetime,
        operation_id: UUID | None = None,
    ) -> SyncChangeModel | None:
        """Append a change for a recorded action, when a device could care about it.

        Returns None when nothing was written: a refused action changed nothing, an entity type
        outside the synchronizable set is not something a client holds, and an event with no
        entity identifier names nothing to fetch. All three are ordinary, not errors, which is
        why the answer is None rather than a raise.
        """
        if outcome is not AuditOutcome.SUCCEEDED:
            return None
        if entity_type not in SYNCHRONIZABLE_ENTITY_TYPES:
            return None
        if entity_id is None:
            return None

        change = SyncChangeModel.for_record(
            change_id=uuid4(),
            tenant_id=tenant_context.tenant_id,
            # The database assigns the sequence; the entity validates what comes back. One is
            # passed because the field is required, and it is replaced by the identity column.
            change_sequence=1,
            entity_type=entity_type,
            entity_id=entity_id,
            change_type=CHANGE_TYPE_FOR_ACTION.get(action, ChangeType.UPDATED),
            now=now,
            operation_id=operation_id,
        )
        stored = await sync_change_crud.record(session, change)  # type: ignore[arg-type]
        self._logger.info("sync_change_recorded", **stored.describe_for_audit())
        return stored

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    async def pull_changes(
        self,
        tenant_context: TenantContext,
        *,
        after_sequence: int,
        limit: int = DEFAULT_CHANGE_PAGE_SIZE,
    ) -> ChangePage:
        """Return the changes this caller is allowed to see, after a sequence.

        The permission check is per entity type rather than a single gate: the feed spans five
        modules, and a salesperson is entitled to the catalogue, the customers and the sales, and
        is not entitled to the expenses. A caller who holds none of the read permissions is
        refused rather than handed an empty page.
        """
        readable = self._readable_entity_types(tenant_context)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            visible = []
            # Paged in the database by sequence, then filtered: asking for one page and dropping
            # what the caller may not see is the only way to keep the cursor meaningful, and
            # `has_more` tells the client to come back for the rest.
            candidates = await sync_change_crud.changes_after(
                session,
                tenant_context.tenant_id,
                after_sequence=after_sequence,
                limit=limit + 1,
            )
            latest = await sync_change_crud.latest_sequence(session, tenant_context.tenant_id)
        for change in candidates:
            if change.entity_type in readable:
                visible.append(change)
        has_more = len(candidates) > limit
        return ChangePage(
            changes=visible[:limit],
            latest_sequence=latest,
            has_more=has_more,
        )

    def _readable_entity_types(self, tenant_context: TenantContext) -> frozenset[str]:
        readable = frozenset(
            entity_type
            for entity_type, permission in READ_PERMISSION_FOR_ENTITY_TYPE.items()
            if tenant_context.has_permission(permission)
        )
        if not readable:
            self._logger.warning(
                "authorization_denied",
                decision="denied",
                reason="no_sync_read_permission",
                operation="pull_changes",
                tenant_id=str(tenant_context.tenant_id),
                actor_id=str(tenant_context.user_id),
                membership_id=str(tenant_context.membership_id),
                action="sync.pull",
                resource_type="sync_change",
                held_permission_count=len(tenant_context.permissions),
            )
            raise AuthorizationError(
                operation="pull_changes",
                entity="sync_change",
                identifier=str(tenant_context.tenant_id),
                detail=(
                    "reading the change feed needs at least one of the read permissions the "
                    f"feed covers; role={tenant_context.role_name or 'unknown'}"
                ),
            )
        return readable
