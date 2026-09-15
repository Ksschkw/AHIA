"""The sharing adapter: the one place the outward formats are spelled.

Every other module asks for a share sheet by name and receives strings; this file is where
`wa.me` and the QR payload's path rules actually live. It is constructed by the composition root,
which is the only place allowed to choose an adapter, and it satisfies `core.ports.sharing_port`
so no caller has to know it exists.

Nothing here holds state or opens a connection: building a URL is arithmetic on strings, and the
adapter is a function with a name.
"""

from __future__ import annotations

from ahia.core.errors import InvalidInputError
from ahia.core.ports.sharing_port import SharingResult
from ahia.integrations.qr.qr_payload import build_qr_payload
from ahia.integrations.whatsapp.click_to_chat import (
    build_click_to_chat_link,
    product_inquiry_message,
)


class SharingAdapter:
    """Builds share sheets from public paths and contact numbers."""

    def __init__(
        self,
        *,
        public_base_url: str,
        click_to_chat_base_url: str,
    ) -> None:
        self._public_base_url = public_base_url
        self._click_to_chat_base_url = click_to_chat_base_url

    def share_sheet(
        self,
        *,
        public_path: str,
        business_name: str,
        subject_name: str,
        price_text: str | None,
        contact_number: str | None,
    ) -> SharingResult:
        """Return the address, the payload and the link, with a reason when there is no link."""
        qr = build_qr_payload(path=public_path, base_url=self._public_base_url)
        if contact_number is None:
            return SharingResult(
                public_url=qr.public_url,
                qr_payload=qr.payload,
                click_to_chat_url=None,
                unavailable_reason="this shop has no contact number a customer can message",
            )

        message = product_inquiry_message(
            business_name=business_name,
            product_name=subject_name,
            product_url=qr.public_url,
            price_text=price_text,
        )
        try:
            link = build_click_to_chat_link(
                whatsapp_number=contact_number,
                message=message,
                base_url=self._click_to_chat_base_url,
            )
        except InvalidInputError:
            # A number the messaging provider cannot address is a shop that cannot be messaged:
            # an ordinary state, not a failed request. The share sheet offers the link and the QR
            # code and says why there is no message button.
            return SharingResult(
                public_url=qr.public_url,
                qr_payload=qr.payload,
                click_to_chat_url=None,
                unavailable_reason="this shop's contact number cannot be messaged",
            )
        return SharingResult(
            public_url=qr.public_url,
            qr_payload=qr.payload,
            click_to_chat_url=link.url,
        )
