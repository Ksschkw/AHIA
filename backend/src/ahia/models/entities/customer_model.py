"""The customer entity: a person a business sells to.

**The data is the business's, and it is personal data.** A customer record holds a name, a
phone number and an address, which is the most sensitive thing this product stores about
somebody who did not themselves become a user. Three consequences shape this entity.

Consent is opt-in, and the default is no
    `marketing_opt_in` starts False and only a deliberate act sets it. Defaulting to True
    would mean a business collected consent by typing a name, which is not consent.

Audit descriptions carry identifiers, never the person
    `describe_for_audit` returns the customer's identifier, the business's identifier and
    two booleans. It does not return the name, the phone or the email, so a log line that
    mentions a customer cannot become the place where a phone number leaks. Support can
    find the record from the identifier; nobody can harvest from the logs.

A customer is deactivated, never deleted
    Sales reference customers, and a deleted customer is a receipt that cannot be
    explained. `deactivated` keeps the row and takes the customer out of the pickers;
    nothing in this entity removes anything.

Version is carried for sync
    Offline edits to a customer's notes are merged last-writer-wins, which needs a version
    to compare. Every change increments it, so two phones that edited the same customer can
    be told apart instead of one silently overwriting the other.

Phone completion needs configuration, so it happens in the service
    The entity normalises the *syntax* of a phone number - separators removed - and
    rejects one that is not a plausible number. Completing a country code requires the
    configured default, so a service does that before building this entity, exactly as it
    does for a user's account.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.phone_number import (
    MAXIMUM_PHONE_LENGTH,
    is_plausible_phone_number,
    normalize_phone_number,
)

MAXIMUM_NAME_LENGTH: Final[int] = 200
MAXIMUM_EMAIL_LENGTH: Final[int] = 254
MAXIMUM_ADDRESS_LENGTH: Final[int] = 500
MAXIMUM_NOTES_LENGTH: Final[int] = 2_000

_EMAIL_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


@dataclass(frozen=True, slots=True)
class CustomerModel:
    """One person a business sells to."""

    id: UUID
    tenant_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    notes: str | None = None
    marketing_opt_in: bool = False
    is_active: bool = True
    version: int = 1

    def __post_init__(self) -> None:
        _require_aware(self.created_at, field_name="created_at", customer_id=self.id)
        _require_aware(self.updated_at, field_name="updated_at", customer_id=self.id)
        if self.updated_at < self.created_at:
            raise EntityInvariantError(
                operation="build_customer",
                entity="customer",
                identifier=str(self.id),
                detail="updated_at is earlier than created_at",
            )

        if not self.name.strip():
            raise EntityInvariantError(
                operation="build_customer",
                entity="customer",
                identifier=str(self.id),
                detail="name is empty after trimming",
            )
        if len(self.name) > MAXIMUM_NAME_LENGTH:
            raise EntityInvariantError(
                operation="build_customer",
                entity="customer",
                identifier=str(self.id),
                detail=f"name exceeds {MAXIMUM_NAME_LENGTH} characters",
            )

        if self.phone is not None:
            if not is_plausible_phone_number(self.phone):
                raise EntityInvariantError(
                    operation="build_customer",
                    entity="customer",
                    identifier=str(self.id),
                    detail="phone is not a plausible number",
                )
            if len(self.phone) > MAXIMUM_PHONE_LENGTH:
                raise EntityInvariantError(
                    operation="build_customer",
                    entity="customer",
                    identifier=str(self.id),
                    detail=f"phone exceeds {MAXIMUM_PHONE_LENGTH} characters",
                )

        if self.email is not None and (
            len(self.email) > MAXIMUM_EMAIL_LENGTH or not _EMAIL_PATTERN.match(self.email)
        ):
            raise EntityInvariantError(
                operation="build_customer",
                entity="customer",
                identifier=str(self.id),
                detail="email is not a valid address",
            )

        for field_name, value, maximum in (
            ("address", self.address, MAXIMUM_ADDRESS_LENGTH),
            ("notes", self.notes, MAXIMUM_NOTES_LENGTH),
        ):
            if value is not None and len(value) > maximum:
                raise EntityInvariantError(
                    operation="build_customer",
                    entity="customer",
                    identifier=str(self.id),
                    detail=f"{field_name} exceeds {maximum} characters",
                )

        if self.version < 1:
            raise EntityInvariantError(
                operation="build_customer",
                entity="customer",
                identifier=str(self.id),
                detail="version starts at 1 and never goes back",
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        customer_id: UUID,
        tenant_id: UUID,
        name: str,
        now: datetime,
        phone: str | None = None,
        email: str | None = None,
        address: str | None = None,
        notes: str | None = None,
        marketing_opt_in: bool = False,
    ) -> CustomerModel:
        """Register a customer.

        A customer with no phone and no email is legitimate: a shopkeeper records the
        person who buys on credit by name alone, and demanding a contact detail would mean
        they write a fake one.
        """
        return cls(
            id=customer_id,
            tenant_id=tenant_id,
            name=name.strip(),
            phone=normalize_phone_number(phone),
            email=_clean_email(email),
            address=_clean_text(address),
            notes=_clean_text(notes),
            marketing_opt_in=marketing_opt_in,
            is_active=True,
            version=1,
            created_at=now,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    def has_a_contact_detail(self) -> bool:
        """Return True when the customer can be reached at all."""
        return self.phone is not None or self.email is not None

    def is_reachable_for_marketing(self) -> bool:
        """Return True when consent exists *and* there is somewhere to send a message."""
        return self.marketing_opt_in and self.is_active and self.has_a_contact_detail()

    def describe_for_audit(self) -> dict[str, str]:
        """Return identifiers and booleans, and nothing about the person.

        This is a privacy rule, not a formatting choice: a customer's name or phone number
        in a log line is personal data in a place it was never meant to be, and it would
        outlive the record itself. Support can look the record up from its identifier.
        """
        return {
            "customer_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "is_active": "true" if self.is_active else "false",
            "has_phone": "true" if self.phone is not None else "false",
            "has_email": "true" if self.email is not None else "false",
            "marketing_opt_in": "true" if self.marketing_opt_in else "false",
            "version": str(self.version),
        }

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def renamed(self, *, name: str, at: datetime) -> CustomerModel:
        """Return the customer with a new name."""
        return replace(self, name=name.strip(), updated_at=at, version=self.version + 1)

    def contacted(
        self,
        *,
        phone: str | None,
        email: str | None,
        at: datetime,
    ) -> CustomerModel:
        """Return the customer with both contact fields set.

        Both are applied because both are clearable: a caller that changes one passes the
        current value of the other, which keeps "clear it" and "leave it" visibly
        different at every call site.
        """
        return replace(
            self,
            phone=normalize_phone_number(phone),
            email=_clean_email(email),
            updated_at=at,
            version=self.version + 1,
        )

    def addressed(self, *, address: str | None, at: datetime) -> CustomerModel:
        """Return the customer with a delivery address, or without one."""
        return replace(self, address=_clean_text(address), updated_at=at, version=self.version + 1)

    def noted(self, *, notes: str | None, at: datetime) -> CustomerModel:
        """Return the customer with notes, or with them cleared.

        Notes are the field the specification names for last-writer-wins merging, which is
        why the version moves here more than anywhere else.
        """
        return replace(self, notes=_clean_text(notes), updated_at=at, version=self.version + 1)

    def gave_marketing_consent(self, *, opt_in: bool, at: datetime) -> CustomerModel:
        """Return the customer with their marketing preference recorded.

        Consent is the customer's decision, so this is the only transition for it and it
        always moves the version - a change of mind is worth syncing even when nothing else
        about the record changed.
        """
        return replace(self, marketing_opt_in=opt_in, updated_at=at, version=self.version + 1)

    def deactivated(self, *, at: datetime) -> CustomerModel:
        """Return the customer taken out of the pickers, with their history intact.

        Never a deletion: sales reference customers, and a receipt whose customer no longer
        exists is a receipt nobody can explain.
        """
        if not self.is_active:
            return self
        return replace(self, is_active=False, updated_at=at, version=self.version + 1)

    def reactivated(self, *, at: datetime) -> CustomerModel:
        """Return the customer active again."""
        if self.is_active:
            return self
        return replace(self, is_active=True, updated_at=at, version=self.version + 1)


def _clean_text(value: str | None) -> str | None:
    """Trim, and treat a value that is only whitespace as absent."""
    if value is None:
        return None
    return value.strip() or None


def _clean_email(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    return None if cleaned is None else cleaned.lower()


def _require_aware(moment: datetime, *, field_name: str, customer_id: UUID) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="build_customer",
            entity="customer",
            identifier=str(customer_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
