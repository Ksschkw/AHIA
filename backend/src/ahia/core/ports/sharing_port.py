"""The provider-neutral sharing port.

Two things a business shares with a customer: a link that opens WhatsApp with a message already
written, and a string a QR code encodes. Both are outward-facing formats - one belongs to WhatsApp,
one to the QR specification - and both are capabilities the domain asks for by name rather than by
provider.

The port exists for the layering, not for a second implementation. A service may not import an
adapter and neither may a router: `core` is the one place every layer may reach, and the composition
root is the one place an adapter is chosen. A service that imported `wa.me` directly would be a
service that knows a vendor's URL shape, and the next messaging provider would mean editing the
layer that has nothing to do with messaging.

The port names no vendor: `whatsapp` does not appear in it. A test asserts that, so the contract
cannot quietly acquire a provider-shaped parameter - which is exactly how the storage port would
have grown an `r2_` prefix if nobody had been watching.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class SharingResult:
    """What a share sheet needs, as plain strings.

    One dataclass for both capabilities because they travel together to the same screen, and a
    caller that has one almost always wants the other.
    """

    public_url: str
    qr_payload: str
    click_to_chat_url: str | None
    #: Why there is no messaging link, when there is none. A typed absence rather than a silent
    #: null: a share button that does nothing is worse than one that explains itself.
    unavailable_reason: str | None = None


@runtime_checkable
class SharingPort(Protocol):
    """Builds the outward-facing strings for sharing one thing."""

    def share_sheet(
        self,
        *,
        public_path: str,
        business_name: str,
        subject_name: str,
        price_text: str | None,
        contact_number: str | None,
    ) -> SharingResult:
        """Return the public URL, the QR payload and the messaging link, if one can be built.

        `contact_number` is the international dialling form or None. A number that cannot be
        addressed produces no link and a reason, rather than an exception: a shop without a
        number is an ordinary state, not a failure of the request.
        """
        ...
