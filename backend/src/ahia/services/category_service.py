"""Category use cases: creating, listing, reading and editing a business's groups.

**Which permission governs a category.** The specification declares no `categories.*`
permission; the catalogue is governed by `products.*`, and a category is part of the
catalogue. Creating a category therefore requires `products.create`, reading one
`products.read`, and editing one `products.update`. Inventing a permission the
specification does not name would put a code in the registry that no role bundle was
designed around, and every role's meaning would quietly change.

**This service owns the checks, not the router.** A category is tenant-owned data, so
every use case here resolves the category through the authorized context: the tenant
identifier comes from the membership that was proven, never from the request, and a
category from another business is answered exactly as a missing category. A CLI or a
scheduled job calling this service gets the same answers as an HTTP request, which is
the point of putting the check here rather than in a dependency.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.errors import InvalidInputError, NotFoundError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions.product_permissions import (
    PRODUCTS_CREATE,
    PRODUCTS_READ,
    PRODUCTS_UPDATE,
)
from ahia.core.tenant_context import TenantContext
from ahia.crud import category_crud
from ahia.models.entities.category_model import CategoryModel
from ahia.services.audit_event_service import AuditEventService

_CATEGORY_LOGGER_NAME: Final[str] = "ahia.services.category"

#: Fields a caller may change. An allowlist, so a new column cannot become externally
#: writable merely by being added to the entity. The slug is absent and stays absent:
#: it is the stable handle, and it is derived rather than set.
_EDITABLE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "name",
        "description",
        "default_normal_price",
        "default_wholesale_price",
        "default_pieces_per_pack",
        "parent_id",
    }
)

#: How far up the tree a move looks. A catalogue is not nested this deep; the bound is here so that
#: a tree damaged elsewhere cannot hang a request in a loop.
_MAXIMUM_DEPTH: Final[int] = 32


#: The fields that are one decision - what this group costs - and move together.
def _money_or_none(value: object) -> Decimal | None:
    """Return a price from a change map, which carries several types.

    An explicit narrowing rather than a cast: if a caller ever put the wrong type in the map, the
    value is treated as absent rather than being asserted into a Decimal and failing later.
    """
    return value if isinstance(value, Decimal) else None


def _count_or_none(value: object) -> int | None:
    """Return a whole count from a change map, refusing a bool, which is an int in Python."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


_PRICE_FIELDS: Final[tuple[str, ...]] = (
    "default_normal_price",
    "default_wholesale_price",
    "default_pieces_per_pack",
)


