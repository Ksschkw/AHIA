"""A customer's list: what somebody wants, before the trader has agreed to anything.

This is the paper slip, held as data. It is **not** a sale and it touches nothing: no stock moves,
no
ledger entry is written, no receipt is issued, until the trader confirms it and it becomes one. That
separation is the whole design, because a list is a wish and the trade it becomes is a decision only
he
can make - he sources some of it from his shelf and some of it from the market that morning.

The customer is identified by their **phone number**, never by an account: it is the one thing asked
of
them, and the reason they are asked is said out loud - so the trader knows whose list it is, and so
they
do not start from nothing next time.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError
from ahia.models.entities.phone_number import canonical_phone_number

MAXIMUM_NOTE_LENGTH: Final[int] = 1_000
MAXIMUM_NAME_LENGTH: Final[int] = 120

#: The shortest national number worth keeping: below this it is a typo, not a customer.
#: Counted in national digits, so the plus and the country code are not part of it.
_MINIMUM_CANONICAL_PHONE_DIGITS: Final[int] = 8


class RequestStatus(StrEnum):
    """Where a list has got to.

    A customer sends it, the trader prices it, and then he confirms it - which is the single moment
    a
    wish becomes a sale. Cancelling is possible until it is confirmed, and not after: a confirmed
    list
    is a record of an agreement, and ending it is a refund or a return rather than a cancellation.
    """

    SUBMITTED = "submitted"
    QUOTED = "quoted"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


#: The states a list may be moved out of, by status. Clearing an empty set is impossible on purpose.
_ALLOWED_TRANSITIONS: Final[dict[RequestStatus, frozenset[RequestStatus]]] = {
    RequestStatus.SUBMITTED: frozenset(
        {RequestStatus.QUOTED, RequestStatus.CONFIRMED, RequestStatus.CANCELLED}
    ),
    RequestStatus.QUOTED: frozenset({RequestStatus.CONFIRMED, RequestStatus.CANCELLED}),
    RequestStatus.CONFIRMED: frozenset(),
    RequestStatus.CANCELLED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class RequestModel:
    """One customer's list, from the moment they send it."""

    id: UUID
    tenant_id: UUID
    customer_phone: str
    created_at: datetime
    updated_at: datetime
    status: RequestStatus = RequestStatus.SUBMITTED
    customer_name: str | None = None
    note: str | None = None
    #: The address the customer came in on, stored as a digest so the link cannot be read out of
    #: the database, exactly as the shop's own share links are. None once the list is confirmed,
    #: because by then it is a sale and the link has no more work to do.
    public_token_digest: str | None = None
    #: Who is carrying it, their number, the waybill number, what the trip cost, and where it can be
    #: Who is carrying it, the waybill number, what the trip cost, and where it can be followed.
    #: way for this trade to work, and the cost is worth having separately, because it comes
    #: having separately, because it comes off what the list made.
    transporter_name: str | None = None
    transporter_phone: str | None = None
    waybill_number: str | None = None
    dispatch_cost: Decimal | None = None
    tracking_url: str | None = None
    dispatched_at: datetime | None = None

    def dispatched(
        self,
        *,
        transporter_name: str | None,
        transporter_phone: str | None,
        waybill_number: str | None,
        dispatch_cost: Decimal | None,
        tracking_url: str | None,
        at: datetime,
    ) -> RequestModel:
        """Return the list with how it was sent recorded.

        Every field is optional and none of them has a default meaning "unchanged": this is called
        with what the trader wrote down, and what he left out stays out.
        """
        return replace(
            self,
            transporter_name=transporter_name,
            transporter_phone=transporter_phone,
            waybill_number=waybill_number,
            dispatch_cost=dispatch_cost,
            tracking_url=tracking_url,
            dispatched_at=at,
            updated_at=at,
        )

    def __post_init__(self) -> None:
        for field_name, moment in (
            ("created_at", self.created_at),
            ("updated_at", self.updated_at),
        ):
            if moment.tzinfo is None or moment.utcoffset() is None:
                raise EntityInvariantError(
                    operation="build_request",
                    entity="request",
                    identifier=str(self.id),
                    detail=f"{field_name} must carry a timezone",
                )
        if self.updated_at < self.created_at:
            raise EntityInvariantError(
                operation="build_request",
                entity="request",
                identifier=str(self.id),
                detail="updated_at is earlier than created_at",
            )
        # The canonical form is checked for shape and not only for a leading plus: "not a number
        # at all" came through the canonicaliser as something, and a list nobody can be reached
        # about is a list the trader cannot serve.
        if not self.customer_phone.startswith("+") or not self.customer_phone[1:].isdigit():
            raise EntityInvariantError(
                operation="build_request",
                entity="request",
                identifier=str(self.id),
                detail="customer_phone must be stored in its one canonical form",
            )
        if len(self.customer_phone) < _MINIMUM_CANONICAL_PHONE_DIGITS + 1:
            raise EntityInvariantError(
                operation="build_request",
                entity="request",
                identifier=str(self.id),
                detail="customer_phone is too short to be a number anybody can be reached on",
            )
        if self.note is not None and len(self.note) > MAXIMUM_NOTE_LENGTH:
            raise EntityInvariantError(
                operation="build_request",
                entity="request",
                identifier=str(self.id),
                detail=f"note exceeds {MAXIMUM_NOTE_LENGTH} characters",
            )
        if self.customer_name is not None and len(self.customer_name) > MAXIMUM_NAME_LENGTH:
            raise EntityInvariantError(
                operation="build_request",
                entity="request",
                identifier=str(self.id),
                detail=f"customer_name exceeds {MAXIMUM_NAME_LENGTH} characters",
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def submitted_by_customer(
        cls,
        *,
        request_id: UUID,
        tenant_id: UUID,
        customer_phone: str,
        now: datetime,
        default_country_code: str = "+234",
        customer_name: str | None = None,
        note: str | None = None,
        public_token_digest: str | None = None,
    ) -> RequestModel:
        """Take the list a customer sent.

        The number is put into the one canonical form here rather than trusted, because the trader's
        history, the prices he has given this person, and the list itself all hang off it - and
        `0901...`, `+234901...` and `234901...` are the same person.
        """
        canonical = canonical_phone_number(
            customer_phone, default_country_code=default_country_code
        )
        if canonical is None:
            raise EntityInvariantError(
                operation="submit_request",
                entity="request",
                identifier=str(request_id),
                detail="a list cannot be taken without a number to keep it against",
            )
        return cls(
            id=request_id,
            tenant_id=tenant_id,
            customer_phone=canonical,
            customer_name=(customer_name.strip() if customer_name else None),
            note=(note.strip() if note else None),
            public_token_digest=public_token_digest,
            status=RequestStatus.SUBMITTED,
            created_at=now,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def moved_to(self, *, status: RequestStatus, at: datetime) -> RequestModel:
        """Return the list in a new state, or refuse the move.

        Refusing rather than allowing and correcting is the point: a confirmed list that could be
        confirmed again, or a cancelled one that could come back, is a list whose total, stock and
        receipt could be created twice.
        """
        # No idempotent shortcut: moving a list to the state it is already in is refused, because
        # the caller meant to do something, and a silent success would tell them it happened.
        if status not in _ALLOWED_TRANSITIONS[self.status]:
            raise EntityInvariantError(
                operation="move_request",
                entity="request",
                identifier=str(self.id),
                detail=f"a {self.status.value} list cannot become {status.value}",
            )
        return replace(self, status=status, updated_at=at)

    def confirmed(self, *, at: datetime) -> RequestModel:
        """Return the list as a sale, which is the only move that creates money."""
        return self.moved_to(status=RequestStatus.CONFIRMED, at=at)

    @property
    def is_confirmed(self) -> bool:
        """Return True when this list has become a sale."""
        return self.status is RequestStatus.CONFIRMED

    @property
    def is_open(self) -> bool:
        """Return True while the trader can still change or price the list."""
        return self.status in {RequestStatus.SUBMITTED, RequestStatus.QUOTED}

    def describe_for_audit(self) -> dict[str, str]:
        """Return identifiers only: a customer's number is personal data and does not belong in a
        log."""
        return {
            "request_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "status": self.status.value,
        }
