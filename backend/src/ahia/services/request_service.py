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
from ahia.core.tenant_context import TenantContext
from ahia.crud import product_crud, request_crud, request_line_crud, storefront_crud, tenant_crud
from ahia.models.entities.request_line_model import RequestLineModel
from ahia.models.entities.request_model import RequestModel
from ahia.schemas.money_format import money_text, quantity_text
from ahia.schemas.request_schema import (
    PublicRequestSchema,
    RequestLineResponseSchema,
    RequestResponseSchema,
)

_REQUEST_LOGGER_NAME: Final[str] = "ahia.services.request"

#: The longest edge of a list, so one customer cannot fill a database with one request.
MAXIMUM_LINES_PER_LIST: Final[int] = 200


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
                line_total=None if line.line_total is None else money_text(line.line_total),
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
        default_phone_country_code: str = "+234",
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._default_country_code = default_phone_country_code
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
    ) -> tuple[RequestModel, int]:
        """Take a list from somebody with no account, and say only that it arrived.

        The shop's public address has to be open, because a link that answers nothing is a link that
        teaches a customer not to bother. Everything else about the shop stays out of the answer:
        the
        customer is told their list arrived, and nothing that is the trader's business.
        """
        now = datetime.now(UTC)
        request_id = uuid4()

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
        return request, len(stored_lines)

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