class CategoryService:
    """Catalogue grouping use cases."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        audit_event_service: AuditEventService,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._audit = audit_event_service
        self._logger = (logger or get_logger(_CATEGORY_LOGGER_NAME)).bind(
            component="category_service", layer="service"
        )

    # ------------------------------------------------------------------
    # Creating
    # ------------------------------------------------------------------

    async def create_category(
        self,
        tenant_context: TenantContext,
        *,
        name: str,
        description: str | None = None,
        parent_id: UUID | None = None,
        default_normal_price: Decimal | None = None,
        default_wholesale_price: Decimal | None = None,
        default_pieces_per_pack: int | None = None,
    ) -> CategoryModel:
        """Add a category to the caller's business.

        The slug is derived from the name by the entity, so a caller cannot send two
        values that disagree. A name that is already in use in this business is a
        typed conflict from the database, not a silently created second category: two
        categories a person cannot tell apart is worse than a refusal.
        """
        tenant_context.require_permission(
            PRODUCTS_CREATE,
            operation="create_category",
            resource_type="category",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            # Checked here rather than in the schema, because a parent is a fact about the catalogue
            # and not about the shape of a request: the group must belong to this business.
            if parent_id is not None:
                parent = await category_crud.get_by_id(
                    session, tenant_id=tenant_context.tenant_id, category_id=parent_id
                )
                if parent is None:
                    raise NotFoundError(
                        operation="create_category",
                        entity="category",
                        identifier=str(parent_id),
                        detail="no group with that identifier in this business",
                    )

            category = CategoryModel.create(
                category_id=uuid4(),
                tenant_id=tenant_context.tenant_id,
                name=name,
                description=description,
                parent_id=parent_id,
                default_normal_price=default_normal_price,
                default_wholesale_price=default_wholesale_price,
                default_pieces_per_pack=default_pieces_per_pack,
                now=datetime.now(UTC),
            )
            stored = await category_crud.create(session, category)
            await self._audit.record_audit_event(
                unit_of_work.session_handle,
                tenant_context,
                action="create_category",
                entity_type="category",
                entity_id=stored.id,
                now=stored.created_at,
                detail=stored.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.info(
            "category_created",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            category_id=str(stored.id),
            category_slug=stored.slug,
        )
        return stored

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    async def list_categories(self, tenant_context: TenantContext) -> list[CategoryModel]:
        """Return every category in the caller's business, in reading order."""
        tenant_context.require_permission(
            PRODUCTS_READ,
            operation="list_categories",
            resource_type="category",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await category_crud.list_for_tenant(
                unit_of_work.session_handle, tenant_context.tenant_id
            )

    async def get_category(
        self,
        tenant_context: TenantContext,
        *,
        category_id: UUID,
    ) -> CategoryModel:
        """Return one category, or refuse as if it did not exist."""
        tenant_context.require_permission(
            PRODUCTS_READ,
            operation="get_category",
            resource_type="category",
            resource_id=str(category_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await self._require_category(
                unit_of_work.session_handle,
                tenant_context=tenant_context,
                category_id=category_id,
            )

    # ------------------------------------------------------------------
    # Editing
    # ------------------------------------------------------------------

    async def _require_move_is_possible(
        self,
        session: object,
        *,
        tenant_context: TenantContext,
        category_id: UUID,
        proposed_parent_id: UUID,
    ) -> None:
        """Refuse a move that would put a group inside itself.

        The entity refuses a group being its own parent: the one-node case. This is the rest:
        walk up from the proposed parent and refuse if the group being moved is somewhere above it.
        A group nested inside its own descendant does not merely read oddly: every walk down the
        tree would never come back, and the list builder walks the tree.
        """
        current: UUID | None = proposed_parent_id
        for _ in range(_MAXIMUM_DEPTH):
            if current is None:
                return
            if current == category_id:
                raise InvalidInputError(
                    operation="update_category",
                    entity="category",
                    identifier=str(category_id),
                    detail="a group cannot be moved inside itself or inside one of its own groups",
                )
            ancestor = await category_crud.get_by_id(
                session,  # type: ignore[arg-type]
                tenant_id=tenant_context.tenant_id,
                category_id=current,
            )
            if ancestor is None:
                raise NotFoundError(
                    operation="update_category",
                    entity="category",
                    identifier=str(proposed_parent_id),
                    detail="no group with that identifier in this business",
                )
            current = ancestor.parent_id

        raise InvalidInputError(
            operation="update_category",
            entity="category",
            identifier=str(category_id),
            detail=f"the groups are nested more than {_MAXIMUM_DEPTH} deep",
        )

    async def update_category(
        self,
        tenant_context: TenantContext,
        *,
        category_id: UUID,
        changes: Mapping[str, str | Decimal | int | None],
    ) -> CategoryModel:
        """Apply a partial edit to a category.

        The slug is not editable and never appears in the allowlist: it is the handle
        other things point at, and a rename changes what a person reads. A description
        sent as null is cleared, which is why the caller's "was this field present"
        decision is preserved into here rather than being flattened into a value.
        """
        tenant_context.require_permission(
            PRODUCTS_UPDATE,
            operation="update_category",
            resource_type="category",
            resource_id=str(category_id),
            logger=self._logger,
        )

        unexpected_fields = sorted(set(changes) - _EDITABLE_FIELDS)
        if unexpected_fields:
            raise InvalidInputError(
                operation="update_category",
                entity="category",
                identifier=str(category_id),
                detail=("fields are not editable on a category: " + ", ".join(unexpected_fields)),
            )

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            category = await self._require_category(
                session,
                tenant_context=tenant_context,
                category_id=category_id,
            )

            updated = category
            name = changes.get("name")
            if isinstance(name, str):
                updated = updated.renamed(name=name, at=now)
            if "description" in changes:
                description = changes["description"]
                updated = updated.described(
                    description=description if isinstance(description, str) else None, at=now
                )
            if "parent_id" in changes:
                raw_parent = changes["parent_id"]
                if isinstance(raw_parent, UUID):
                    proposed = raw_parent
                elif isinstance(raw_parent, str) and raw_parent.strip():
                    proposed = UUID(raw_parent.strip())
                else:
                    proposed = None
                if proposed is not None:
                    await self._require_move_is_possible(
                        session,
                        tenant_context=tenant_context,
                        category_id=category_id,
                        proposed_parent_id=proposed,
                    )
                updated = updated.reparented_to(parent_id=proposed, at=now)
            if any(field in changes for field in _PRICE_FIELDS):
                # Absent means unchanged, and an explicit null means cleared - the same rule the
                # description follows, and the reason the "was it sent" decision survives this far.
                updated = updated.repriced_defaults(
                    default_normal_price=_money_or_none(
                        changes.get("default_normal_price", updated.default_normal_price)
                    ),
                    default_wholesale_price=_money_or_none(
                        changes.get("default_wholesale_price", updated.default_wholesale_price)
                    ),
                    default_pieces_per_pack=_count_or_none(
                        changes.get("default_pieces_per_pack", updated.default_pieces_per_pack)
                    ),
                    at=now,
                )

            stored = await category_crud.update(session, updated)
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="update_category",
                entity_type="category",
                entity_id=stored.id,
                now=now,
                detail=stored.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.info(
            "category_updated",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            category_id=str(stored.id),
            changed_fields=sorted(changes),
        )
        return stored

    # ------------------------------------------------------------------
    # Shared lookups
    # ------------------------------------------------------------------

    async def _require_category(
        self,
        session: object,
        *,
        tenant_context: TenantContext,
        category_id: UUID,
    ) -> CategoryModel:
        """Load a category, refusing one that belongs to another business.

        The tenant comes from the authorized context, never from the request, so a
        category identifier alone cannot reach across tenants. A category in another
        business is answered exactly as one that does not exist, and the attempt is
        logged as a security event, because the two are deliberately
        indistinguishable to the caller and must not be indistinguishable to us.
        """
        category = await category_crud.get_by_id(
            session,  # type: ignore[arg-type]
            tenant_id=tenant_context.tenant_id,
            category_id=category_id,
        )
        if category is None:
            self._logger.warning(
                "category_access_denied",
                reason="category_not_in_tenant",
                tenant_id=str(tenant_context.tenant_id),
                category_id=str(category_id),
                security_event="tenant_isolation",
            )
            raise NotFoundError(
                operation="fetch_category",
                entity="category",
                identifier=str(category_id),
                detail="no category matched in this business",
            )
        return category
