"""HTTP transport for customers.

Six routes on `/tenants/{tenant_id}/customers`, plus the counter's lookup by phone.

The lookup is declared before the parameterised route, because FastAPI matches in
registration order: with `GET /customers/{customer_id}` first, the literal word `lookup`
would be parsed as a customer identifier and answered with a 422 that says nothing about
the real mistake.

Every handler parses, calls one service method and shapes the response. Authorization,
tenant resolution, duplicate detection and the version check live in the service, where a
CLI or a scheduled job gets the same answers as an HTTP request.
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from ahia.core.tenant_context import TenantContext
from ahia.routers.tenant_router import require_tenant_context
from ahia.schemas.customer_schema import (
    CustomerCreateSchema,
    CustomerCreationResponseSchema,
    CustomerLookupResponseSchema,
    CustomerResponseSchema,
    CustomerUpdateSchema,
)
from ahia.services.customer_service import CustomerService

_TENANT_SCOPE_PREFIX: Final[str] = "/tenants/{tenant_id}"

router = APIRouter(prefix=_TENANT_SCOPE_PREFIX, tags=["customers"])


def get_customer_service(request: Request) -> CustomerService:
    """Return the customer service for this request."""
    service: CustomerService = request.app.state.container.customer_service
    return service


CustomerServiceDependency = Annotated[CustomerService, Depends(get_customer_service)]
TenantContextDependency = Annotated[TenantContext, Depends(require_tenant_context)]


@router.post(
    "/customers",
    response_model=CustomerCreationResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Record a customer",
)
async def create_customer(
    payload: CustomerCreateSchema,
    tenant_context: TenantContextDependency,
    service: CustomerServiceDependency,
) -> CustomerCreationResponseSchema:
    """Record a customer, reporting anybody who may already be them.

    A likely duplicate does not refuse the write: a household shares a phone number, and
    the person at the counter is the one who knows.
    """
    creation = await service.create_customer(
        tenant_context,
        name=payload.name,
        phone=payload.phone,
        email=payload.email,
        address=payload.address,
        notes=payload.notes,
        marketing_opt_in=payload.marketing_opt_in,
    )
    return CustomerCreationResponseSchema(
        customer=CustomerResponseSchema.from_entity(creation.customer),
        possible_duplicate_of=creation.possible_duplicate_of,
    )


@router.get(
    "/customers/lookup",
    response_model=CustomerLookupResponseSchema,
    summary="Find the customers already holding a phone number",
)
async def look_up_customer_by_phone(
    tenant_context: TenantContextDependency,
    service: CustomerServiceDependency,
    phone: Annotated[str, Query(description="The number as it was typed.")],
) -> CustomerLookupResponseSchema:
    """Answer the counter's question before a customer is saved.

    Declared before the parameterised route: see the module docstring.
    """
    matches = await service.find_by_phone(tenant_context, phone=phone)
    return CustomerLookupResponseSchema(
        matches=[CustomerResponseSchema.from_entity(customer) for customer in matches]
    )


@router.get(
    "/customers",
    response_model=list[CustomerResponseSchema],
    summary="List this business's customers",
)
async def list_customers(
    tenant_context: TenantContextDependency,
    service: CustomerServiceDependency,
    include_inactive: Annotated[
        bool,
        Query(description="Include customers the business has stopped serving."),
    ] = False,
) -> list[CustomerResponseSchema]:
    """Return the customers, by name. Withdrawn customers are excluded unless asked for."""
    customers = await service.list_customers(tenant_context, include_inactive=include_inactive)
    return [CustomerResponseSchema.from_entity(customer) for customer in customers]


@router.get(
    "/customers/{customer_id}",
    response_model=CustomerResponseSchema,
    summary="Read one customer",
)
async def get_customer(
    customer_id: UUID,
    tenant_context: TenantContextDependency,
    service: CustomerServiceDependency,
) -> CustomerResponseSchema:
    """Return one customer. A customer of another business is a 404, not a 403."""
    customer = await service.get_customer(tenant_context, customer_id=customer_id)
    return CustomerResponseSchema.from_entity(customer)


@router.patch(
    "/customers/{customer_id}",
    response_model=CustomerResponseSchema,
    summary="Edit a customer",
)
async def update_customer(
    customer_id: UUID,
    payload: CustomerUpdateSchema,
    tenant_context: TenantContextDependency,
    service: CustomerServiceDependency,
) -> CustomerResponseSchema:
    """Apply a partial edit.

    Sending `version` checks the edit against the state the caller was working from, so two
    offline edits produce a 409 rather than one silently discarding the other. Sending
    nothing means last-writer-wins.
    """
    customer = await service.update_customer(
        tenant_context,
        customer_id=customer_id,
        changes=payload.to_entity_changes(),
        expected_version=payload.expected_version,
    )
    return CustomerResponseSchema.from_entity(customer)


@router.delete(
    "/customers/{customer_id}",
    response_model=CustomerResponseSchema,
    summary="Stop serving a customer",
)
async def deactivate_customer(
    customer_id: UUID,
    tenant_context: TenantContextDependency,
    service: CustomerServiceDependency,
) -> CustomerResponseSchema:
    """Take a customer out of the pickers, with their purchase history intact.

    Deletion is not offered: sales reference customers, and a vanished customer is a
    receipt nobody can explain.
    """
    customer = await service.deactivate_customer(tenant_context, customer_id=customer_id)
    return CustomerResponseSchema.from_entity(customer)


@router.post(
    "/customers/{customer_id}/reactivate",
    response_model=CustomerResponseSchema,
    summary="Serve a customer again",
)
async def reactivate_customer(
    customer_id: UUID,
    tenant_context: TenantContextDependency,
    service: CustomerServiceDependency,
) -> CustomerResponseSchema:
    """Return a withdrawn customer to the pickers."""
    customer = await service.reactivate_customer(tenant_context, customer_id=customer_id)
    return CustomerResponseSchema.from_entity(customer)
