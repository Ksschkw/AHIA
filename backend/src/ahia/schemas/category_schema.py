"""Transport contracts for categories.

Two fields are accepted, and one of them is not.

`name` and `description` are what a person types. The slug is not accepted at all:
it is derived from the name by the domain, so a client that sent both could send two
things that disagree and the database would keep whichever won. `extra="forbid"`
turns a client's attempt to set it into a 422 rather than a silently ignored field.

The description may be cleared, so an update that omits it and an update that sends
null are different requests: omitting means "leave it", sending null means "clear it".
`exclude_unset` is what preserves that difference, which is why the update schema
exposes `to_entity_changes` rather than a fully populated dump.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

from ahia.models.entities.category_model import (
    MAXIMUM_DESCRIPTION_LENGTH,
    MAXIMUM_NAME_LENGTH,
    CategoryModel,
)

CategoryName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAXIMUM_NAME_LENGTH),
]
CategoryDescription = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAXIMUM_DESCRIPTION_LENGTH,
    ),
]


class CategoryCreateSchema(BaseModel):
    """A category a business is adding to its own catalogue."""

    model_config = ConfigDict(extra="forbid")

    name: CategoryName
    description: CategoryDescription | None = None


class CategoryUpdateSchema(BaseModel):
    """A partial edit of a category.

    Sending `description: null` clears it. Sending nothing leaves it alone, which is
    the difference `exclude_unset` preserves.
    """

    model_config = ConfigDict(extra="forbid")

    name: CategoryName | None = None
    description: CategoryDescription | None = None

    def to_entity_changes(self) -> dict[str, str | None]:
        """Return only the fields the caller actually sent."""
        return self.model_dump(exclude_unset=True)


class CategoryResponseSchema(BaseModel):
    """One category, as the business sees it."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    name: str
    slug: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, category: CategoryModel) -> CategoryResponseSchema:
        return cls(
            id=category.id,
            tenant_id=category.tenant_id,
            name=category.name,
            slug=category.slug,
            description=category.description,
            created_at=category.created_at,
            updated_at=category.updated_at,
        )
