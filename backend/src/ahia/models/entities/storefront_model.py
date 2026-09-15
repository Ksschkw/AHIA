"""A business's public shop: whether it is open, and what it says about itself.

**Publishing is a state, and the address belongs to the business.** The public URL is
`/shop/{tenant_slug}` - one address per business, chosen once and already unique across the whole
product. This entity deliberately has no slug of its own: a second one would be a second address
for the same shop, and the two would eventually disagree about which one customers hold. The
tenant owns the address; the storefront owns whether it answers.

**Unpublishing is not deleting.** A business that closes its shop for a week and reopens it keeps
the address it gave out, and it keeps the record that it was open before. `unpublished_at` is a
state, and re-publishing does not invent a new address or a new history.

**The contact number is completed by the service, not here.** The entity checks that the value
could be a phone number; turning `0803 123 4567` into `+2348031234567` needs the configured
default country code, which only a service has - the same split the account and customer records
already use, and it means a business can type the number the way it says it out loud.

**What the shop says is separate from what the business knows.** The headline, the description and
the contact number are chosen for customers; cost prices, stock counts, staff and financial data
live in this product and never appear on a public page. The projection that serves the shop is
built in `storefront_service`, and it is built from an allowlist rather than by removing fields
from a business object - the difference between a projection that cannot leak and one that
currently does not.

**One storefront per business.** A second row would be a second answer to "is this shop open",
and the first question a customer's link asks is exactly that. The uniqueness is a database
constraint.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.phone_number import is_plausible_phone_number

MAXIMUM_HEADLINE_LENGTH: Final[int] = 120
MAXIMUM_DESCRIPTION_LENGTH: Final[int] = 1_000
MAXIMUM_CONTACT_PHONE_LENGTH: Final[int] = 32


@dataclass(frozen=True, slots=True)
class StorefrontModel:
    """One business's public shop."""

    id: UUID
    tenant_id: UUID
    is_published: bool
    created_at: datetime
    updated_at: datetime
    headline: str | None = None
    description: str | None = None
    contact_phone: str | None = None
    published_at: datetime | None = None
    unpublished_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name, moment in (
            ("created_at", self.created_at),
            ("updated_at", self.updated_at),
        ):
            _require_aware(moment, field_name=field_name, storefront_id=self.id)
        if self.updated_at < self.created_at:
            raise EntityInvariantError(
                operation="build_storefront",
                entity="storefront",
                identifier=str(self.id),
                detail="updated_at is earlier than created_at",
            )

        for field_name, value, maximum in (
            ("headline", self.headline, MAXIMUM_HEADLINE_LENGTH),
            ("description", self.description, MAXIMUM_DESCRIPTION_LENGTH),
        ):
            if value is None:
                continue
            if not value.strip():
                raise EntityInvariantError(
                    operation="build_storefront",
                    entity="storefront",
                    identifier=str(self.id),
                    detail=f"{field_name} is empty; use None instead",
                )
            if len(value) > maximum:
                raise EntityInvariantError(
                    operation="build_storefront",
                    entity="storefront",
                    identifier=str(self.id),
                    detail=f"{field_name} exceeds {maximum} characters",
                )

        if self.contact_phone is not None:
            # Syntax only. Completing a country code needs the configured default, which only a
            # service has - so the service stores the canonical form and this entity refuses what
            # could not be a number at all.
            if not is_plausible_phone_number(self.contact_phone):
                raise EntityInvariantError(
                    operation="build_storefront",
                    entity="storefront",
                    identifier=str(self.id),
                    detail="contact_phone is not a plausible phone number",
                )
            if len(self.contact_phone) > MAXIMUM_CONTACT_PHONE_LENGTH:
                raise EntityInvariantError(
                    operation="build_storefront",
                    entity="storefront",
                    identifier=str(self.id),
                    detail=f"contact_phone exceeds {MAXIMUM_CONTACT_PHONE_LENGTH} characters",
                )

        self._check_publication()

    def _check_publication(self) -> None:
        if self.is_published:
            if self.published_at is None:
                raise EntityInvariantError(
                    operation="build_storefront",
                    entity="storefront",
                    identifier=str(self.id),
                    detail="a published shop must record when it was published",
                )
            _require_aware(self.published_at, field_name="published_at", storefront_id=self.id)
            return
        if self.published_at is not None and self.unpublished_at is None:
            raise EntityInvariantError(
                operation="build_storefront",
                entity="storefront",
                identifier=str(self.id),
                detail=(
                    "a shop that is not published and was published before must record when it "
                    "was withdrawn"
                ),
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def open_shop(
        cls,
        *,
        storefront_id: UUID,
        tenant_id: UUID,
        now: datetime,
        headline: str | None = None,
        description: str | None = None,
        contact_phone: str | None = None,
    ) -> StorefrontModel:
        """Build the storefront a business starts with: closed, and saying nothing yet.

        Closed by default, because a shop that appears on the public internet the moment a
        business registers is a shop nobody decided to open - and the first thing a customer
        would see is an empty catalogue.
        """
        return cls(
            id=storefront_id,
            tenant_id=tenant_id,
            is_published=False,
            created_at=now,
            updated_at=now,
            # Whitespace-only text is not text: storing it would put an empty string in a column
            # the contract promises holds something a person wrote.
            headline=(headline or "").strip() or None,
            description=(description or "").strip() or None,
            contact_phone=contact_phone.strip() if contact_phone else None,
        )

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def published(
        self,
        *,
        at: datetime,
        headline: str | None = None,
        description: str | None = None,
        contact_phone: str | None = None,
    ) -> StorefrontModel:
        """Return the shop open, with what it says about itself.

        Idempotent: publishing an open shop keeps the moment it first opened, because that is when
        customers started arriving and a later edit is not the same event.
        """
        return replace(
            self,
            is_published=True,
            published_at=self.published_at or at,
            unpublished_at=None,
            headline=_resolved(self.headline, headline),
            description=_resolved(self.description, description),
            contact_phone=(contact_phone.strip() if contact_phone else self.contact_phone),
            updated_at=at,
        )

    def unpublished(self, *, at: datetime) -> StorefrontModel:
        """Return the shop closed, keeping the address and the fact that it was open."""
        if not self.is_published:
            return self
        return replace(
            self,
            is_published=False,
            unpublished_at=at,
            updated_at=at,
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    def is_open(self) -> bool:
        """Return True when the shop answers at its public address."""
        return self.is_published

    def describe_for_audit(self) -> dict[str, str]:
        """Return identifiers and the publication state, and nothing a customer typed.

        The headline and the description are text a business wrote for strangers, and the contact
        number is a phone number: none of them belong in a log line that outlives the shop.
        """
        description = {
            "storefront_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "is_published": "true" if self.is_published else "false",
            "has_contact_phone": "true" if self.contact_phone else "false",
        }
        if self.published_at is not None:
            description["published_at"] = self.published_at.isoformat()
        return description


def _resolved(current: str | None, provided: str | None) -> str | None:
    """Return the new value when one was given, and the current one otherwise.

    An untouched field keeps what it had: publishing a shop that was withdrawn should not wipe the
    headline the business wrote, and a caller that sends nothing about a field is not asking for
    it to be cleared. Clearing is done by sending an empty-looking value through an update, which
    is a different call.
    """
    if provided is None:
        return current
    stripped = provided.strip()
    return stripped or None


def _require_aware(moment: datetime, *, field_name: str, storefront_id: UUID) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="build_storefront",
            entity="storefront",
            identifier=str(storefront_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
