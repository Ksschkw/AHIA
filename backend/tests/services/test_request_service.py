"""Tests for RequestService: category breadcrumbs, public lists, customer history, and confirmation.

All tests respect the architectural contracts: mock UnitOfWork, CRUD, and SalesService.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ahia.core.errors import InvalidInputError
from ahia.core.permissions import sales_permissions
from ahia.core.tenant_context import TenantContext
from ahia.crud import (
    category_crud,
    customer_crud,
    product_crud,
    request_crud,
    request_line_crud,
    tenant_crud,
)
from ahia.models.entities.category_model import CategoryModel
from ahia.models.entities.product_model import ProductModel
from ahia.models.entities.request_line_model import RequestLineModel, RequestLineUnit
from ahia.models.entities.request_model import RequestModel, RequestStatus
from ahia.models.entities.tenant_model import TenantModel
from ahia.services.request_service import (
    RequestService,
    _build_category_path,
    request_response,
)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def _make_category(
    name: str,
    *,
    category_id: object | None = None,
    parent_id: object | None = None,
    tenant_id: object | None = None,
) -> CategoryModel:
    cid = category_id if category_id is not None else uuid4()
    tid = tenant_id if tenant_id is not None else uuid4()
    return CategoryModel(
        id=cid,  # type: ignore[arg-type]
        tenant_id=tid,  # type: ignore[arg-type]
        name=name,
        slug=name.lower().replace(" ", "-"),
        parent_id=parent_id,  # type: ignore[arg-type]
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.unit
def test_build_category_path_single_level() -> None:
    cat = _make_category("Phone Accessories")
    categories = {cat.id: cat}
    path = _build_category_path(cat.id, categories)
    assert path == "Phone Accessories"


@pytest.mark.unit
def test_build_category_path_nested_hierarchy() -> None:
    root = _make_category("Phone Accessories")
    mid = _make_category("Screenguards", parent_id=root.id, tenant_id=root.tenant_id)
    leaf = _make_category("21D", parent_id=mid.id, tenant_id=root.tenant_id)

    categories = {root.id: root, mid.id: mid, leaf.id: leaf}
    path = _build_category_path(leaf.id, categories)
    assert path == "Phone Accessories > Screenguards > 21D"


@pytest.mark.unit
def test_build_category_path_handles_missing_or_cycle() -> None:
    assert _build_category_path(None, {}) is None
    assert _build_category_path(uuid4(), {}) is None

    # Cycle test
    cat_a = _make_category("A")
    cat_b = _make_category("B", parent_id=cat_a.id)
    # create cycle
    cat_a_cyclic = CategoryModel(
        id=cat_a.id,
        tenant_id=cat_a.tenant_id,
        name="A",
        slug="a",
        parent_id=cat_b.id,
        created_at=NOW,
        updated_at=NOW,
    )
    categories = {cat_a.id: cat_a_cyclic, cat_b.id: cat_b}
    # Should terminate without infinite loop
    path = _build_category_path(cat_b.id, categories)
    assert path is not None
    assert "A" in path and "B" in path


@pytest.mark.unit
def test_request_response_enriches_products_and_excludes_headings() -> None:
    tenant_id = uuid4()
    req_id = uuid4()
    prod_id = uuid4()
    cat = _make_category("Screen Protection", tenant_id=tenant_id)
    prod = ProductModel(
        id=prod_id,
        tenant_id=tenant_id,
        name="Hot 8 21D",
        slug="hot-8-21d",
        category_id=cat.id,
        selling_price=Decimal("500.00"),
        created_at=NOW,
        updated_at=NOW,
    )

    request = RequestModel.submitted_by_customer(
        request_id=req_id,
        tenant_id=tenant_id,
        customer_phone="+2348031234567",
        now=NOW,
    )

    heading_line = RequestLineModel(
        id=uuid4(),
        request_id=req_id,
        tenant_id=tenant_id,
        position=0,
        quantity=Decimal("1"),
        unit=RequestLineUnit.PIECE,
        free_text="Screen Guards",
        note="heading",
        created_at=NOW,
    )

    product_line = RequestLineModel(
        id=uuid4(),
        request_id=req_id,
        tenant_id=tenant_id,
        position=1,
        product_id=prod_id,
        quantity=Decimal("10"),
        unit=RequestLineUnit.PIECE,
        created_at=NOW,
    ).priced_at(unit_price=Decimal("500.00"))

    resp = request_response(
        request,
        [heading_line, product_line],
        products_by_id={prod.id: prod},
        categories_by_id={cat.id: cat},
    )

    assert resp.unpriced_line_count == 0  # Heading is excluded from unpriced
    assert resp.priced_total == "5000.00"
    assert resp.lines[0].free_text == "Screen Guards"
    assert resp.lines[0].note == "heading"
    assert resp.lines[1].product_name == "Hot 8 21D"
    assert resp.lines[1].group_name == "Screen Protection"
    assert resp.lines[1].line_total == "5000.00"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_confirm_request_triggers_complete_sale_for_catalogue_items() -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    device_id = uuid4()
    req_id = uuid4()
    prod_id = uuid4()

    tenant_context = TenantContext(
        user_id=user_id,
        tenant_id=tenant_id,
        membership_id=uuid4(),
        role_name="owner",
        device_id=device_id,
        permissions=frozenset({sales_permissions.SALES_CREATE, sales_permissions.SALES_READ}),
    )

    request = RequestModel.submitted_by_customer(
        request_id=req_id,
        tenant_id=tenant_id,
        customer_phone="+2348031234567",
        now=NOW,
    )

    heading = RequestLineModel(
        id=uuid4(),
        request_id=req_id,
        tenant_id=tenant_id,
        position=0,
        quantity=Decimal("1"),
        unit=RequestLineUnit.PIECE,
        free_text="Section",
        note="heading",
        created_at=NOW,
    )

    line = RequestLineModel(
        id=uuid4(),
        request_id=req_id,
        tenant_id=tenant_id,
        position=1,
        product_id=prod_id,
        quantity=Decimal("5"),
        unit=RequestLineUnit.PIECE,
        created_at=NOW,
    ).priced_at(unit_price=Decimal("1000.00"))

    mock_session = AsyncMock()
    mock_uow = MagicMock()
    mock_uow.session_handle = mock_session
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)
    mock_uow.commit = AsyncMock()

    mock_uow_factory = MagicMock(return_value=mock_uow)
    mock_tokens = MagicMock()
    mock_sales = MagicMock()
    mock_sales.complete_sale = AsyncMock()
    mock_audit = MagicMock()
    mock_audit.record_audit_event = AsyncMock()

    service = RequestService(
        unit_of_work_factory=mock_uow_factory,
        token_service=mock_tokens,
        audit_event_service=mock_audit,
        sales_service=mock_sales,
    )

    # Mock CRUD calls
    request_crud.require_by_id = AsyncMock(return_value=request)  # type: ignore[method-assign]
    request_line_crud.list_for_request = AsyncMock(return_value=[heading, line])  # type: ignore[method-assign]
    customer_crud.find_by_phone = AsyncMock(return_value=[])  # type: ignore[method-assign]
    request_crud.update = AsyncMock(return_value=request.confirmed(at=NOW))  # type: ignore[method-assign]
    product_crud.list_by_ids = AsyncMock(return_value=[])  # type: ignore[method-assign]
    category_crud.list_for_tenant = AsyncMock(return_value=[])  # type: ignore[method-assign]

    resp = await service.confirm_request(tenant_context, request_id=req_id)
    assert resp.status == RequestStatus.CONFIRMED

    # Verify complete_sale was called
    mock_sales.complete_sale.assert_awaited_once()
    _, kwargs = mock_sales.complete_sale.call_args
    assert len(kwargs["lines"]) == 1
    assert kwargs["lines"][0].product_id == prod_id
    assert kwargs["lines"][0].quantity == Decimal("5")
    assert kwargs["lines"][0].unit_price == Decimal("1000.00")
    assert kwargs["payments"] == []
    assert kwargs["operation_id"] == req_id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_customer_history_returns_summaries_and_lines() -> None:
    tenant_id = uuid4()
    req_id = uuid4()
    prod_id = uuid4()

    mock_session = AsyncMock()
    mock_uow = MagicMock()
    mock_uow.session_handle = mock_session
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)
    mock_uow_factory = MagicMock(return_value=mock_uow)
    mock_tokens = MagicMock()

    service = RequestService(
        unit_of_work_factory=mock_uow_factory,
        token_service=mock_tokens,
    )

    mock_tenant = TenantModel(
        id=tenant_id,
        name="Kosi's Pot",
        slug="kosi-s-pot",
        created_at=NOW,
        updated_at=NOW,
    )
    mock_req = RequestModel.submitted_by_customer(
        request_id=req_id,
        tenant_id=tenant_id,
        customer_phone="+2348031234567",
        now=NOW,
    )
    mock_line = RequestLineModel(
        id=uuid4(),
        request_id=req_id,
        tenant_id=tenant_id,
        position=0,
        product_id=prod_id,
        quantity=Decimal("3"),
        unit=RequestLineUnit.PIECE,
        created_at=NOW,
    ).priced_at(unit_price=Decimal("1500.00"))

    mock_prod = ProductModel(
        id=prod_id,
        tenant_id=tenant_id,
        name="Ceramic Screenguard",
        slug="ceramic-screenguard",
        selling_price=Decimal("1500.00"),
        created_at=NOW,
        updated_at=NOW,
    )

    tenant_crud.get_by_slug = AsyncMock(return_value=mock_tenant)  # type: ignore[method-assign]
    request_crud.list_for_tenant = AsyncMock(return_value=[mock_req])  # type: ignore[method-assign]
    category_crud.list_for_tenant = AsyncMock(return_value=[])  # type: ignore[method-assign]
    request_line_crud.list_for_request = AsyncMock(return_value=[mock_line])  # type: ignore[method-assign]
    product_crud.list_by_ids = AsyncMock(return_value=[mock_prod])  # type: ignore[method-assign]

    summaries = await service.list_customer_history(
        tenant_slug="kosi-s-pot",
        customer_phone="08031234567",
    )

    assert len(summaries) == 1
    assert summaries[0].id == req_id
    assert summaries[0].line_count == 1
    assert len(summaries[0].lines) == 1
    assert summaries[0].lines[0].text == "Ceramic Screenguard"
    assert summaries[0].lines[0].quantity == "3.000"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_unconfirmed_request() -> None:
    tenant_id = uuid4()
    req_id = uuid4()

    mock_session = AsyncMock()
    mock_uow = MagicMock()
    mock_uow.session_handle = mock_session
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)
    mock_uow.commit = AsyncMock()
    mock_uow_factory = MagicMock(return_value=mock_uow)
    mock_tokens = MagicMock()
    mock_audit = MagicMock()
    mock_audit.record_audit_event = AsyncMock()

    service = RequestService(
        unit_of_work_factory=mock_uow_factory,
        token_service=mock_tokens,
        audit_event_service=mock_audit,
    )

    mock_req = RequestModel.submitted_by_customer(
        request_id=req_id,
        tenant_id=tenant_id,
        customer_phone="08031234567",
        now=NOW,
    )
    request_crud.require_by_id = AsyncMock(return_value=mock_req)  # type: ignore[method-assign]
    request_crud.delete = AsyncMock(return_value=None)  # type: ignore[method-assign]

    tenant_context = TenantContext(
        tenant_id=tenant_id,
        user_id=uuid4(),
        membership_id=uuid4(),
        permissions=frozenset({sales_permissions.SALES_CREATE}),
    )
    await service.delete_request(tenant_context, request_id=req_id)
    request_crud.delete.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_confirmed_request_refused() -> None:
    tenant_id = uuid4()
    req_id = uuid4()

    mock_session = AsyncMock()
    mock_uow = MagicMock()
    mock_uow.session_handle = mock_session
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)
    mock_uow_factory = MagicMock(return_value=mock_uow)
    mock_tokens = MagicMock()

    service = RequestService(
        unit_of_work_factory=mock_uow_factory,
        token_service=mock_tokens,
    )

    mock_req = RequestModel.submitted_by_customer(
        request_id=req_id,
        tenant_id=tenant_id,
        customer_phone="08031234567",
        now=NOW,
    ).confirmed(at=NOW)
    request_crud.require_by_id = AsyncMock(return_value=mock_req)  # type: ignore[method-assign]

    tenant_context = TenantContext(
        tenant_id=tenant_id,
        user_id=uuid4(),
        membership_id=uuid4(),
        permissions=frozenset({sales_permissions.SALES_CREATE}),
    )
    with pytest.raises(InvalidInputError):
        await service.delete_request(tenant_context, request_id=req_id)
