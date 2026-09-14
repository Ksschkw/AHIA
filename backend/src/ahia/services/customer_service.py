"""Customer use cases: recording the people a business sells to.

**Duplicate detection is a hint, not a gate.** A shopkeeper at the counter types a phone
number, and the business may already have that number because a household shares it or
because somebody was entered twice. `create_customer` therefore *records* the customer and
*reports* the possible duplicate alongside, rather than refusing the write. Refusing would
put the shopkeeper in front of a constraint they cannot satisfy without inventing a number
- and an invented number is worse than a duplicate, because it is wrong rather than merely
repeated. A caller that wants the answer before saving can ask `find_by_phone`; a caller
that wants it afterwards reads it from the response.

**Phone completion happens here, not in the entity.** The entity normalises syntax, and
completing a country code needs the configured default, which only a service has - the same
split the account flow uses, now sharing one implementation in `phone_number`.

**Privacy rules this layer enforces.** Log lines carry the customer's identifier and the
business's, never a name or a phone number: a customer never signed up for this product,
and their details should not accumulate in a log store. `describe_for_audit` on the entity
is what the log calls use.

**Deactivation, never deletion.** Sales reference customers, so withdrawing somebody from
the pickers leaves the history intact and reversible.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID, uuid4

from ahia.core.database import UnitOfWork
from ahia.core.errors import InvalidInputError, NotFoundError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions.customer_permissions import (
    CUSTOMERS_CREATE,
    CUSTOMERS_READ,
    CUSTOMERS_UPDATE,
)
from ahia.core.tenant_context import TenantContext
from ahia.crud import customer_crud
from ahia.models.entities.customer_model import CustomerModel
from ahia.models.entities.phone_number import (
    canonical_phone_number,
    is_plausible_phone_number,
    normalize_phone_number,
)
from ahia.services.audit_event_service import AuditEventService

_CUSTOMER_LOGGER_NAME: Final[str] = "ahia.services.customer"

#: Fields a caller may change. An allowlist, so a new column cannot become externally
#: writable merely by being added to the entity. The tenant and the version are absent:
#: one comes from the authorized context and the other is carried, not set.
_EDITABLE_FIELDS: Final[frozenset[str]] = frozenset(
    {"name", "phone", "email", "address", "notes", "marketing_opt_in"}
)


@dataclass(frozen=True, slots=True)
class CustomerCreation:
    """A customer that was recorded, and who they may already be.

    `possible_duplicate_of` is the identifier of an existing customer holding the same
    phone number, or None. It is reported rather than refused: the shopkeeper decides.
    """

    customer: CustomerModel
    possible_duplicate_of: UUID | None = None

    @property
    def has_possible_duplicate(self) -> bool:
        return self.possible_duplicate_of is not None


class CustomerService:
    """Customer use cases."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        default_phone_country_code: str,
        audit_event_service: AuditEventService,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._default_country_code = f"+{default_phone_country_code.lstrip('+')}"
        self._audit = audit_event_service
        self._logger = (logger or get_logger(_CUSTOMER_LOGGER_NAME)).bind(
            component="customer_service", layer="service"
        )

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def create_customer(
        self,
        tenant_context: TenantContext,
        *,
        name: str,
        phone: str | None = None,
        email: str | None = None,
        address: str | None = None,
        notes: str | None = None,
        marketing_opt_in: bool = False,
    ) -> CustomerCreation:
        """Record a customer and report who they might already be."""
        tenant_context.require_permission(
            CUSTOMERS_CREATE,
            operation="create_customer",
            resource_type="customer",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )

        canonical_phone = self._canonical_or_refuse(phone, operation="create_customer")
        customer = CustomerModel.create(
            customer_id=uuid4(),
            tenant_id=tenant_context.tenant_id,
            name=name,
            now=datetime.now(UTC),
            phone=canonical_phone,
            email=email,
            address=address,
            notes=notes,
            marketing_opt_in=marketing_opt_in,
        )

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            duplicate = await self._first_match_by_phone(
                session, tenant_context=tenant_context, phone=canonical_phone
            )
            stored = await customer_crud.create(session, customer)
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="create_customer",
                entity_type="customer",
                entity_id=stored.id,
                now=stored.created_at,
                detail=stored.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.info(
            "customer_created",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            customer_id=str(stored.id),
            has_possible_duplicate=duplicate is not None,
            possible_duplicate_of=str(duplicate.id) if duplicate else None,
        )
        return CustomerCreation(
            customer=stored, possible_duplicate_of=duplicate.id if duplicate else None
        )

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    async def list_customers(
        self,
        tenant_context: TenantContext,
        *,
        include_inactive: bool = False,
    ) -> list[CustomerModel]:
        """Return the business's customers, by name.

        Inactive customers are excluded by default: a picker at the counter should not
        offer somebody the business has stopped serving.
        """
        tenant_context.require_permission(
            CUSTOMERS_READ,
            operation="list_customers",
            resource_type="customer",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await customer_crud.list_for_tenant(
                unit_of_work.session_handle,
                tenant_context.tenant_id,
                include_inactive=include_inactive,
            )

    async def get_customer(
        self,
        tenant_context: TenantContext,
        *,
        customer_id: UUID,
    ) -> CustomerModel:
        """Return one customer, or refuse as if they did not exist."""
        tenant_context.require_permission(
            CUSTOMERS_READ,
            operation="get_customer",
            resource_type="customer",
            resource_id=str(customer_id),
            logger=self._logger,
        )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await self._require_customer(
                unit_of_work.session_handle,
                tenant_context=tenant_context,
                customer_id=customer_id,
            )

    async def find_by_phone(
        self,
        tenant_context: TenantContext,
        *,
        phone: str,
    ) -> list[CustomerModel]:
        """Return the customers who already hold this number.

        The counter's question before saving somebody new. A list, because a household
        shares a number and a match is a hint rather than proof.
        """
        tenant_context.require_permission(
            CUSTOMERS_READ,
            operation="find_customer_by_phone",
            resource_type="customer",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )
        canonical_phone = self._canonical_or_refuse(phone, operation="find_customer_by_phone")
        if canonical_phone is None:
            raise InvalidInputError(
                operation="find_customer_by_phone",
                entity="customer",
                detail="a phone number is required to look a customer up",
            )
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await customer_crud.find_by_phone(
                unit_of_work.session_handle,
                tenant_id=tenant_context.tenant_id,
                phone=canonical_phone,
            )

    # ------------------------------------------------------------------
    # Editing
    # ------------------------------------------------------------------

    async def update_customer(
        self,
        tenant_context: TenantContext,
        *,
        customer_id: UUID,
        changes: Mapping[str, Any],
        expected_version: int | None = None,
    ) -> CustomerModel:
        """Apply a partial edit, optionally checked against a version.

        The change map is heterogeneous, so each value is narrowed where it is used rather
        than trusted. `expected_version` is what an offline client was working from; when
        it no longer matches, the write is refused so that neither edit is silently lost.
        """
        tenant_context.require_permission(
            CUSTOMERS_UPDATE,
            operation="update_customer",
            resource_type="customer",
            resource_id=str(customer_id),
            logger=self._logger,
        )

        unexpected_fields = sorted(set(changes) - _EDITABLE_FIELDS)
        if unexpected_fields:
            raise InvalidInputError(
                operation="update_customer",
                entity="customer",
                identifier=str(customer_id),
                detail="fields are not editable on a customer: " + ", ".join(unexpected_fields),
            )

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            customer = await self._require_customer(
                session, tenant_context=tenant_context, customer_id=customer_id
            )

            if "name" in changes:
                customer = customer.renamed(name=_required_text(changes, "name"), at=now)
            if "phone" in changes or "email" in changes:
                customer = customer.contacted(
                    phone=(
                        self._canonical_or_refuse(
                            _optional_text(changes, "phone"), operation="update_customer"
                        )
                        if "phone" in changes
                        else customer.phone
                    ),
                    email=(
                        _optional_text(changes, "email") if "email" in changes else customer.email
                    ),
                    at=now,
                )
            if "address" in changes:
                customer = customer.addressed(address=_optional_text(changes, "address"), at=now)
            if "notes" in changes:
                customer = customer.noted(notes=_optional_text(changes, "notes"), at=now)
            if "marketing_opt_in" in changes:
                customer = customer.gave_marketing_consent(
                    opt_in=_required_boolean(changes, "marketing_opt_in"), at=now
                )

            stored = await customer_crud.update(
                session, customer, expected_version=expected_version
            )
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="update_customer",
                entity_type="customer",
                entity_id=stored.id,
                now=now,
                detail=stored.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.info(
            "customer_updated",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            customer_id=str(stored.id),
            changed_fields=sorted(changes),
            version=stored.version,
        )
        return stored

    # ------------------------------------------------------------------
    # Withdrawal
    # ------------------------------------------------------------------

    async def deactivate_customer(
        self,
        tenant_context: TenantContext,
        *,
        customer_id: UUID,
    ) -> CustomerModel:
        """Take a customer out of the pickers, with their history intact."""
        tenant_context.require_permission(
            CUSTOMERS_UPDATE,
            operation="deactivate_customer",
            resource_type="customer",
            resource_id=str(customer_id),
            logger=self._logger,
        )
        return await self._lifecycle_change(
            tenant_context, customer_id=customer_id, reactivating=False
        )

    async def reactivate_customer(
        self,
        tenant_context: TenantContext,
        *,
        customer_id: UUID,
    ) -> CustomerModel:
        """Return a withdrawn customer to the pickers."""
        tenant_context.require_permission(
            CUSTOMERS_UPDATE,
            operation="reactivate_customer",
            resource_type="customer",
            resource_id=str(customer_id),
            logger=self._logger,
        )
        return await self._lifecycle_change(
            tenant_context, customer_id=customer_id, reactivating=True
        )

    async def _lifecycle_change(
        self,
        tenant_context: TenantContext,
        *,
        customer_id: UUID,
        reactivating: bool,
    ) -> CustomerModel:
        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            customer = await self._require_customer(
                session, tenant_context=tenant_context, customer_id=customer_id
            )
            changed = customer.reactivated(at=now) if reactivating else customer.deactivated(at=now)
            stored = await customer_crud.update(session, changed)
            await self._audit.record_audit_event(
                session,
                tenant_context,
                action="reactivate_customer" if reactivating else "deactivate_customer",
                entity_type="customer",
                entity_id=stored.id,
                now=now,
                detail=stored.describe_for_audit(),
            )
            await unit_of_work.commit()

        self._logger.warning(
            "customer_reactivated" if reactivating else "customer_deactivated",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            customer_id=str(stored.id),
            security_event="customer_lifecycle_changed",
        )
        return stored

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _canonical_or_refuse(self, phone: str | None, *, operation: str) -> str | None:
        """Complete a phone number's country code, or refuse an implausible one.

        Refused here rather than left to the entity so the caller is told which field is
        wrong: the entity's message is about a customer, and a caller sending a mistyped
        phone number wants to know it is the phone number.
        """
        canonical = canonical_phone_number(
            normalize_phone_number(phone), default_country_code=self._default_country_code
        )
        if canonical is None:
            return None
        # Checked *after* completion, never before: a local number such as `0803 123 4567`
        # is eleven digits on its own and only becomes a dialable number once the country
        # code replaces the trunk prefix. Checking the local form would have accepted it
        # unchanged and stored a number that cannot be dialled from anywhere else.
        if not is_plausible_phone_number(canonical):
            raise InvalidInputError(
                operation=operation,
                entity="customer",
                detail="phone is not a plausible number",
            )
        return canonical

    async def _first_match_by_phone(
        self,
        session: object,
        *,
        tenant_context: TenantContext,
        phone: str | None,
    ) -> CustomerModel | None:
        if phone is None:
            return None
        matches = await customer_crud.find_by_phone(
            session,  # type: ignore[arg-type]
            tenant_id=tenant_context.tenant_id,
            phone=phone,
        )
        return matches[0] if matches else None

    async def _require_customer(
        self,
        session: object,
        *,
        tenant_context: TenantContext,
        customer_id: UUID,
    ) -> CustomerModel:
        customer = await customer_crud.get_by_id(
            session,  # type: ignore[arg-type]
            tenant_id=tenant_context.tenant_id,
            customer_id=customer_id,
        )
        if customer is None:
            self._logger.warning(
                "customer_access_denied",
                reason="customer_not_in_tenant",
                tenant_id=str(tenant_context.tenant_id),
                customer_id=str(customer_id),
                security_event="tenant_isolation",
            )
            raise NotFoundError(
                operation="fetch_customer",
                entity="customer",
                identifier=str(customer_id),
                detail="no customer matched in this business",
            )
        return customer


# ---------------------------------------------------------------------------
# Narrowing the change map
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


def _required_boolean(changes: Mapping[str, Any], field_name: str) -> bool:
    value = changes[field_name]
    if not isinstance(value, bool):
        raise _bad_field(field_name, "true or false")
    return value


def _bad_field(field_name: str, expected: str) -> InvalidInputError:
    return InvalidInputError(
        operation="update_customer",
        entity="customer",
        detail=f"{field_name} must be {expected}",
    )
