"""Transport contracts for customers.

The contract carries the privacy decisions rather than leaving them to a client.

`marketing_opt_in` is a field a caller may set, and it is absent from every response's
default: a client that does not send it records a customer who has not consented. The
entity defaults it to False and this contract preserves that, because a default of True
would be consent collected by typing a name.

The version travels in both directions. A response carries it, and an update may send the
version the client was working from - which is what turns two offline edits to the same
customer into a conflict the client can resolve rather than a silent overwrite. Sending no
version means last-writer-wins, which is what an online client wants and what the
specification allows for notes.

`possible_duplicate_of` is in the creation response and is not an error. A shopkeeper at
the counter should not be blocked by a phone number a household shares; they should be
told, once, and allowed to carry on.

The consent field is the one boolean parsed strictly. Pydantic accepts `"yes"`, `"1"` and
`"on"` for a boolean, which is convenient everywhere except here: consent is the field
where guessing is least welcome, and a client that means yes sends `true`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ahia.models.entities.customer_model import CustomerModel

CustomerName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
CustomerPhone = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=4, max_length=32)
]
CustomerEmail = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=254)
]
CustomerAddress = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
CustomerNotes = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)
]
#: A version a client was working from. Bounded below by one because that is where the
#: entity starts counting.
CustomerVersion = Annotated[int, Field(ge=1)]


class CustomerCreateSchema(BaseModel):
    """A customer a business is recording."""

    model_config = ConfigDict(extra="forbid")

    name: CustomerName
    phone: CustomerPhone | None = None
    email: CustomerEmail | None = None
    address: CustomerAddress | None = None
    notes: CustomerNotes | None = None
    # Absent means no consent, never "consent by default".
    marketing_opt_in: bool = False


class CustomerUpdateSchema(BaseModel):
    """A partial edit of a customer.

    Every field is optional, and `exclude_unset` preserves the difference between "not
    sent" and "sent as null": clearing a phone number, an address or notes is a real
    operation, and leaving one alone is a different request. `version` is the one field
    that is not a customer attribute - it is what the caller was working from.
    """

    model_config = ConfigDict(extra="forbid")

    name: CustomerName | None = None
    phone: CustomerPhone | None = None
    email: CustomerEmail | None = None
    address: CustomerAddress | None = None
    notes: CustomerNotes | None = None
    # Strict, unlike the other booleans: Pydantic accepts "yes", "1" and "on" for a bool,
    # and consent is the one field where guessing is unwelcome. A client that means true
    # sends true.
    marketing_opt_in: Annotated[bool, Field(strict=True)] | None = None
    version: CustomerVersion | None = None

    def to_entity_changes(self) -> dict[str, object]:
        """Return only the customer fields the caller actually sent."""
        return self.model_dump(exclude_unset=True, exclude={"version"})

    @property
    def expected_version(self) -> int | None:
        """Return the version the caller claims to have edited, if they said."""
        return self.version


class CustomerResponseSchema(BaseModel):
    """One customer, as the business sees them."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    name: str
    phone: str | None
    email: str | None
    address: str | None
    notes: str | None
    marketing_opt_in: bool
    is_active: bool
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, customer: CustomerModel) -> CustomerResponseSchema:
        return cls(
            id=customer.id,
            tenant_id=customer.tenant_id,
            name=customer.name,
            phone=customer.phone,
            email=customer.email,
            address=customer.address,
            notes=customer.notes,
            marketing_opt_in=customer.marketing_opt_in,
            is_active=customer.is_active,
            version=customer.version,
            created_at=customer.created_at,
            updated_at=customer.updated_at,
        )


class CustomerCreationResponseSchema(BaseModel):
    """A recorded customer, and who they may already be.

    `possible_duplicate_of` is reported rather than refused: the person at the counter
    decides whether it is the same customer, and blocking the write would push them into
    inventing a phone number to get past it.
    """

    model_config = ConfigDict(extra="forbid")

    customer: CustomerResponseSchema
    possible_duplicate_of: UUID | None


class CustomerLookupResponseSchema(BaseModel):
    """What a counter lookup found: the customers already holding a number."""

    model_config = ConfigDict(extra="forbid")

    matches: list[CustomerResponseSchema]
