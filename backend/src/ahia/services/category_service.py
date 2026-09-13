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

_CATEGORY_LOGGER_NAME: Final[str] = "ahia.services.category"

#: Fields a caller may change. An allowlist, so a new column cannot become externally
#: writable merely by being added to the entity. The slug is absent and stays absent:
#: it is the stable handle, and it is derived rather than set.
_EDITABLE_FIELDS: Final[frozenset[str]] = frozenset({"name", "description"})


class CategoryService:
    """Catalogue grouping use cases."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
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

        category = CategoryModel.create(
            category_id=uuid4(),
            tenant_id=tenant_context.tenant_id,
            name=name,
            description=description,
            now=datetime.now(UTC),
        )

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            stored = await category_crud.create(unit_of_work.session_handle, category)
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

    async def update_category(
        self,
        tenant_context: TenantContext,
        *,
        category_id: UUID,
        changes: Mapping[str, str | None],
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
            if name is not None:
                updated = updated.renamed(name=name, at=now)
            if "description" in changes:
                updated = updated.described(description=changes["description"], at=now)

            stored = await category_crud.update(session, updated)
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
