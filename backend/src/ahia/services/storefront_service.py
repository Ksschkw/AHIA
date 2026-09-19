"""Public shop use cases: opening one, and what a stranger sees.

**A public read is the one place this product answers without an identity.** Everywhere else an
anonymous caller is refused, and here the whole point is that a customer with a link can look at a
shop. The compensation is the projection: what a stranger receives is built from an allowlist of
public fields - the product's name, its selling price, whether it is available at all, and one
picture - and never by removing private fields from a business object. Cost price, stock counts,
staff, financial data and internal identifiers are not filtered out of this response; they are
never put into it. A projection that cannot leak is worth more than one that currently does not.

**Availability is a boolean, never a count.** "In stock" is what a customer needs to decide
whether to make the trip; "three left" is the business's own information, and a stranger does not
need to know how thin the shelf is. The count stays behind `inventory.read`.

**The address is the business's, and publication is the shop's.** `/shop/{tenant_slug}` comes from
the tenant, resolved by slug, and the storefront row only says whether the shop answers. A slug
that does not exist and a shop that is not open produce the same not-found answer, so a stranger
cannot enumerate which businesses exist by watching the difference.

**Publishing is behind a flag, and the reads are behind the same one.** The feature is off by
default: while it is off a business cannot open a shop and a public URL does not answer, because a
half-released storefront is one that customers can find and the business cannot manage. The flag
is a release control, not a security control - the permission check, the projection and the
rate limit all hold regardless of what it is set to.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.errors import InvalidInputError, NotFoundError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions.product_permissions import PRODUCTS_READ
from ahia.core.permissions.storefront_permissions import STOREFRONT_MANAGE, STOREFRONT_READ
from ahia.core.tenant_context import TenantContext
from ahia.core.tenant_scope import tenant_scope
from ahia.crud import (
    category_crud,
    product_crud,
    product_image_crud,
    storefront_crud,
    tenant_crud,
)
from ahia.models.entities.phone_number import (
    canonical_phone_number,
    international_digits_for,
    is_plausible_phone_number,
)
from ahia.models.entities.product_image_model import ProductImageModel
from ahia.models.entities.product_model import ProductModel
from ahia.models.entities.storefront_model import StorefrontModel
from ahia.schemas.money_format import money_text
from ahia.services.audit_event_service import AuditEventService
from ahia.services.product_image_service import ProductImageService

_STOREFRONT_LOGGER_NAME: Final[str] = "ahia.services.storefront"

#: Fields a business may change about what its shop says. An allowlist, so a new column cannot
#: become externally writable merely by being added to the entity.
_EDITABLE_FIELDS: Final[frozenset[str]] = frozenset({"headline", "description", "contact_phone"})


@dataclass(frozen=True, slots=True)
class PublicProduct:
    """One product as a stranger sees it."""

    product_slug: str
    name: str
    selling_price: Decimal | None
    description: str | None = None
    primary_image_url: str | None = None
    #: The heading this item sits under in the trader's own words: "21D", and the models under it.
    group_name: str | None = None
    #: True when the item carries its own price rather than the one its group sets. Only these are
    #: shown to a customer by name - "Hot 8 is 370, the rest of the 21D are 350" - because the
    #: trader should not have to type four hundred models in for the four hundred that are all the
    #: same price.
    is_special: bool = False


@dataclass(frozen=True, slots=True)
class PublicStorefront:
    """A shop as a stranger sees it, with its catalogue.

    No internal identifiers: a public page that carried a tenant or product UUID would be the
    enumeration the sharing rules forbid, and the slug is the only address a customer needs.
    """

    tenant_slug: str
    business_name: str
    headline: str | None
    description: str | None
    contact_phone: str | None
    products: tuple[PublicProduct, ...]

    @property
    def is_open(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class ProductShareTarget:
    """What is needed to share one product: the address, and who to address.

    The public path and the contact number, and no URLs. A service may not reach into an integration
    adapter - the layer contract forbids it, and the forbidding is the point: the adapter knows
    how a `wa.me` link is spelled, and this layer knows which product is being shared. The
    transport layer is where the two meet, and it is the only place that has to know both.
    """

    business_name: str
    product_name: str
    product_slug: str
    public_path: str
    price_text: str | None
    whatsapp_number: str | None
    #: Why there is no number, when there is none. A typed absence rather than a silent null: a
    #: screen that shows "share on WhatsApp" and does nothing is worse than one that says why.
    whatsapp_unavailable_reason: str | None = None


class StorefrontService:
    """Storefront use cases."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        product_image_service: ProductImageService,
        audit_event_service: AuditEventService,
        publishing_enabled: bool,
        default_phone_country_code: str,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._images = product_image_service
        self._audit = audit_event_service
        self._publishing_enabled = publishing_enabled
        self._default_country_code = f"+{default_phone_country_code.lstrip('+')}"
        self._logger = (logger or get_logger(_STOREFRONT_LOGGER_NAME)).bind(
            component="storefront_service", layer="service"
        )

    # ------------------------------------------------------------------
    # Managing the shop
    # ------------------------------------------------------------------

    async def get_storefront(self, tenant_context: TenantContext) -> StorefrontModel:
        """Return the business's own shop, closed and empty if it never opened one."""
        tenant_context.require_permission(
            STOREFRONT_READ,
            operation="get_storefront",
            resource_type="storefront",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            stored = await storefront_crud.get_for_tenant(
                unit_of_work.session_handle, tenant_context.tenant_id
            )
        return stored or StorefrontModel.open_shop(
            storefront_id=uuid4(),
            tenant_id=tenant_context.tenant_id,
            now=datetime.now(UTC),
        )

    async def publish_storefront(
        self,
        tenant_context: TenantContext,
        *,
        headline: str | None = None,
        description: str | None = None,
        contact_phone: str | None = None,
    ) -> StorefrontModel:
        """Open the shop at the business's public address."""
        tenant_context.require_permission(
            STOREFRONT_MANAGE,
            operation="publish_storefront",
            resource_type="storefront",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )
        self._require_publishing_enabled(operation="publish_storefront")

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            existing = await storefront_crud.get_for_tenant(session, tenant_context.tenant_id)
            shop = existing or StorefrontModel.open_shop(
                storefront_id=uuid4(), tenant_id=tenant_context.tenant_id, now=now
            )
            stored = await storefront_crud.update(
                session,
                shop.published(
                    at=now,
                    headline=headline,
                    description=description,
                    contact_phone=self._canonical_or_refuse(
                        contact_phone, operation="publish_storefront"
                    ),
                ),
            )
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="publish_storefront",
                entity_type="storefront",
                entity_id=stored.id,
                now=now,
                detail=stored.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.info(
            "storefront_published",
            tenant_id=str(stored.tenant_id),
            actor_id=str(tenant_context.user_id),
            storefront_id=str(stored.id),
            has_contact_phone=stored.contact_phone is not None,
        )
        return stored

    async def update_storefront(
        self,
        tenant_context: TenantContext,
        *,
        changes: Mapping[str, Any],
    ) -> StorefrontModel:
        """Change what the shop says about itself, without changing whether it is open."""
        tenant_context.require_permission(
            STOREFRONT_MANAGE,
            operation="update_storefront",
            resource_type="storefront",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )
        self._require_publishing_enabled(operation="update_storefront")

        unexpected = sorted(set(changes) - _EDITABLE_FIELDS)
        if unexpected:
            raise InvalidInputError(
                operation="update_storefront",
                entity="storefront",
                identifier=str(tenant_context.tenant_id),
                detail="fields are not editable on a storefront: " + ", ".join(unexpected),
            )

        headline = _optional_text(changes, "headline") if "headline" in changes else None
        description = _optional_text(changes, "description") if "description" in changes else None
        contact_phone = (
            self._canonical_or_refuse(
                _optional_text(changes, "contact_phone"), operation="update_storefront"
            )
            if "contact_phone" in changes
            else None
        )

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            existing = await storefront_crud.get_for_tenant(session, tenant_context.tenant_id)
            shop = existing or StorefrontModel.open_shop(
                storefront_id=uuid4(), tenant_id=tenant_context.tenant_id, now=now
            )
            # An open shop is re-published with the new text so the publication moment is
            # preserved; a closed one keeps being closed. `published` is idempotent for the
            # fields it is not given.
            updated = shop.published(
                at=now, headline=headline, description=description, contact_phone=contact_phone
            )
            stored = await storefront_crud.update(session, updated)
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="update_storefront",
                entity_type="storefront",
                entity_id=stored.id,
                now=now,
                detail=stored.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.info(
            "storefront_updated",
            tenant_id=str(stored.tenant_id),
            actor_id=str(tenant_context.user_id),
            storefront_id=str(stored.id),
            changed_fields=sorted(changes),
        )
        return stored

    async def unpublish_storefront(self, tenant_context: TenantContext) -> StorefrontModel:
        """Close the shop, keeping the address a customer already holds."""
        tenant_context.require_permission(
            STOREFRONT_MANAGE,
            operation="unpublish_storefront",
            resource_type="storefront",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )
        self._require_publishing_enabled(operation="unpublish_storefront")

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            existing = await storefront_crud.get_for_tenant(session, tenant_context.tenant_id)
            shop = existing or StorefrontModel.open_shop(
                storefront_id=uuid4(), tenant_id=tenant_context.tenant_id, now=now
            )
            stored = await storefront_crud.update(session, shop.unpublished(at=now))
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="unpublish_storefront",
                entity_type="storefront",
                entity_id=stored.id,
                now=now,
                detail=stored.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.warning(
            "storefront_unpublished",
            tenant_id=str(stored.tenant_id),
            actor_id=str(tenant_context.user_id),
            storefront_id=str(stored.id),
            security_event="storefront_unpublished",
        )
        return stored

    # ------------------------------------------------------------------
    # What a stranger sees
    # ------------------------------------------------------------------

    async def read_public_storefront(self, *, tenant_slug: str) -> PublicStorefront:
        """Return a published shop and its catalogue, for a caller with no identity.

        A slug that does not exist and a shop that is not open are the same not-found answer: a
        stranger learns nothing about which businesses exist by comparing the two.

        Two transactions, because a public read begins before any business is known. The first
        resolves the slug to a business - a table no tenant scope covers, which is what makes a
        public address possible at all. The second reads the shop and its catalogue with that
        business bound as the Row-Level Security scope, because those tables are visible only from
        inside a scope. A read that spanned both inside one transaction would return an empty
        catalogue the moment the policies are on.
        """
        self._require_publishing_enabled(operation="read_public_storefront")
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            tenant = await tenant_crud.get_by_slug(unit_of_work.session_handle, tenant_slug)
            if tenant is None or not tenant.is_active:
                raise self._closed_shop(tenant_slug)
            resolved_tenant_id = tenant.id
            resolved_slug = tenant.slug
            business_name = tenant.name

        with tenant_scope(resolved_tenant_id):
            unit_of_work = self._unit_of_work_factory()
            async with unit_of_work:
                session = unit_of_work.session_handle
                shop = await storefront_crud.get_for_tenant(session, resolved_tenant_id)
                if shop is None or not shop.is_open():
                    raise self._closed_shop(tenant_slug)
                products = await product_crud.list_published_for_tenant(session, resolved_tenant_id)
                catalogue = [
                    await self._public_product(
                        session,
                        tenant_id=resolved_tenant_id,
                        product=product,
                    )
                    for product in products
                ]

        return PublicStorefront(
            tenant_slug=resolved_slug,
            business_name=business_name,
            headline=shop.headline,
            description=shop.description,
            # The shop's own number if it has one, otherwise the business's - which is where a
            # trader
            # actually put it. Reading only the shop's field meant a customer on a product page was
            # told "this shop has no number to message yet" while the trader had already saved one
            # on
            # his business, which is the one thing that must never happen: a shop nobody can ask a
            # question is a shop nobody buys from.
            contact_phone=shop.contact_phone or tenant.phone,
            products=tuple(catalogue),
        )

    async def share_target_for_product(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
    ) -> ProductShareTarget:
        """Return what sharing one product needs: its public address and who to address.

        The product must be published and the shop open, because sharing a product that is not on
        the shop sends a customer to an address that answers "not found" - and they will blame the
        shop, not the button. The refusal names which of the two is missing, so the person holding
        the phone knows what to fix.
        """
        tenant_context.require_permission(
            PRODUCTS_READ,
            operation="share_product",
            resource_type="product",
            resource_id=str(product_id),
            logger=self._logger,
        )

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            product = await product_crud.get_by_id(
                session, tenant_id=tenant_context.tenant_id, product_id=product_id
            )
            if product is None:
                raise NotFoundError(
                    operation="share_product",
                    entity="product",
                    identifier=str(product_id),
                    detail="no product matched in this business",
                )
            shop = await storefront_crud.get_for_tenant(session, tenant_context.tenant_id)
            tenant = await tenant_crud.require_by_id(session, tenant_context.tenant_id)

        if not product.is_published or not product.is_active:
            raise InvalidInputError(
                operation="share_product",
                entity="product",
                detail="publish this product before sharing it; the link would open nothing",
            )
        if shop is None or not shop.is_open():
            raise InvalidInputError(
                operation="share_product",
                entity="storefront",
                detail="open the shop before sharing a product; the address answers nothing yet",
            )

        phone = shop.contact_phone or tenant.phone
        whatsapp_number = (
            international_digits_for(phone, default_country_code=self._default_country_code)
            if phone
            else None
        )
        return ProductShareTarget(
            business_name=tenant.name,
            product_name=product.name,
            product_slug=product.slug,
            public_path=f"/shop/{tenant.slug}/product/{product.slug}",
            price_text=_optional_money_text(await self._effective_normal_price(session, product)),
            whatsapp_number=whatsapp_number,
            whatsapp_unavailable_reason=(
                None
                if whatsapp_number
                else "this shop has no contact number a customer can message"
            ),
        )

    async def read_public_product(self, *, tenant_slug: str, product_slug: str) -> PublicProduct:
        """Return one published product of a published shop, for a caller with no identity.

        Resolve, then read within the scope, for the same reason the shop itself is read that way:
        the slug is the only address a stranger has, and the policies are what stop that address
        from becoming a way to read another business's rows.
        """
        self._require_publishing_enabled(operation="read_public_product")
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            tenant = await tenant_crud.get_by_slug(unit_of_work.session_handle, tenant_slug)
            if tenant is None or not tenant.is_active:
                raise self._closed_shop(tenant_slug)
            resolved_tenant_id = tenant.id

        with tenant_scope(resolved_tenant_id):
            unit_of_work = self._unit_of_work_factory()
            async with unit_of_work:
                session = unit_of_work.session_handle
                shop = await storefront_crud.get_for_tenant(session, resolved_tenant_id)
                if shop is None or not shop.is_open():
                    raise self._closed_shop(tenant_slug)
                product = await product_crud.get_by_slug(
                    session, tenant_id=resolved_tenant_id, slug=product_slug
                )
                if product is None or not product.is_published or not product.is_active:
                    raise NotFoundError(
                        operation="read_public_product",
                        entity="product",
                        identifier=product_slug,
                        detail="no published product matches that address in this shop",
                    )
                return await self._public_product(
                    session, tenant_id=resolved_tenant_id, product=product
                )

    async def _effective_normal_price(
        self,
        session: object,
        product: ProductModel,
    ) -> Decimal | None:
        """Return what a stranger is shown as this item's price.

        The item's own price if it has one, otherwise its group's - the same rule the counter and a
        list use, resolved from the side a browsing customer sees. None is possible and is not
        hidden: an item nobody has priced cannot be shown to a customer at a price, and pretending
        otherwise would put a figure on the shop page that the trader never chose.
        """
        if product.selling_price is not None:
            return product.selling_price
        if product.category_id is None:
            return None
        group = await category_crud.get_by_id(
            session,  # type: ignore[arg-type]
            tenant_id=product.tenant_id,
            category_id=product.category_id,
        )
        if group is None:
            return None
        return group.price_defaults().normal_price

    async def _public_product(
        self,
        session: object,
        *,
        tenant_id: UUID,
        product: ProductModel,
    ) -> PublicProduct:
        """Build one product's public projection from an allowlist of fields.

        The allowlist is the point: `cost_price`, the stock count, the internal identifier and the
        publication token are not removed from this object, they are never added to it. A field
        nobody thought about therefore cannot appear here by default.
        """
        # No stock read at all: it was fetched, used to fill a field that then stopped being sent,
        # and left behind as a query per product on every visit. The allowlist above says the stock
        # count is never added to this object, and now nothing fetches it either.
        images = await product_image_crud.list_for_product(
            session,  # type: ignore[arg-type]
            tenant_id=tenant_id,
            product_id=product.id,
        )
        primary = _primary_image(images)
        group = None
        group_default_price = None
        if product.category_id is not None:
            found = await category_crud.get_by_id(
                session,  # type: ignore[arg-type]
                tenant_id=tenant_id,
                category_id=product.category_id,
            )
            if found is not None:
                group = found.name
                group_default_price = found.price_defaults().normal_price
        # An exception carries its own price and it differs from the group's. An
        # item with no price of its own inherits, and inheriting is the ordinary case.
        is_special = (
            product.selling_price is not None and product.selling_price != group_default_price
        )
        return PublicProduct(
            product_slug=product.slug,
            name=product.name,
            selling_price=await self._effective_normal_price(session, product),
            description=product.description,
            primary_image_url=(await self._images.build_delivery_url(primary) if primary else None),
            group_name=group,
            is_special=is_special,
        )

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def _require_publishing_enabled(self, *, operation: str) -> None:
        """Refuse as if the capability did not exist while the release flag is off."""
        if not self._publishing_enabled:
            raise NotFoundError(
                operation=operation,
                entity="storefront",
                detail="public storefronts are not enabled in this deployment",
            )

    def _closed_shop(self, tenant_slug: str) -> NotFoundError:
        return NotFoundError(
            operation="read_public_storefront",
            entity="storefront",
            identifier=tenant_slug,
            detail="no open shop matches that address",
        )

    def _canonical_or_refuse(self, phone: str | None, *, operation: str) -> str | None:
        """Return the E.164 form of a contact number, or refuse it here rather than in the entity.

        `canonical_phone_number` completes a number; it does not judge one. A value that survives
        normalisation but could not be dialled - letters, too few digits - is refused at this
        boundary, so the caller gets a field-level error rather than an entity invariant that
        reads like a defect in this product.
        """
        if phone is None:
            return None
        canonical = canonical_phone_number(phone, default_country_code=self._default_country_code)
        if canonical is None or not is_plausible_phone_number(canonical):
            raise InvalidInputError(
                operation=operation,
                entity="storefront",
                detail="contact_phone is not a phone number this product can dial",
            )
        return canonical


def _optional_money_text(amount: Decimal | None) -> str | None:
    """Format a price that may not exist, because an item can follow a group nobody priced
    either."""
    return None if amount is None else money_text(amount)


def _primary_image(images: list[ProductImageModel]) -> ProductImageModel | None:
    """Return the picture a customer should see, or None.

    The cover the business chose, else the first one it arranged. Removed pictures are already
    excluded by the reader, so a shop never advertises something a business took down.
    """
    for image in images:
        if image.is_primary:
            return image
    return images[0] if images else None


def _optional_text(changes: Mapping[str, Any], field_name: str) -> str | None:
    value = changes[field_name]
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidInputError(
            operation="update_storefront",
            entity="storefront",
            detail=f"{field_name} must be text or null",
        )
    return value.strip() or None
