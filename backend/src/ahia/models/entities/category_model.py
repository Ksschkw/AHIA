"""The category entity: how a business groups what it sells.

A category is a business's own vocabulary, not the product's. "Drinks" in one shop is
not "Drinks" in another, which is why the uniqueness rule is per tenant and why this
entity can never be global.

Three decisions worth stating.

The slug is derived from the name and does not follow a rename
    The slug is what a filter, an export and a report refer to, so it is a stable
    handle rather than a second copy of the display name. Renaming "Drinks" to "Cold
    Drinks" changes what a person reads and not what the system stores for a filter
    that was set up last month.

Uniqueness is per tenant, and enforced by the database
    `UNIQUE(tenant_id, slug)` is declared on the record, so two businesses may both
    have a "Drinks" category while one business may not have two, whichever way the
    name was typed.

There is no `is_active`
    The specification gives a category no state, and inventing one would raise a
    question the product has not answered: what a product in a deactivated category
    is. A category is removed when nothing references it, which is a decision the
    catalogue milestone makes once products exist. Until then this entity is created,
    read and edited, and never silently hidden.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError
from ahia.core.slug import normalize_slug, require_slug_shape

MAXIMUM_NAME_LENGTH: Final[int] = 120
MAXIMUM_SLUG_LENGTH: Final[int] = 63
MAXIMUM_DESCRIPTION_LENGTH: Final[int] = 2_000


@dataclass(frozen=True, slots=True)
class CategoryModel:
    """One grouping of products inside one business."""

    id: UUID
    tenant_id: UUID
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime
    description: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.created_at, field_name="created_at", category_id=self.id)
        _require_aware(self.updated_at, field_name="updated_at", category_id=self.id)

        if self.updated_at < self.created_at:
            raise EntityInvariantError(
                operation="build_category",
                entity="category",
                identifier=str(self.id),
                detail="updated_at is earlier than created_at",
            )

        if not self.name.strip():
            raise EntityInvariantError(
                operation="build_category",
                entity="category",
                identifier=str(self.id),
                detail="name is empty after trimming",
            )
        if len(self.name) > MAXIMUM_NAME_LENGTH:
            raise EntityInvariantError(
                operation="build_category",
                entity="category",
                identifier=str(self.id),
                detail=f"name exceeds {MAXIMUM_NAME_LENGTH} characters",
            )

        try:
            # Two characters are enough here, unlike a published business slug: a
            # shop is allowed to have a "TV" category.
            require_slug_shape(self.slug, maximum_length=MAXIMUM_SLUG_LENGTH)
        except ValueError as invalid_slug:
            raise EntityInvariantError(
                operation="build_category",
                entity="category",
                identifier=str(self.id),
                detail=f"invalid slug: {invalid_slug}",
            ) from invalid_slug

        if self.description is not None and len(self.description) > MAXIMUM_DESCRIPTION_LENGTH:
            raise EntityInvariantError(
                operation="build_category",
                entity="category",
                identifier=str(self.id),
                detail=f"description exceeds {MAXIMUM_DESCRIPTION_LENGTH} characters",
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        category_id: UUID,
        tenant_id: UUID,
        name: str,
        now: datetime,
        description: str | None = None,
    ) -> CategoryModel:
        """Create a category, deriving its slug from its name.

        The slug is derived rather than accepted: a client that sent both could send
        two things that disagree, and the one that ends up in the database would be
        whichever won. Deriving it means the handle always matches the words that
        produced it.
        """
        trimmed_name = name.strip()
        # A description of only whitespace is no description. Collapsing it here means
        # a reader never has to test for both None and the empty string.
        trimmed_description = description.strip() if description is not None else None
        return cls(
            id=category_id,
            tenant_id=tenant_id,
            name=trimmed_name,
            slug=normalize_slug(trimmed_name),
            description=trimmed_description or None,
            created_at=now,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    def describe_for_audit(self) -> dict[str, str]:
        """Return the identifiers an audit record needs.

        The name is included because an audit line about a category is unreadable
        without it and a category name is not personal data. The description is not:
        it is free text a business wrote for its own customers.
        """
        return {
            "category_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "category_slug": self.slug,
        }

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def renamed(self, *, name: str, at: datetime) -> CategoryModel:
        """Return the category with a new display name.

        The slug is untouched on purpose: it is the stable handle other things point
        at, and a rename is a change to what people read.
        """
        return replace(self, name=name.strip(), updated_at=at)

    def described(self, *, description: str | None, at: datetime) -> CategoryModel:
        """Return the category with its description set, or cleared.

        Clearing is a real operation, so `None` means cleared rather than unchanged.
        The caller decides whether the field was sent at all; this method always
        applies what it is given.
        """
        trimmed = description.strip() if description is not None else None
        return replace(self, description=trimmed or None, updated_at=at)


def _require_aware(moment: datetime, *, field_name: str, category_id: UUID) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="build_category",
            entity="category",
            identifier=str(category_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
