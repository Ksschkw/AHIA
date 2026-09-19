"""Lists: what a customer asks for, and what the trader does about it.

A list is not a sale. Nothing here moves stock, writes to the ledger or issues a receipt - those
happen
when the trader confirms it, which is a decision only he can make, because he sources some of it
from his
shelf and some of it from the market that morning.

Two sides of one thing:

- **A customer sends a list**, with no account. They are identified by their phone number, which is
the
  only thing asked of them, and which is what makes their next list start from their last one
  instead of
  from nothing.
- **The trader sees it**, prices it, sources it, and decides what it comes to. The app does his
arithmetic
  and never argues with him.

Nothing in the customer's half returns anything about the shop's own affairs: not stock, not
margins, not
whether an item is on a shelf. An Igbo trader is never truly out of stock - he goes and finds it -
and a
customer reading "unavailable" is a customer who takes his list elsewhere.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.errors import InvalidInputError, NotFoundError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions import sales_permissions
from ahia.core.security import TokenService
from ahia.core.tenant_context import TenantContext
from ahia.crud import product_crud, request_crud, request_line_crud, storefront_crud, tenant_crud
from ahia.models.entities.request_line_model import RequestLineModel
from ahia.models.entities.request_model import RequestModel, RequestStatus
from ahia.schemas.money_format import money_text, quantity_text
from ahia.schemas.request_schema import (
    DispatchSchema,
    PublicListLineSchema,
    PublicListSchema,
    PublicRequestSchema,
    RequestLineResponseSchema,
    RequestLineWorkSchema,
    RequestResponseSchema,
)
from ahia.services.audit_event_service import AuditEventService

_REQUEST_LOGGER_NAME: Final[str] = "ahia.services.request"

#: The longest edge of a list, so one customer cannot fill a database with one request.
MAXIMUM_LINES_PER_LIST: Final[int] = 200


def _text_or_none(value: str | None) -> str | None:
    """Return what was typed, or None when nothing was.

    Whitespace is not a transporter's name: a form submitted with spaces in a box means the box was
    left empty, and storing spaces would make a screen show a blank where it should show nothing.
    """
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def request_response(
    request: RequestModel,
    lines: list[RequestLineModel],
) -> RequestResponseSchema:
    """Shape one list and its lines for the trader.

    The total is None while nothing is priced, and the count of unpriced lines travels with it: a
    figure
    that quietly leaves out what nobody has priced is worse than no figure at all, and the screen
    says
    "to be priced" instead.
    """
    unpriced = sum(1 for line in lines if not line.is_priced)
    priced = [line.line_total for line in lines if line.line_total is not None]
    return RequestResponseSchema(
        id=request.id,
        customer_phone=request.customer_phone,
        customer_name=request.customer_name,
        status=request.status,
        note=request.note,
        created_at=request.created_at,
        transporter_name=request.transporter_name,
        transporter_phone=request.transporter_phone,
        waybill_number=request.waybill_number,
        dispatch_cost=(
            None if request.dispatch_cost is None else money_text(request.dispatch_cost)
        ),
        tracking_url=request.tracking_url,
        dispatched_at=request.dispatched_at,
        unpriced_line_count=unpriced,
        priced_total=money_text(sum(priced, Decimal("0.00"))) if priced else None,
        lines=[
            RequestLineResponseSchema(
                id=line.id,
                position=line.position,
                product_id=line.product_id,
                free_text=line.free_text,
                note=line.note,
                quantity=quantity_text(line.quantity),
                unit=line.unit,
                pieces_per_pack=line.pieces_per_pack,
                pieces=quantity_text(line.pieces),
                customer_price=(
                    None if line.customer_price is None else money_text(line.customer_price)
                ),
                shop_price=None if line.shop_price is None else money_text(line.shop_price),
                cost_price=None if line.cost_price is None else money_text(line.cost_price),
                line_total=None if line.line_total is None else money_text(line.line_total),
                margin=(
                    None
                    if line.cost_price is None or line.line_total is None
                    else money_text(line.line_total - line.cost_price * line.pieces)
                ),
                state=line.state,
                image_key=line.image_key,
            )
            for line in lines
        ],
    )


class RequestService:
    """Customer lists, from the moment they arrive."""

    def __init__(
        self,
        unit_of_work_factory: Callable[[], UnitOfWork],
        token_service: TokenService,
        default_phone_country_code: str = "+234",
        audit_event_service: AuditEventService | None = None,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        #: What he did with a list is a business change and belongs in the trail. A customer's own
        # : submission has no authenticated actor to attribute it to, so it is written to the
        # structured
        # : security log with its correlation id instead - the arrangement authentication already
        # uses,
        #: because it too happens before a business is chosen.
        self._audit = audit_event_service or AuditEventService(
            unit_of_work_factory=unit_of_work_factory
        )
        self._default_country_code = default_phone_country_code
        # : The same token service share links use: a list's address is a credential, and the
        # database
        #: keeps only its digest, so a leak of the table is not a leak of everybody's lists.
        self._tokens = token_service
        self._logger = (logger or get_logger(_REQUEST_LOGGER_NAME)).bind(
            component="request_service", layer="service"
        )

    # ------------------------------------------------------------------
    # What a customer does: no session, no account
    # ------------------------------------------------------------------

    async def submit_customer_list(
        self,
        *,
        tenant_slug: str,
        payload: PublicRequestSchema,
    ) -> tuple[RequestModel, int, str]:
        """Take a list from somebody with no account, and say only that it arrived.

        The shop's public address has to be open, because a link that answers nothing is a link that
        teaches a customer not to bother. Everything else about the shop stays out of the answer:
        the
        customer is told their list arrived, and nothing that is the trader's business.
        """
        now = datetime.now(UTC)
        request_id = uuid4()
        # The list gets its own address the moment it exists, because the customer will close the
        # page:
        # the link is how they come back to it and how the trader opens the same one.
        list_token = self._tokens.generate_public_token()

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle

            tenant = await tenant_crud.get_by_slug(session, tenant_slug)
            if tenant is None:
                raise NotFoundError(
                    operation="submit_customer_list",
                    entity="storefront",
                    identifier=tenant_slug,
                    detail="no shop answers at that address",
                )

            shop = await storefront_crud.get_for_tenant(session, tenant.id)
            if shop is None or not shop.is_open():
                raise InvalidInputError(
                    operation="submit_customer_list",
                    entity="storefront",
                    identifier=tenant_slug,
                    detail="this shop is not taking lists at the moment",
                )

            request = RequestModel.submitted_by_customer(
                request_id=request_id,
                tenant_id=tenant.id,
                customer_phone=payload.customer_phone,
                customer_name=payload.customer_name,
                note=payload.note,
                default_country_code=self._default_country_code,
                public_token_digest=self._tokens.hash_bearer_token(list_token),
                now=now,
            )

            lines = await self._build_lines(
                session,
                tenant_id=tenant.id,
                request_id=request_id,
                payload=payload,
                now=now,
            )
            await request_crud.create(session, request)
            stored_lines = await request_line_crud.create_many(session, lines)
            await unit_of_work.commit()

        self._logger.info(
            "customer_list_received",
            tenant_id=str(tenant.id),
            request_id=str(request.id),
            line_count=len(stored_lines),
        )
        return request, len(stored_lines), list_token

    async def _build_lines(
        self,
        session: object,
        *,
        tenant_id: UUID,
        request_id: UUID,
        payload: PublicRequestSchema,
        now: datetime,
    ) -> list[RequestLineModel]:
        """Turn what was sent into lines, checking that catalogued items are this shop's own.

        A line naming another business's product is refused rather than stored, because a list that
        references something the shop cannot see is a list nobody can act on - and it is also the
        shape
        of an attempt to read across tenants.
        """
        if len(payload.lines) > MAXIMUM_LINES_PER_LIST:
            raise InvalidInputError(
                operation="submit_customer_list",
                entity="request",
                identifier=str(request_id),
                detail=f"a list may hold at most {MAXIMUM_LINES_PER_LIST} lines",
            )

        lines: list[RequestLineModel] = []
        for position, line in enumerate(payload.lines):
            product_id: UUID | None = None
            free_text = line.free_text
            if line.product_slug is not None:
                # The slug is resolved **inside this shop's own catalogue**, so a line can only ever
                # name
                # something this business sells - which is both a correctness rule and the shape of
                # an
                # attempt to read across tenants.
                product = await product_crud.get_by_slug(
                    session,  # type: ignore[arg-type]
                    tenant_id=tenant_id,
                    slug=line.product_slug,
                )
                if product is None:
                    raise InvalidInputError(
                        operation="submit_customer_list",
                        entity="request_line",
                        identifier=line.product_slug,
                        detail="that item is not in this shop's catalogue",
                    )
                product_id = product.id
            if product_id is None and free_text is None:
                free_text = "Something the shop does not list yet"

            unit = line.unit
            pieces_per_pack = line.pieces_per_pack
            lines.append(
                RequestLineModel(
                    id=uuid4(),
                    request_id=request_id,
                    tenant_id=tenant_id,
                    position=position,
                    quantity=line.quantity if line.quantity > Decimal("0") else Decimal("1"),
                    unit=unit,
                    product_id=product_id,
                    free_text=free_text,
                    note=line.note,
                    pieces_per_pack=pieces_per_pack,
                    customer_price=line.customer_price,
                    image_key=line.image_key,
                    created_at=now,
                )
            )
        return lines

    async def read_public_list(self, *, list_token: str) -> PublicListSchema:
        """Return a list to whoever holds its address.

        No session, no tenant, no permissions: the token **is** the authority, exactly as a share
        link is.
        The database holds only its digest, so a leak of the table is not a leak of everybody's
        lists, and
        what comes back is the customer's view - their lines, the shop's prices, and nothing about
        what
        the goods cost the trader.
        """
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            request = await request_crud.get_by_token_digest(
                session, token_digest=self._tokens.hash_bearer_token(list_token)
            )
            if request is None:
                raise NotFoundError(
                    operation="read_public_list",
                    entity="request",
                    identifier="list",
                    detail="no list answers at that address",
                )
            lines = await request_line_crud.list_for_request(
                session, tenant_id=request.tenant_id, request_id=request.id
            )
            tenant = await tenant_crud.get_by_id(session, request.tenant_id)

        priced = [line.line_total for line in lines if line.line_total is not None]
        return PublicListSchema(
            business_name=tenant.name if tenant is not None else "",
            tenant_slug=tenant.slug if tenant is not None else "",
            status=request.status,
            created_at=request.created_at,
            unpriced_line_count=sum(1 for line in lines if not line.is_priced),
            priced_total=money_text(sum(priced, Decimal("0.00"))) if priced else None,
            lines=[
                PublicListLineSchema(
                    position=line.position,
                    text=line.free_text or "From the shop",
                    group=line.note,
                    quantity=quantity_text(line.quantity),
                    pieces=quantity_text(line.pieces),
                    shop_price=None if line.shop_price is None else money_text(line.shop_price),
                    line_total=None if line.line_total is None else money_text(line.line_total),
                    state=line.state,
                )
                for line in lines
            ],
        )

    # ------------------------------------------------------------------
    # What the trader does
    # ------------------------------------------------------------------

    async def read_request(
        self,
        tenant_context: TenantContext,
        *,
        request_id: UUID,
    ) -> RequestResponseSchema:
        """Return one list with its lines, or refuse as if it did not exist."""
        tenant_context.require_permission(
            sales_permissions.SALES_READ,
            operation="read_request",
            resource_type="request",
            resource_id=str(request_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            request = await request_crud.require_by_id(
                session, tenant_id=tenant_context.tenant_id, request_id=request_id
            )
            lines = await request_line_crud.list_for_request(
                session, tenant_id=tenant_context.tenant_id, request_id=request_id
            )
        return request_response(request, lines)

    async def as_response(
        self,
        tenant_context: TenantContext,
        *,
        request: RequestModel,
    ) -> RequestResponseSchema:
        """Return one list with its lines, for a caller already allowed to see it."""
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            lines = await request_line_crud.list_for_request(
                unit_of_work.session_handle,
                tenant_id=tenant_context.tenant_id,
                request_id=request.id,
            )
        return request_response(request, lines)

    async def list_requests(
        self,
        tenant_context: TenantContext,
        *,
        limit: int = 100,
    ) -> list[RequestModel]:
        """Return this business's lists, newest first."""
        tenant_context.require_permission(
            sales_permissions.SALES_READ,
            operation="list_requests",
            resource_type="request",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await request_crud.list_for_tenant(
                unit_of_work.session_handle, tenant_context.tenant_id, limit=limit
            )

    async def work_line(
        self,
        tenant_context: TenantContext,
        *,
        request_id: UUID,
        line_id: UUID,
        changes: RequestLineWorkSchema,
    ) -> RequestResponseSchema:
        """Record what he did with one line: where he got it, what it cost, what he charges.

        All of it in one call because it is one action at a counter - he picks the thing up,
        decides, and
        types the price. Three round trips for one decision would make the screen unusable in the
        market,
        where the connection is the reason he is standing there.
        """
        tenant_context.require_permission(
            sales_permissions.SALES_CREATE,
            operation="work_request_line",
            resource_type="request_line",
            resource_id=str(line_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            request = await request_crud.require_by_id(
                session, tenant_id=tenant_context.tenant_id, request_id=request_id
            )
            if request.is_confirmed:
                raise InvalidInputError(
                    operation="work_request_line",
                    entity="request",
                    identifier=str(request_id),
                    detail="this list is already a sale; a change to it is a return, not an edit",
                )
            line = await request_line_crud.require_by_id(
                session,
                tenant_id=tenant_context.tenant_id,
                line_id=line_id,
                request_id=request_id,
            )
            sent = changes.model_fields_set
            if {"state", "cost_price"} & sent:
                line = line.sourced_for(
                    cost_price=changes.cost_price if "cost_price" in sent else line.cost_price,
                    state=changes.state if changes.state is not None else line.state,
                )
            if "shop_price" in sent and changes.shop_price is not None:
                line = line.priced_at(unit_price=changes.shop_price)
            stored = await request_line_crud.update(session, line)
            lines = await request_line_crud.list_for_request(
                session, tenant_id=tenant_context.tenant_id, request_id=request_id
            )
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="request_line_worked",
                entity_type="request_line",
                entity_id=stored.id,
                now=datetime.now(UTC),
                detail={
                    "request_id": str(request_id),
                    "state": stored.state.value,
                    "priced": "yes" if stored.is_priced else "no",
                },
            )
            await unit_of_work.commit()

        self._logger.info(
            "request_line_worked",
            tenant_id=str(tenant_context.tenant_id),
            request_id=str(request_id),
            line_id=str(stored.id),
            state=stored.state.value,
        )
        return request_response(request, lines)

    async def dispatch_request(
        self,
        tenant_context: TenantContext,
        *,
        request_id: UUID,
        payload: DispatchSchema,
    ) -> RequestResponseSchema:
        """Record how a list was sent.

        Only a confirmed list can be dispatched, which is a rule rather than a formality: sending
        goods before the price is agreed is how a trader ends up owed money he never named. What it
        cost to send is kept beside what the list made, because the difference between the two is
        the day's real answer.
        """
        tenant_context.require_permission(
            sales_permissions.SALES_CREATE,
            operation="dispatch_request",
            resource_type="request",
            resource_id=str(request_id),
            logger=self._logger,
        )
        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            request = await request_crud.require_by_id(
                session, tenant_id=tenant_context.tenant_id, request_id=request_id
            )
            if request.status is not RequestStatus.CONFIRMED:
                raise InvalidInputError(
                    operation="dispatch_request",
                    entity="request",
                    identifier=str(request_id),
                    detail="a list must be confirmed before it can be sent",
                )
            dispatched = request.dispatched(
                transporter_name=_text_or_none(payload.transporter_name),
                transporter_phone=_text_or_none(payload.transporter_phone),
                waybill_number=_text_or_none(payload.waybill_number),
                dispatch_cost=payload.dispatch_cost,
                tracking_url=_text_or_none(payload.tracking_url),
                at=now,
            )
            stored = await request_crud.update(session, dispatched)
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="request_dispatched",
                entity_type="request",
                entity_id=stored.id,
                now=now,
                detail={
                    "waybill_number": stored.waybill_number or "",
                    "has_tracking": "yes" if stored.tracking_url else "no",
                },
            )
            lines = await request_line_crud.list_for_request(
                session, tenant_id=tenant_context.tenant_id, request_id=request_id
            )
            await unit_of_work.commit()

        self._logger.info(
            "request_dispatched",
            tenant_id=str(tenant_context.tenant_id),
            request_id=str(request_id),
        )
        return request_response(stored, lines)

    async def confirm_request(
        self,
        tenant_context: TenantContext,
        *,
        request_id: UUID,
    ) -> RequestResponseSchema:
        """Turn a list into a sale - the one moment money exists.

        Refused while any line is unpriced, because a total with holes in it is not an agreement,
        and
        confirming one would write a sale nobody agreed to. The trader can still confirm a list he
        never
        priced line by line by pricing every line to zero, which is his business.
        """
        tenant_context.require_permission(
            sales_permissions.SALES_CREATE,
            operation="confirm_request",
            resource_type="request",
            resource_id=str(request_id),
            logger=self._logger,
        )
        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            request = await request_crud.require_by_id(
                session, tenant_id=tenant_context.tenant_id, request_id=request_id
            )
            lines = await request_line_crud.list_for_request(
                session, tenant_id=tenant_context.tenant_id, request_id=request_id
            )
            unpriced = [line for line in lines if not line.is_priced]
            if unpriced:
                raise InvalidInputError(
                    operation="confirm_request",
                    entity="request",
                    identifier=str(request_id),
                    detail=(
                        f"{len(unpriced)} line(s) have no price; price them first, "
                        "because a total with holes is not an agreement"
                    ),
                )
            confirmed = await request_crud.update(session, request.confirmed(at=now))
            # The moment a list becomes a sale is the change most in need of a record: it is the
            # one that creates money, and it is written in the same transaction as the change, so
            # the two cannot disagree.
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="request_confirmed",
                entity_type="request",
                entity_id=confirmed.id,
                now=now,
                detail={"line_count": str(len(lines))},
            )
            await unit_of_work.commit()

        self._logger.info(
            "request_confirmed",
            tenant_id=str(tenant_context.tenant_id),
            request_id=str(request_id),
            line_count=len(lines),
        )
        return request_response(confirmed, lines)
