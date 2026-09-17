"""Product use cases: the catalogue's write path and the storefront's switches.

**Which permission governs what.** The specification names four catalogue permissions,
and each operation here maps onto exactly one of them:

    create                      products.create
    list, read                  products.read
    edit, publish, unpublish    products.update
    deactivate, reactivate      products.delete

Deactivation is the destructive direction and takes `products.delete`, which MANAGER
does not hold: withdrawing a product from sale is the owner's decision. Reactivation
takes `products.update`, because bringing something back is not destructive.

**This service owns the checks.** Every use case resolves the product - and the category
it is filed under - through the authorized context, so the tenant identifier comes from
the membership that was proven rather than from the request. A product from another
business is answered exactly as a missing product, and the attempt is logged as a
security event, because the two are deliberately indistinguishable to the caller and
must not be indistinguishable to us. A CLI command or a scheduled job calling this
service gets the same answers as an HTTP request, which is the point of putting the
checks here rather than in a router dependency.

**The public token is generated here, never supplied.** It is the address of a
storefront link and, for a shared product page, the authorization. A caller that could
choose it could choose somebody else's, and a caller that could read it from a log line
would have a link that bypasses every check in this file. It is minted by the token
service at publication and never logged - only its fingerprint is.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.errors import InvalidInputError, NotFoundError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions.product_permissions import (
    PRODUCTS_CREATE,
    PRODUCTS_DELETE,
    PRODUCTS_READ,
    PRODUCTS_UPDATE,
)
from ahia.core.security import TokenService, fingerprint_for_log
from ahia.core.tenant_context import TenantContext
from ahia.crud import category_crud, product_crud
from ahia.models.entities.category_model import CategoryModel
from ahia.models.entities.price_book import (
    NO_DEFAULTS,
    PriceDefaults,
    ResolvedPrice,
    resolve_price,
)
from ahia.models.entities.product_model import ProductModel
from ahia.services.audit_event_service import AuditEventService

_PRODUCT_LOGGER_NAME: Final[str] = "ahia.services.product"

#: Fields a caller may change. An allowlist, so a new column cannot become externally
#: writable merely by being added to the entity. The slug, the tenant, the public token
#: and the two lifecycle booleans are absent and stay absent.
_EDITABLE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "name",
        "description",
        "category_id",
        "sku",
        "barcode",
        "selling_price",
        "cost_price",
        "low_stock_threshold",
    }
)


class ProductService:
    """Catalogue use cases."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        token_service: TokenService,
        audit_event_service: AuditEventService,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._token_service = token_service
        self._audit = audit_event_service
        self._logger = (logger or get_logger(_PRODUCT_LOGGER_NAME)).bind(
            component="product_service", layer="service"
        )

    # ------------------------------------------------------------------
    # Creating
    # ------------------------------------------------------------------

    async def create_product(
        self,
        tenant_context: TenantContext,
        *,
        name: str,
        selling_price: Decimal | None,
        category_id: UUID | None = None,
        description: str | None = None,
        sku: str | None = None,
        barcode: str | None = None,
        cost_price: Decimal | None = None,
        wholesale_price: Decimal | None = None,
        pieces_per_pack: int | None = None,
        low_stock_threshold: Decimal | None = None,
    ) -> ProductModel:
        """Add a product to the catalogue. It starts active and unpublished."""
        tenant_context.require_permission(
            PRODUCTS_CREATE,
            operation="create_product",
            resource_type="product",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            group = await self._require_category_in_business(
                session, tenant_context=tenant_context, category_id=category_id
            )
            await self._require_a_price(
                own_normal_price=selling_price,
                defaults=group.price_defaults() if group is not None else NO_DEFAULTS,
                product_name=name,
                operation="create_product",
            )

            creation_arguments: dict[str, Any] = {
                "product_id": uuid4(),
                "tenant_id": tenant_context.tenant_id,
                "name": name,
                "selling_price": selling_price,
                "now": now,
                "category_id": category_id,
                "description": description,
                "sku": sku,
                "barcode": barcode,
                "cost_price": cost_price,
                "wholesale_price": wholesale_price,
                "pieces_per_pack": pieces_per_pack,
            }
            if low_stock_threshold is not None:
                creation_arguments["low_stock_threshold"] = low_stock_threshold

            product = await product_crud.create(session, ProductModel.create(**creation_arguments))
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="create_product",
                entity_type="product",
                entity_id=product.id,
                now=product.created_at,
                detail=product.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.info(
            "product_created",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            product_id=str(product.id),
            product_slug=product.slug,
            has_sku=product.sku is not None,
        )
        return product

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    async def list_products(
        self,
        tenant_context: TenantContext,
        *,
        include_inactive: bool = True,
    ) -> list[ProductModel]:
        """Return the catalogue, in reading order.

        Inactive products are included by default: `products.read` is described as
        seeing the catalogue including what is not currently sold, and a withdrawn
        product that cannot be found cannot be brought back.
        """
        tenant_context.require_permission(
            PRODUCTS_READ,
            operation="list_products",
            resource_type="product",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await product_crud.list_for_tenant(
                unit_of_work.session_handle,
                tenant_context.tenant_id,
                include_inactive=include_inactive,
            )

    async def get_product(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
    ) -> ProductModel:
        """Return one product, or refuse as if it did not exist."""
        tenant_context.require_permission(
            PRODUCTS_READ,
            operation="get_product",
            resource_type="product",
            resource_id=str(product_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await self._require_product(
                unit_of_work.session_handle,
                tenant_context=tenant_context,
                product_id=product_id,
            )

    async def _require_a_price(
        self,
        *,
        own_normal_price: Decimal | None,
        defaults: PriceDefaults,
        product_name: str,
        operation: str,
    ) -> None:
        """Refuse an item nobody has priced: it cannot be sold or shown to a customer.

        The rule lives here and not in the entity: an entity cannot see its group, and "no price
        anywhere" is a business rule about an item *and* its group rather than a fact about either.
        """
        if resolve_price(own_normal_price=own_normal_price, defaults=defaults).is_priced:
            return
        raise InvalidInputError(
            operation=operation,
            entity="product",
            detail=(
                f"{product_name} has no price and its group has none either; "
                "set one on the item or on the group"
            ),
        )

    # ------------------------------------------------------------------
    # The price book: what an item costs, once its group has had its say
    # ------------------------------------------------------------------

    async def prices_for(
        self,
        tenant_context: TenantContext,
        products: list[ProductModel],
    ) -> dict[UUID, ResolvedPrice]:
        """Return the resolved price for each item, reading groups once.

        Batched rather than resolved item by item: a catalogue of two hundred models under eight
        grades is eight groups to read, not two hundred, and that difference decides whether a
        screen opens.

        No permission check of its own: this reads nothing the caller has not already been allowed
        to read, and it is called from the same use case that produced the products.
        """
        if not products:
            return {}

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            groups = await category_crud.list_for_tenant(
                unit_of_work.session_handle, tenant_context.tenant_id
            )
        defaults_by_group = {group.id: group.price_defaults() for group in groups}

        def defaults_for(product: ProductModel) -> PriceDefaults:
            """A product may belong to no group at all, which is a real state with no defaults."""
            if product.category_id is None:
                return NO_DEFAULTS
            return defaults_by_group.get(product.category_id, NO_DEFAULTS)

        return {
            product.id: resolve_price(
                own_normal_price=product.selling_price,
                own_wholesale_price=product.wholesale_price,
                own_pieces_per_pack=product.pieces_per_pack,
                defaults=defaults_for(product),
            )
            for product in products
        }

    async def price_for(
        self,
        tenant_context: TenantContext,
        product: ProductModel,
    ) -> ResolvedPrice:
        """Return the resolved price for one item."""
        resolved = await self.prices_for(tenant_context, [product])
        return resolved[product.id]

    async def list_products_with_prices(
        self,
        tenant_context: TenantContext,
        *,
        include_inactive: bool = True,
    ) -> list[tuple[ProductModel, ResolvedPrice]]:
        """Return the catalogue with each item's resolved price.

        A pair rather than a new type: the product is the entity this layer deals in, and the price
        is derived from it and its group, so they travel together at this boundary.
        """
        products = await self.list_products(tenant_context, include_inactive=include_inactive)
        prices = await self.prices_for(tenant_context, products)
        return [(product, prices[product.id]) for product in products]

    # ------------------------------------------------------------------
    # Editing
    # ------------------------------------------------------------------

    async def update_product(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
        changes: Mapping[str, Any],
    ) -> ProductModel:
        """Apply a partial edit.

        The change map is heterogeneous on purpose - text, an identifier and decimals -
        and each value is narrowed where it is used rather than trusted. The schema
        layer has already validated what arrives over HTTP, and this is the layer that
        makes the entity's annotations true for every other caller.

        Fields that can be cleared are cleared by sending null, and fields that are
        absent are left alone. That distinction is carried in the map itself: `sku: None`
        means "remove the SKU", while no `sku` key means "leave the SKU".
        """
        tenant_context.require_permission(
            PRODUCTS_UPDATE,
            operation="update_product",
            resource_type="product",
            resource_id=str(product_id),
            logger=self._logger,
        )

        unexpected_fields = sorted(set(changes) - _EDITABLE_FIELDS)
        if unexpected_fields:
            raise InvalidInputError(
                operation="update_product",
                entity="product",
                identifier=str(product_id),
                detail="fields are not editable on a product: " + ", ".join(unexpected_fields),
            )

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            product = await self._require_product(
                session, tenant_context=tenant_context, product_id=product_id
            )

            if "category_id" in changes:
                category_id = _optional_identifier(changes, "category_id")
                await self._require_category_in_business(
                    session, tenant_context=tenant_context, category_id=category_id
                )
                product = product.categorised(category_id=category_id, at=now)

            if "name" in changes:
                product = product.renamed(name=_required_text(changes, "name"), at=now)
            if "description" in changes:
                product = product.described(
                    description=_optional_text(changes, "description"), at=now
                )
            if "sku" in changes or "barcode" in changes:
                # Both are applied together. A caller that changes one passes the
                # current value of the other, which keeps "clear it" and "leave it"
                # visibly different at every call site.
                product = product.identified(
                    sku=(_optional_text(changes, "sku") if "sku" in changes else product.sku),
                    barcode=(
                        _optional_text(changes, "barcode")
                        if "barcode" in changes
                        else product.barcode
                    ),
                    at=now,
                )
            if "selling_price" in changes or "cost_price" in changes:
                product = product.repriced(
                    selling_price=(
                        _required_money(changes, "selling_price")
                        if "selling_price" in changes
                        else product.selling_price
                    ),
                    cost_price=(
                        _optional_money(changes, "cost_price")
                        if "cost_price" in changes
                        else product.cost_price
                    ),
                    at=now,
                )
            if "low_stock_threshold" in changes:
                product = product.rethresholded(
                    low_stock_threshold=_required_quantity(changes, "low_stock_threshold"),
                    at=now,
                )

            stored = await product_crud.update(session, product)
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="update_product",
                entity_type="product",
                entity_id=stored.id,
                now=now,
                detail=stored.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.info(
            "product_updated",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            product_id=str(stored.id),
            changed_fields=sorted(changes),
        )
        return stored

    # ------------------------------------------------------------------
    # Publication
    # ------------------------------------------------------------------

    async def publish_product(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
    ) -> ProductModel:
        """Make a product visible to customers at a freshly minted public address.

        Publishing an already published product is idempotent, and a product that was
        published before keeps the address it had - so withdrawing a product and
        bringing it back does not invalidate a link a customer already holds. The token
        is minted here rather than accepted from the caller: it is the address, and a
        caller who could choose it could choose one that belongs to somebody else.
        """
        tenant_context.require_permission(
            PRODUCTS_UPDATE,
            operation="publish_product",
            resource_type="product",
            resource_id=str(product_id),
            logger=self._logger,
        )

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            product = await self._require_product(
                session, tenant_context=tenant_context, product_id=product_id
            )
            # A product that has been published before already has an address. Minting
            # a new one would break every link a customer holds, so a token is only
            # generated when there is none.
            now = datetime.now(UTC)
            published = product.publish(
                public_token=product.public_token or self._token_service.generate_public_token(),
                at=now,
            )
            if published == product:
                # Already published: the public address does not change, so there is
                # nothing to write and nothing new to tell anybody.
                return product
            stored = await product_crud.update(session, published)
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="publish_product",
                entity_type="product",
                entity_id=stored.id,
                now=now,
                detail=stored.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.info(
            "product_published",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            product_id=str(stored.id),
            public_token_fingerprint=fingerprint_for_log(published.public_token or ""),
        )
        return stored

    async def unpublish_product(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
    ) -> ProductModel:
        """Withdraw a product from the storefront without retiring it.

        The public token is kept, so re-publishing later restores the same address
        rather than issuing a new one that nobody has.
        """
        tenant_context.require_permission(
            PRODUCTS_UPDATE,
            operation="unpublish_product",
            resource_type="product",
            resource_id=str(product_id),
            logger=self._logger,
        )

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            product = await self._require_product(
                session, tenant_context=tenant_context, product_id=product_id
            )
            stored = await product_crud.update(session, product.unpublish(at=now))
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="unpublish_product",
                entity_type="product",
                entity_id=stored.id,
                now=now,
                detail=stored.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.info(
            "product_unpublished",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            product_id=str(stored.id),
        )
        return stored

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def deactivate_product(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
    ) -> ProductModel:
        """Withdraw a product from sale, and from the storefront with it.

        Deactivation, never deletion: every sale line that references this product must
        keep resolving to it, and a product that has been sold cannot be a row that no
        longer exists. The entity moves both states together, so a withdrawn product is
        never left visible.
        """
        tenant_context.require_permission(
            PRODUCTS_DELETE,
            operation="deactivate_product",
            resource_type="product",
            resource_id=str(product_id),
            logger=self._logger,
        )

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            product = await self._require_product(
                session, tenant_context=tenant_context, product_id=product_id
            )
            stored = await product_crud.update(session, product.deactivate(at=now))
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="deactivate_product",
                entity_type="product",
                entity_id=stored.id,
                now=now,
                detail=stored.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.warning(
            "product_deactivated",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            product_id=str(stored.id),
            was_published=product.is_published,
        )
        return stored

    async def activate_product(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
    ) -> ProductModel:
        """Return a withdrawn product to the catalogue. It stays unpublished."""
        tenant_context.require_permission(
            PRODUCTS_UPDATE,
            operation="activate_product",
            resource_type="product",
            resource_id=str(product_id),
            logger=self._logger,
        )

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            product = await self._require_product(
                session, tenant_context=tenant_context, product_id=product_id
            )
            stored = await product_crud.update(session, product.activate(at=now))
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="activate_product",
                entity_type="product",
                entity_id=stored.id,
                now=now,
                detail=stored.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.info(
            "product_activated",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            product_id=str(stored.id),
        )
        return stored

    # ------------------------------------------------------------------
    # Shared lookups and value narrowing
    # ------------------------------------------------------------------

    async def _require_product(
        self,
        session: object,
        *,
        tenant_context: TenantContext,
        product_id: UUID,
    ) -> ProductModel:
        """Load a product, refusing one that belongs to another business."""
        product = await product_crud.get_by_id(
            session,  # type: ignore[arg-type]
            tenant_id=tenant_context.tenant_id,
            product_id=product_id,
        )
        if product is None:
            self._logger.warning(
                "product_access_denied",
                reason="product_not_in_tenant",
                tenant_id=str(tenant_context.tenant_id),
                product_id=str(product_id),
                security_event="tenant_isolation",
            )
            raise NotFoundError(
                operation="fetch_product",
                entity="product",
                identifier=str(product_id),
                detail="no product matched in this business",
            )
        return product

    async def _require_category_in_business(
        self,
        session: object,
        *,
        tenant_context: TenantContext,
        category_id: UUID | None,
    ) -> CategoryModel | None:
        """Refuse a category that does not belong to this business, and return it.

        It returns the group rather than only checking it, because the caller almost always needs
        the group's prices next and reading it twice would be a second query for the same row.

        The database enforces this too, through the composite key on
        `(category_id, tenant_id)`. Checking here means a caller receives a clear
        refusal that names the category, while the constraint remains the guarantee
        that no code path can bypass.
        """
        if category_id is None:
            return None
        category = await category_crud.get_by_id(
            session,  # type: ignore[arg-type]
            tenant_id=tenant_context.tenant_id,
            category_id=category_id,
        )
        if category is None:
            self._logger.warning(
                "product_category_refused",
                reason="category_not_in_tenant",
                tenant_id=str(tenant_context.tenant_id),
                category_id=str(category_id),
                security_event="tenant_isolation",
            )
            raise NotFoundError(
                operation="file_product_under_category",
                entity="category",
                identifier=str(category_id),
                detail="no category matched in this business",
            )
        return category


# ---------------------------------------------------------------------------
# Narrowing the change map
#
# The values arrive already validated from the schema layer. These helpers are what
# makes that true for every other caller too - a CLI, a job, a test - and they fail as
# a bad request rather than as an invariant violation, because a wrong type is the
# caller's mistake, not a defect in the domain.
# ---------------------------------------------------------------------------


def _required_text(changes: Mapping[str, Any], field_name: str) -> str:
    value = changes[field_name]
    if not isinstance(value, str) or not value.strip():
        raise _bad_field(field_name, "a non-empty string")
    return value


def _optional_text(changes: Mapping[str, Any], field_name: str) -> str | None:
    value = changes[field_name]
    if value is None:
        return None
    if not isinstance(value, str):
        raise _bad_field(field_name, "text or null")
    return value


def _optional_identifier(changes: Mapping[str, Any], field_name: str) -> UUID | None:
    value = changes[field_name]
    if value is None:
        return None
    if not isinstance(value, UUID):
        raise _bad_field(field_name, "an identifier or null")
    return value


def _required_money(changes: Mapping[str, Any], field_name: str) -> Decimal:
    value = changes[field_name]
    if not isinstance(value, Decimal):
        raise _bad_field(field_name, "a decimal amount")
    return value


def _optional_money(changes: Mapping[str, Any], field_name: str) -> Decimal | None:
    value = changes[field_name]
    if value is None:
        return None
    if not isinstance(value, Decimal):
        raise _bad_field(field_name, "a decimal amount or null")
    return value


def _required_quantity(changes: Mapping[str, Any], field_name: str) -> Decimal:
    value = changes[field_name]
    if not isinstance(value, Decimal):
        raise _bad_field(field_name, "a decimal quantity")
    return value


def _bad_field(field_name: str, expected: str) -> InvalidInputError:
    return InvalidInputError(
        operation="update_product",
        entity="product",
        detail=f"{field_name} must be {expected}",
    )
