"""Share link use cases: minting a link, revoking it, and what it opens.

**The token is generated here, returned once, and never stored.** `create_share_link` mints a
non-guessable token with the token service, hands its digest to the entity and returns the
plaintext to the caller in the same response. Nothing writes the plaintext anywhere: no log line,
no column, no audit detail. A business that loses the link asks for a new one, which is the
correct answer - a system that can re-show a link is a system that stored it.

**Revocation is available to the business that created the link, and it is permanent.** A link
sent to the wrong number is stopped, and the row that recorded it stays so that "this invoice was
shared and then withdrawn" can be answered. Re-sharing mints a new link rather than reviving the
old one, so the withdrawn address never works again.

**What a link opens is a public projection, built from an allowlist.** For an invoice that is the
business's name and contact number, the receipt number, the moment of the sale, its lines and its
totals - and deliberately not the customer's name or phone number. The person holding an invoice
link already knows who they are; putting a customer's identity behind a bearer token would turn a
shared receipt into a place where personal data travels by link.

**Reading needs no identity, and the permission to share is the resource's own.** Creating an
invoice link needs `sales.read`, because somebody who may not read a sale may not publish it to the
internet. A map from resource type to read permission is declared once, so a new shareable resource
cannot be added without deciding who may share it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.errors import AuthorizationError, InvalidInputError, NotFoundError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions.report_permissions import REPORTS_READ
from ahia.core.permissions.sales_permissions import SALES_READ
from ahia.core.security import TokenService
from ahia.core.tenant_context import TenantContext
from ahia.crud import (
    report_export_crud,
    sale_crud,
    sale_item_crud,
    share_link_crud,
    storefront_crud,
    tenant_crud,
)
from ahia.models.entities.report_export_model import ReportExportModel
from ahia.models.entities.sale_item_model import SaleItemModel
from ahia.models.entities.sale_model import SaleModel
from ahia.models.entities.share_link_model import (
    DEFAULT_LIFETIME,
    MAXIMUM_LIFETIME,
    MINIMUM_LIFETIME,
    ShareableResource,
    ShareLinkModel,
)
from ahia.services.audit_event_service import AuditEventService

_SHARE_LINK_LOGGER_NAME: Final[str] = "ahia.services.share_link"

#: Who may share what. The resource's own read permission: somebody who may not read a record may
#: not publish it to the internet either, and a new shareable resource has to be classified here
#: before it can be shared at all.
READ_PERMISSION_FOR_RESOURCE: Final[dict[ShareableResource, str]] = {
    ShareableResource.INVOICE: SALES_READ,
    ShareableResource.REPORT: REPORTS_READ,
}


@dataclass(frozen=True, slots=True)
class IssuedShareLink:
    """A link that was just minted, and the token that opens it.

    The plaintext token is here and nowhere else. It is returned once, and a caller that loses it
    asks for a new link: this object is the only place it exists after the request ends.
    """

    link: ShareLinkModel
    token: str

    @property
    def public_path(self) -> str:
        return f"/share/{self.token}"


@dataclass(frozen=True, slots=True)
class SharedInvoiceLine:
    """One line of a shared invoice, as the person holding the link sees it."""

    product_name: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


@dataclass(frozen=True, slots=True)
class SharedInvoice:
    """An invoice opened through a link.

    No customer identity and no internal identifiers: the receipt number is what a person quotes,
    and everything a customer would recognise is a fact about the sale rather than about them.
    """

    business_name: str
    business_contact_phone: str | None
    receipt_number: str
    occurred_at: datetime
    subtotal: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    lines: tuple[SharedInvoiceLine, ...]


class ShareLinkService:
    """Share link use cases."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        token_service: TokenService,
        audit_event_service: AuditEventService,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._tokens = token_service
        self._audit = audit_event_service
        self._logger = (logger or get_logger(_SHARE_LINK_LOGGER_NAME)).bind(
            component="share_link_service", layer="service"
        )

    # ------------------------------------------------------------------
    # Minting and revoking
    # ------------------------------------------------------------------

    async def share_invoice(
        self,
        tenant_context: TenantContext,
        *,
        sale_id: UUID,
        lifetime: timedelta = DEFAULT_LIFETIME,
    ) -> IssuedShareLink:
        """Mint a link that opens one sale as an invoice."""
        self._require_permission(
            tenant_context, resource_type=ShareableResource.INVOICE, operation="share_invoice"
        )
        if lifetime < MINIMUM_LIFETIME or lifetime > MAXIMUM_LIFETIME:
            raise InvalidInputError(
                operation="share_invoice",
                entity="share_link",
                detail=(
                    f"lifetime must be between {MINIMUM_LIFETIME} and {MAXIMUM_LIFETIME}; a link "
                    "that never expires is a permanent public address for a customer's purchases"
                ),
            )

        token = self._tokens.generate_public_token()
        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            # The sale is loaded first: a link to a sale that does not exist in this business
            # would be a public address that answers "not found" forever, and minting it would
            # look like success.
            sale = await self._require_sale(session, tenant_context=tenant_context, sale_id=sale_id)
            link = await share_link_crud.create(
                session,
                ShareLinkModel.issue(
                    link_id=uuid4(),
                    tenant_id=tenant_context.tenant_id,
                    resource_type=ShareableResource.INVOICE,
                    resource_id=sale.id,
                    token_hash=self._tokens.hash_bearer_token(token),
                    now=now,
                    lifetime=lifetime,
                    created_by_user_id=tenant_context.user_id,
                ),
            )
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="share_invoice",
                entity_type="share_link",
                entity_id=link.id,
                now=now,
                detail=link.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.info(
            "share_link_created",
            **link.describe_for_audit(),
            actor_id=str(tenant_context.user_id),
        )
        return IssuedShareLink(link=link, token=token)

    async def revoke_share_link(
        self,
        tenant_context: TenantContext,
        *,
        share_link_id: UUID,
    ) -> ShareLinkModel:
        """Stop a link from opening anything, permanently."""
        share_link = await self._require_link(tenant_context, share_link_id=share_link_id)
        self._require_permission(
            tenant_context,
            resource_type=share_link.resource_type,
            operation="revoke_share_link",
        )

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            revoked = await share_link_crud.update(session, share_link.revoked(at=now))
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="revoke_share_link",
                entity_type="share_link",
                entity_id=revoked.id,
                now=now,
                detail=revoked.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.warning(
            "share_link_revoked",
            **revoked.describe_for_audit(),
            actor_id=str(tenant_context.user_id),
            security_event="share_link_revoked",
        )
        return revoked

    async def list_links_for_invoice(
        self,
        tenant_context: TenantContext,
        *,
        sale_id: UUID,
    ) -> list[ShareLinkModel]:
        """Return the links a sale has been shared through, so a business can revoke one."""
        self._require_permission(
            tenant_context, resource_type=ShareableResource.INVOICE, operation="list_share_links"
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await share_link_crud.list_for_resource(
                unit_of_work.session_handle,
                tenant_id=tenant_context.tenant_id,
                resource_type=ShareableResource.INVOICE,
                resource_id=sale_id,
            )

    # ------------------------------------------------------------------
    # What a link opens
    # ------------------------------------------------------------------

    async def read_shared_invoice(self, *, token: str) -> SharedInvoice:
        """Return the invoice a token opens, for a caller with no account.

        Every refusal is the same not-found: an unknown token, a revoked link, an expired link and
        a sale that no longer exists are indistinguishable to the person holding the link, and the
        difference between them is not theirs to learn.
        """
        token_hash = self._tokens.hash_bearer_token(token)
        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            link = await share_link_crud.get_by_token_hash(session, token_hash)
            if link is None or not link.opens(at=now):
                if link is not None:
                    # Logged for the operator and invisible to the holder: a revoked link being
                    # tried is worth knowing about, and saying so in the response would confirm
                    # that the token was once real.
                    self._logger.warning(
                        "share_link_refused",
                        share_link_id=str(link.id),
                        tenant_id=str(link.tenant_id),
                        is_revoked=link.is_revoked(),
                        is_expired=link.is_expired(at=now),
                        security_event="share_link_refused",
                    )
                raise self._unopenable()

            sale = await sale_crud.get_by_id(
                session, tenant_id=link.tenant_id, sale_id=link.resource_id
            )
            if sale is None:
                raise self._unopenable()
            items = await sale_item_crud.list_for_sale(
                session, tenant_id=link.tenant_id, sale_id=sale.id
            )
            business = await self._business_details(session, tenant_id=link.tenant_id)

        return _invoice_from(
            sale=sale,
            items=items,
            business_name=business.name,
            business_contact_phone=business.contact_phone,
        )

    async def share_report(
        self,
        tenant_context: TenantContext,
        *,
        report_export_id: UUID,
        lifetime: timedelta = DEFAULT_LIFETIME,
    ) -> IssuedShareLink:
        """Mint a link that opens one exported report.

        The export must exist and be available: a link to an export whose upload failed opens
        nothing, and minting it would look like success. This is the same refusal the invoice path
        makes for a sale that does not exist.
        """
        self._require_permission(
            tenant_context,
            resource_type=ShareableResource.REPORT,
            operation="share_report",
        )
        if lifetime < MINIMUM_LIFETIME or lifetime > MAXIMUM_LIFETIME:
            raise InvalidInputError(
                operation="share_report",
                entity="share_link",
                detail=(
                    f"lifetime must be between {MINIMUM_LIFETIME} and {MAXIMUM_LIFETIME}; a link "
                    "that never expires is a permanent public address for a business's numbers"
                ),
            )

        token = self._tokens.generate_public_token()
        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            export = await report_export_crud.get_for_tenant(
                session, tenant_id=tenant_context.tenant_id, export_id=report_export_id
            )
            if export is None or not export.is_available():
                raise NotFoundError(
                    operation="share_report",
                    entity="report_export",
                    identifier=str(report_export_id),
                    detail="no available report export matched in this business",
                )
            link = await share_link_crud.create(
                session,
                ShareLinkModel.issue(
                    link_id=uuid4(),
                    tenant_id=tenant_context.tenant_id,
                    resource_type=ShareableResource.REPORT,
                    resource_id=export.id,
                    token_hash=self._tokens.hash_bearer_token(token),
                    now=now,
                    lifetime=lifetime,
                    created_by_user_id=tenant_context.user_id,
                ),
            )
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="share_report",
                entity_type="share_link",
                entity_id=link.id,
                now=now,
                detail=link.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.info(
            "share_link_created",
            **link.describe_for_audit(),
            actor_id=str(tenant_context.user_id),
        )
        return IssuedShareLink(link=link, token=token)

    async def read_shared_report(self, *, token: str) -> ReportExportModel:
        """Return the export a token opens, for a caller with no account.

        The caller receives where the bytes are, not the bytes: the API redirects to the object
        store, so a report never travels through the application process and the delivery URL is the
        provider's own, short-lived one.
        """
        return await self._read_shared(token=token, expected=ShareableResource.REPORT)

    async def _read_shared(self, *, token: str, expected: ShareableResource) -> ReportExportModel:
        token_hash = self._tokens.hash_bearer_token(token)
        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            link = await share_link_crud.get_by_token_hash(session, token_hash)
            if link is None or not link.opens(at=now) or link.resource_type is not expected:
                if link is not None:
                    self._logger.warning(
                        "share_link_refused",
                        share_link_id=str(link.id),
                        tenant_id=str(link.tenant_id),
                        resource_type=link.resource_type.value,
                        is_revoked=link.is_revoked(),
                        is_expired=link.is_expired(at=now),
                        security_event="share_link_refused",
                    )
                raise self._unopenable()
            export = await report_export_crud.get_for_tenant(
                session, tenant_id=link.tenant_id, export_id=link.resource_id
            )
            if export is None or not export.is_available():
                raise self._unopenable()
        return export

    # ------------------------------------------------------------------
    # Guards and readers
    # ------------------------------------------------------------------

    def _require_permission(
        self,
        tenant_context: TenantContext,
        *,
        resource_type: ShareableResource,
        operation: str,
    ) -> None:
        permission = READ_PERMISSION_FOR_RESOURCE.get(resource_type)
        if permission is None:
            # Unreachable while the closed set and the map agree, which a test asserts. It exists so
            # adding a resource type without deciding who may share it fails loudly here rather
            # than silently allowing everybody.
            raise AuthorizationError(
                operation=operation,
                entity="share_link",
                detail=f"no share permission is declared for {resource_type.value}",
            )
        tenant_context.require_permission(
            permission,
            operation=operation,
            resource_type="share_link",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )

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
            raise NotFoundError(
                operation="share_invoice",
                entity="sale",
                identifier=str(sale_id),
                detail="no sale matched in this business",
            )
        return sale

    async def _require_link(
        self, tenant_context: TenantContext, *, share_link_id: UUID
    ) -> ShareLinkModel:
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            link = await share_link_crud.get_for_tenant(
                unit_of_work.session_handle,
                tenant_id=tenant_context.tenant_id,
                share_link_id=share_link_id,
            )
        if link is None:
            raise NotFoundError(
                operation="revoke_share_link",
                entity="share_link",
                identifier=str(share_link_id),
                detail="no share link matched in this business",
            )
        return link

    async def _business_details(self, session: object, *, tenant_id: UUID) -> _BusinessDetails:
        """Return the shop's name and the number a customer holding the invoice should call.

        The storefront's published contact number if the business opened a shop and gave one, and
        the business's own number otherwise: an invoice with no way to reach the seller is a
        receipt a customer cannot question.
        """
        tenant = await tenant_crud.require_by_id(
            session,  # type: ignore[arg-type]
            tenant_id,
        )
        shop = await storefront_crud.get_for_tenant(
            session,  # type: ignore[arg-type]
            tenant_id,
        )
        contact_phone = (shop.contact_phone if shop else None) or tenant.phone
        return _BusinessDetails(name=tenant.name, contact_phone=contact_phone)

    def is_open(self, link: ShareLinkModel) -> bool:
        """Return True when a link still opens its record.

        Exposed as a method rather than left to a caller to compute: the rule is the entity's, and a
        transport layer that re-derived it would be a second implementation that can disagree.
        """
        return link.opens(at=datetime.now(UTC))

    def _unopenable(self) -> NotFoundError:
        return NotFoundError(
            operation="read_shared_invoice",
            entity="share_link",
            detail="this link does not open anything",
        )


@dataclass(frozen=True, slots=True)
class _BusinessDetails:
    """The bits of a business an invoice shows: its name, and a number to call."""

    name: str
    contact_phone: str | None


def _invoice_from(
    *,
    sale: SaleModel,
    items: list[SaleItemModel],
    business_name: str,
    business_contact_phone: str | None,
) -> SharedInvoice:
    return SharedInvoice(
        business_name=business_name,
        business_contact_phone=business_contact_phone,
        receipt_number=sale.receipt_number,
        occurred_at=sale.occurred_at,
        subtotal=sale.subtotal,
        discount_amount=sale.discount_amount,
        total_amount=sale.total_amount,
        lines=tuple(
            SharedInvoiceLine(
                product_name=item.product_name_snapshot,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
            )
            for item in items
        ),
    )
