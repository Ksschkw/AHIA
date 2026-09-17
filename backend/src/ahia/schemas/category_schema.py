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
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, StringConstraints

from ahia.models.entities.category_model import (
    MAXIMUM_DESCRIPTION_LENGTH,
    MAXIMUM_NAME_LENGTH,
    CategoryModel,
)
from ahia.schemas.money_format import money_text

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
    # The price everything under this group uses unless it carries its own - which is how "all of
    # the 21D are 350" is one number rather than twenty. Optional, and a group with none is normal.
    default_normal_price: Money | None = None
    default_wholesale_price: Money | None = None
    default_pieces_per_pack: int | None = None


class CategoryUpdateSchema(BaseModel):
    """A partial edit of a category.

    Sending `description: null` clears it. Sending nothing leaves it alone, which is
    the difference `exclude_unset` preserves.
    """

    model_config = ConfigDict(extra="forbid")

    name: CategoryName | None = None
    description: CategoryDescription | None = None
    default_normal_price: Money | None = None
    default_wholesale_price: Money | None = None
    default_pieces_per_pack: int | None = None

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
    default_normal_price: str | None
    default_wholesale_price: str | None
    default_pieces_per_pack: int | None
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
            default_normal_price=(
                None
                if category.default_normal_price is None
                else money_text(category.default_normal_price)
            ),
            default_wholesale_price=(
                None
                if category.default_wholesale_price is None
                else money_text(category.default_wholesale_price)
            ),
            default_pieces_per_pack=category.default_pieces_per_pack,
            created_at=category.created_at,
            updated_at=category.updated_at,
        )


def _parse_money(value: object) -> object:
    """Accept a price as a string or a number, and hand it on for the entity to check.

    A JSON number is accepted because a client that sends `350` means three hundred and fifty, and
    refusing it would be pedantry rather than safety. The entity decides what is a valid price; this
    only gets it there in one piece.
    """
    if isinstance(value, str):
        return Decimal(value)
    return value


Money = Annotated[Decimal, BeforeValidator(_parse_money)]
