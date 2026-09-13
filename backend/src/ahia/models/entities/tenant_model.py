"""The tenant entity: one business.

Every business in AHIA is a tenant, and every tenant-owned record carries the
tenant's identifier. This entity is the business itself: its name, its public
slug, its contact details and its money and time conventions.

Three decisions worth stating.

The slug is the public identity
    A storefront lives at `/shop/{slug}`, so the slug is chosen once and then
    published on WhatsApp, printed on a QR code and shared between customers.
    Changing it would break every link that already exists, so a rename changes
    the display name and never the slug. This entity therefore has no slug
    transition at all.

Reserved slugs are rejected in the domain, not only at the edge
    `www`, `api`, `admin` and a few dozen others are infrastructure names. A tenant
    that claimed one would either be unreachable or shadow an operational route,
    and the failure would surface as a mysterious 404 rather than as a rejected
    signup.

Money and time are tenant properties
    Currency and timezone are set from the market at creation and are not free
    text. A business in Lagos records naira in Africa/Lagos; a report that mixed
    conventions would be wrong in a way nobody notices until a month-end.

Stock policy is a tenant property too
    Whether stock may go negative is a business decision, not a global setting: a shop
    that orders to demand and one that keeps a shelf full need different answers. The
    policy is stored here, so a business changes it once and every stock movement in
    that business obeys it. See `negative_stock_policy`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError
from ahia.core.slug import MAXIMUM_SLUG_LENGTH, normalize_slug, require_slug_shape
from ahia.models.entities.negative_stock_policy import (
    DEFAULT_NEGATIVE_STOCK_POLICY,
    NegativeStockPolicy,
)

#: The minimum length a published business slug must have. Longer than the shared
#: floor in `core.slug` because this one appears in a URL a customer reads aloud.
MINIMUM_SLUG_LENGTH: Final[int] = 3

#: Names that would collide with infrastructure, with the brand, or with a
#: plausible future route. Rejecting them here means a person sees "that name is
#: taken" instead of discovering a broken link a week later.
RESERVED_SLUGS: Final[frozenset[str]] = frozenset(
    {
        "admin",
        "administrator",
        "api",
        "app",
        "assets",
        "auth",
        "billing",
        "blog",
        "cdn",
        "dashboard",
        "docs",
        "download",
        "email",
        "files",
        "health",
        "help",
        "home",
        "images",
        "internal",
        "legal",
        "login",
        "logout",
        "mail",
        "media",
        "mobile",
        "news",
        "official",
        "payment",
        "privacy",
        "public",
        "register",
        "root",
        "security",
        "settings",
        "share",
        "shop",
        "signup",
        "static",
        "status",
        "store",
        "support",
        "system",
        "terms",
        "test",
        "uploads",
        "user",
        "users",
        "web",
        "webhook",
        "webhooks",
        "www",
    }
)

_MAXIMUM_NAME_LENGTH: Final[int] = 120
_MAXIMUM_EMAIL_LENGTH: Final[int] = 254
_MAXIMUM_PHONE_LENGTH: Final[int] = 20
_MAXIMUM_LOCATION_LENGTH: Final[int] = 80

#: The market defaults. Nigeria, naira, Lagos time.
DEFAULT_COUNTRY: Final[str] = "NG"
DEFAULT_CURRENCY: Final[str] = "NGN"
DEFAULT_TIMEZONE: Final[str] = "Africa/Lagos"


def validate_slug(slug: str) -> None:
    """Raise unless the slug is one this product can publish.

    The shape and the length come from `core.slug`, which every slug in the product
    uses; the reserved names below are this entity's own rule, because they are about
    the public storefront namespace rather than about slugs in general.

    Shared with the schema layer so the edge and the domain cannot disagree about
    what is acceptable; the schema reports it as a 422 and the domain as an
    invariant violation, which is the difference between a bad request and a bug.
    """
    require_slug_shape(slug, minimum_length=MINIMUM_SLUG_LENGTH, maximum_length=MAXIMUM_SLUG_LENGTH)
    if slug in RESERVED_SLUGS:
        raise ValueError(f"{slug} is reserved")


@dataclass(frozen=True, slots=True)
class TenantModel:
    """One business."""

    id: UUID
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime
    is_active: bool = True
    business_type: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    country: str = DEFAULT_COUNTRY
    currency: str = DEFAULT_CURRENCY
    timezone: str = DEFAULT_TIMEZONE
    negative_stock_policy: NegativeStockPolicy = DEFAULT_NEGATIVE_STOCK_POLICY

    def __post_init__(self) -> None:
        _require_aware(self.created_at, field_name="created_at", tenant_id=self.id)
        _require_aware(self.updated_at, field_name="updated_at", tenant_id=self.id)

        if self.updated_at < self.created_at:
            raise EntityInvariantError(
                operation="build_tenant",
                entity="tenant",
                identifier=str(self.id),
                detail="updated_at is earlier than created_at",
            )

        if not self.name.strip():
            raise EntityInvariantError(
                operation="build_tenant",
                entity="tenant",
                identifier=str(self.id),
                detail="name is empty after trimming",
            )
        if len(self.name) > _MAXIMUM_NAME_LENGTH:
            raise EntityInvariantError(
                operation="build_tenant",
                entity="tenant",
                identifier=str(self.id),
                detail=f"name exceeds {_MAXIMUM_NAME_LENGTH} characters",
            )

        try:
            validate_slug(self.slug)
        except ValueError as invalid_slug:
            raise EntityInvariantError(
                operation="build_tenant",
                entity="tenant",
                identifier=str(self.id),
                detail=f"invalid slug: {invalid_slug}",
            ) from invalid_slug

        if len(self.country) != 2 or not self.country.isalpha():
            raise EntityInvariantError(
                operation="build_tenant",
                entity="tenant",
                identifier=str(self.id),
                detail="country must be a two-letter code",
            )
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise EntityInvariantError(
                operation="build_tenant",
                entity="tenant",
                identifier=str(self.id),
                detail="currency must be a three-letter code",
            )
        if not self.timezone.strip():
            raise EntityInvariantError(
                operation="build_tenant",
                entity="tenant",
                identifier=str(self.id),
                detail="timezone is required",
            )
        if not isinstance(self.negative_stock_policy, NegativeStockPolicy):
            # Stored as text in the database, so a value that no longer matches an enum
            # member must fail loudly here rather than silently becoming the default.
            raise EntityInvariantError(
                operation="build_tenant",
                entity="tenant",
                identifier=str(self.id),
                detail=(
                    "negative_stock_policy must be a NegativeStockPolicy, not "
                    f"{type(self.negative_stock_policy).__name__}"
                ),
            )

        if self.email is not None and len(self.email) > _MAXIMUM_EMAIL_LENGTH:
            raise EntityInvariantError(
                operation="build_tenant",
                entity="tenant",
                identifier=str(self.id),
                detail="email is too long",
            )
        if self.phone is not None and len(self.phone) > _MAXIMUM_PHONE_LENGTH:
            raise EntityInvariantError(
                operation="build_tenant",
                entity="tenant",
                identifier=str(self.id),
                detail="phone is too long",
            )
        for field_name, value in (("city", self.city), ("state", self.state)):
            if value is not None and len(value) > _MAXIMUM_LOCATION_LENGTH:
                raise EntityInvariantError(
                    operation="build_tenant",
                    entity="tenant",
                    identifier=str(self.id),
                    detail=f"{field_name} is too long",
                )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        tenant_id: UUID,
        name: str,
        slug: str,
        now: datetime,
        business_type: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        address: str | None = None,
        city: str | None = None,
        state: str | None = None,
        country: str = DEFAULT_COUNTRY,
        currency: str = DEFAULT_CURRENCY,
        timezone: str = DEFAULT_TIMEZONE,
        negative_stock_policy: NegativeStockPolicy = DEFAULT_NEGATIVE_STOCK_POLICY,
    ) -> TenantModel:
        """Create a business, canonicalising the slug and the contact fields."""
        return cls(
            id=tenant_id,
            name=name.strip(),
            slug=normalize_slug(slug),
            business_type=business_type.strip() if business_type else None,
            phone=phone.strip() if phone else None,
            email=email.strip().lower() if email else None,
            address=address.strip() if address else None,
            city=city.strip() if city else None,
            state=state.strip() if state else None,
            country=country.upper(),
            currency=currency.upper(),
            timezone=timezone.strip(),
            is_active=True,
            negative_stock_policy=negative_stock_policy,
            created_at=now,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    @property
    def public_path(self) -> str:
        """Return the public storefront path for this business."""
        return f"/shop/{self.slug}"

    def describe_for_audit(self) -> dict[str, str]:
        """Return the identifiers an audit record needs.

        The slug is included because it is public already, and it makes an audit
        line readable without a join. The contact details are not.
        """
        return {
            "tenant_id": str(self.id),
            "tenant_slug": self.slug,
            "is_active": "true" if self.is_active else "false",
        }

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def with_profile(
        self,
        *,
        name: str | None = None,
        business_type: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        address: str | None = None,
        city: str | None = None,
        state: str | None = None,
        at: datetime,
    ) -> TenantModel:
        """Return the business with profile fields changed.

        The slug is absent on purpose: it is published, and a rename must not break
        a link a customer already has.
        """
        return replace(
            self,
            name=name.strip() if name is not None else self.name,
            business_type=business_type.strip() if business_type else self.business_type,
            phone=phone.strip() if phone else self.phone,
            email=email.strip().lower() if email else self.email,
            address=address.strip() if address else self.address,
            city=city.strip() if city else self.city,
            state=state.strip() if state else self.state,
            updated_at=at,
        )

    def with_negative_stock_policy(
        self, *, policy: NegativeStockPolicy, at: datetime
    ) -> TenantModel:
        """Return the business with a different rule about stock going negative.

        A deliberate operation rather than a profile field: a business that starts
        permitting negative stock is changing what its own numbers mean, and the change
        should be visible as its own act in a log rather than inside a form submission
        that also fixed a phone number.
        """
        return replace(self, negative_stock_policy=policy, updated_at=at)

    def deactivate(self, *, at: datetime) -> TenantModel:
        """Return the business deactivated.

        Deactivation, never deletion: every sale, movement and customer belongs to
        this tenant, and destroying the row would destroy the history with it.
        """
        return replace(self, is_active=False, updated_at=at)

    def activate(self, *, at: datetime) -> TenantModel:
        return replace(self, is_active=True, updated_at=at)


def _require_aware(moment: datetime, *, field_name: str, tenant_id: UUID) -> None:
    """Reject a naive timestamp, as every entity in this codebase does."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="build_tenant",
            entity="tenant",
            identifier=str(tenant_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
