"""Transport contracts for the tenant slice.

The slug is the one field with real rules at the edge, because it is the one field
that reaches the public internet. Validation is shared with the domain rather than
reimplemented: `validate_slug` lives in the entity and is called here so a 422 and
a domain invariant can never disagree about what is acceptable.

A client may send a slug or a name. When a slug is omitted the service derives one
from the name, because asking a trader to invent a URL-safe identifier is asking
them to do work the product can do.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from ahia.models.entities.tenant_model import (
    MAXIMUM_SLUG_LENGTH,
    MINIMUM_SLUG_LENGTH,
    TenantModel,
    normalize_slug,
    validate_slug,
)

BusinessName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
LocationName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)]
ContactPhone = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)]
ContactEmail = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, max_length=254),
]

_CURRENCY_PATTERN: Final[str] = r"^[A-Za-z]{3}$"
_COUNTRY_PATTERN: Final[str] = r"^[A-Za-z]{2}$"


class TenantCreateSchema(BaseModel):
    """A new business request."""

    model_config = ConfigDict(extra="forbid")

    name: BusinessName
    slug: (
        Annotated[
            str,
            StringConstraints(
                strip_whitespace=True,
                to_lower=True,
                min_length=MINIMUM_SLUG_LENGTH,
                max_length=MAXIMUM_SLUG_LENGTH,
            ),
        ]
        | None
    ) = None
    business_type: ShortText | None = None
    phone: ContactPhone | None = None
    email: ContactEmail | None = None
    address: ShortText | None = None
    city: LocationName | None = None
    state: LocationName | None = None
    country: Annotated[str, StringConstraints(to_upper=True, pattern=_COUNTRY_PATTERN)] = "NG"
    currency: Annotated[str, StringConstraints(to_upper=True, pattern=_CURRENCY_PATTERN)] = "NGN"
    timezone: ShortText = "Africa/Lagos"

    @field_validator("slug")
    @classmethod
    def _validate_supplied_slug(cls, value: str | None) -> str | None:
        """Reject a slug the domain would refuse, as a 422 rather than a 500.

        The same function the entity calls, so the edge cannot accept something the
        domain rejects or the other way round.
        """
        if value is None:
            return None
        candidate = normalize_slug(value)
        try:
            validate_slug(candidate)
        except ValueError as invalid_slug:
            raise ValueError(str(invalid_slug)) from invalid_slug
        return candidate


class TenantUpdateSchema(BaseModel):
    """A business profile update.

    The slug is absent and therefore rejected by `extra="forbid"`: it is published
    on links that already exist, so changing it is not a profile edit. A business
    that genuinely needs a different public name gets a new slug through an
    explicit, audited operation, not by sending one to this endpoint.
    """

    model_config = ConfigDict(extra="forbid")

    name: BusinessName | None = None
    business_type: ShortText | None = None
    phone: ContactPhone | None = None
    email: ContactEmail | None = None
    address: ShortText | None = None
    city: LocationName | None = None
    state: LocationName | None = None

    def to_entity_changes(self) -> dict[str, str | None]:
        """Return the fields the caller actually sent."""
        return self.model_dump(exclude_unset=True)


class TenantResponseSchema(BaseModel):
    """A business as its members see it."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    slug: str
    public_path: str
    business_type: str | None
    phone: str | None
    email: str | None
    address: str | None
    city: str | None
    state: str | None
    country: str
    currency: str
    timezone: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, tenant: TenantModel) -> TenantResponseSchema:
        return cls(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            public_path=tenant.public_path,
            business_type=tenant.business_type,
            phone=tenant.phone,
            email=tenant.email,
            address=tenant.address,
            city=tenant.city,
            state=tenant.state,
            country=tenant.country,
            currency=tenant.currency,
            timezone=tenant.timezone,
            is_active=tenant.is_active,
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
        )


class TenantSummarySchema(BaseModel):
    """A business as it appears in a list of the caller's businesses.

    Narrower than the full view: a picker needs a name, a link and whether the
    business is active, not the address and the contact details.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    slug: str
    public_path: str
    role_name: str
    is_active: bool

    @classmethod
    def from_membership(cls, tenant: TenantModel, *, role_name: str) -> TenantSummarySchema:
        return cls(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            public_path=tenant.public_path,
            role_name=role_name,
            is_active=tenant.is_active,
        )
