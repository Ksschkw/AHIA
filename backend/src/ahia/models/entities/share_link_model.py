"""A share link: an opaque token that opens one record to anybody holding it.

An invoice a business sends a customer, a shipment receipt, a report: the artifact is meant to be
seen by somebody who has no account, and the link is the authorization. That makes three things
non-negotiable.

**The token is not stored, and it is not derived from anything.** What the database holds is a
peppered digest, exactly as it does for a refresh token or a membership invitation; a leaked table
therefore yields no working links, and the plaintext exists only in the response that created it
and in the link the business sends. A token derived from the sale's identifier would be enumerable,
which is the same as having no token at all.

**Every link is revocable, and revocation is a state.** A business that sends an invoice to the
wrong number needs to be able to stop it, and the record of the link having existed is what makes
"who was this sent to, and when was it stopped" answerable. `revoked_at` is set once; a revoked
link never opens again and re-sharing mints a new one rather than reviving the old.

**A link names one resource of one business.** `(tenant_id, resource_type, resource_id)` is what it
opens, and the tenant is part of it: a token from one business can never resolve a record in
another, because the resolution reads the tenant from the link rather than from the caller - there
is no caller to read it from.

**Expiry is required, not optional.** A share link that never expires is a permanent public URL for
a record that may contain a customer's purchases; the caller chooses how long, within a bound, and
there is no way to ask for forever.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError

#: The characters a token digest is: SHA-256 rendered as lowercase hex, or the hex digest of the
#: peppered HMAC the token service produces. The name of the second constant contains "HASH"
#: rather than a word a secret scanner looks for, because that is what it is: a shape, not a value.
TOKEN_HASH_LENGTH: Final[int] = 64
HEXADECIMAL_CHARACTERS: Final[str] = "0123456789abcdef"

#: How long a link may live. A day is the default and a year is the ceiling: a link nobody thought
#: about must not outlive the reason it exists, and a link that never expires is a permanent public
#: address for a record that may contain somebody's purchases.
MINIMUM_LIFETIME: Final[timedelta] = timedelta(hours=1)
MAXIMUM_LIFETIME: Final[timedelta] = timedelta(days=365)
DEFAULT_LIFETIME: Final[timedelta] = timedelta(days=30)


class ShareableResource(StrEnum):
    """What a link can open.

    A closed set. Shipments and reports join it when those modules exist; naming them now would let
    a caller mint a link to a record this product cannot serve, and the failure would be discovered
    by the customer who opened it.
    """

    INVOICE = "invoice"


@dataclass(frozen=True, slots=True)
class ShareLinkModel:
    """One revocable link to one record."""

    id: UUID
    tenant_id: UUID
    resource_type: ShareableResource
    resource_id: UUID
    token_hash: str
    expires_at: datetime
    created_at: datetime
    created_by_user_id: UUID | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name, moment in (
            ("expires_at", self.expires_at),
            ("created_at", self.created_at),
        ):
            _require_aware(moment, field_name=field_name, link_id=self.id)
        if not isinstance(self.resource_type, ShareableResource):
            raise EntityInvariantError(
                operation="create_share_link",
                entity="share_link",
                identifier=str(self.id),
                detail=(
                    "resource_type must be a ShareableResource, "
                    f"not {type(self.resource_type).__name__}"
                ),
            )
        if len(self.token_hash) != TOKEN_HASH_LENGTH or any(
            character not in HEXADECIMAL_CHARACTERS for character in self.token_hash
        ):
            raise EntityInvariantError(
                operation="create_share_link",
                entity="share_link",
                identifier=str(self.id),
                detail=(
                    "token_hash must be the lowercase hex digest of the token; storing the token "
                    "itself would make a leaked table a set of working links"
                ),
            )
        if self.revoked_at is not None:
            _require_aware(self.revoked_at, field_name="revoked_at", link_id=self.id)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def issue(
        cls,
        *,
        link_id: UUID,
        tenant_id: UUID,
        resource_type: ShareableResource,
        resource_id: UUID,
        token_hash: str,
        now: datetime,
        lifetime: timedelta = DEFAULT_LIFETIME,
        created_by_user_id: UUID | None = None,
    ) -> ShareLinkModel:
        """Build a link whose token the caller has just minted and will not store.

        The lifetime is bounded here rather than trusted from a caller: a request that asks for a
        hundred years is asking for a permanent public address, and the honest answer is a refusal
        rather than a link somebody will find in a search index in 2126.
        """
        if now + lifetime <= now:
            # Checked when a link is issued, not when one is read: a stored link whose expiry has
            # passed is a link that expired, and refusing to reconstruct it would make the row
            # unreadable - which the first version of this entity did, and the public path turned
            # an expired link into a 422 instead of the not-found it must be.
            raise EntityInvariantError(
                operation="create_share_link",
                entity="share_link",
                identifier=str(link_id),
                detail="a link cannot be issued already expired",
            )
        if lifetime < MINIMUM_LIFETIME or lifetime > MAXIMUM_LIFETIME:
            raise EntityInvariantError(
                operation="create_share_link",
                entity="share_link",
                identifier=str(link_id),
                detail=(
                    f"lifetime must be between {MINIMUM_LIFETIME} and {MAXIMUM_LIFETIME}, "
                    f"not {lifetime}"
                ),
            )
        return cls(
            id=link_id,
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            token_hash=token_hash.strip().lower(),
            expires_at=now + lifetime,
            created_at=now,
            created_by_user_id=created_by_user_id,
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_expired(self, *, at: datetime) -> bool:
        """Return True when the link's lifetime has passed.

        Expiry is a comparison rather than a stored flag: a flag would need a job to set it, and a
        link would remain open until that job ran.
        """
        return at >= self.expires_at

    def opens(self, *, at: datetime) -> bool:
        """Return True when this link should open its record."""
        return not self.is_revoked() and not self.is_expired(at=at)

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def revoked(self, *, at: datetime) -> ShareLinkModel:
        """Return the link revoked.

        Idempotent: revoking twice keeps the first moment, because that is when the link stopped
        working and the second request changed nothing.
        """
        if self.is_revoked():
            return self
        return replace(self, revoked_at=at)

    def describe_for_audit(self) -> dict[str, str]:
        """Return identifiers and the state, and never the token or its digest."""
        description = {
            "share_link_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "resource_type": self.resource_type.value,
            "resource_id": str(self.resource_id),
            "is_revoked": "true" if self.is_revoked() else "false",
            "expires_at": self.expires_at.isoformat(),
        }
        if self.created_by_user_id is not None:
            description["created_by_user_id"] = str(self.created_by_user_id)
        return description


def _require_aware(moment: datetime, *, field_name: str, link_id: UUID) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="create_share_link",
            entity="share_link",
            identifier=str(link_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
