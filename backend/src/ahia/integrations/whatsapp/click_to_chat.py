"""Click-to-Chat: a `wa.me` link with the message already written.

The product's whole sharing story is a link in a WhatsApp message. A shopkeeper does not compose a
message; they tap a button and the message is there, addressed to the right person, naming the right
product at the right price. This module is that button.

**The number arrives already normalized, and this module checks the result.** The domain owns what
a phone number is - `models/entities/phone_number` turns `0803 123 4567` into `2348031234567` - and
this adapter is handed the dialling form because that is what WhatsApp wants. A second normalization
here would be a second opinion about a trunk prefix, and the disagreement would surface as a call to
the wrong number. What the adapter does check is that the number it was handed is digits of a
plausible length: a `wa.me` URL with a malformed number opens WhatsApp on a "phone number shared via
url is invalid" screen, which looks like the product is broken rather than the number.

**Everything in the message is percent-encoded, and the encoding is the URL's own.** A product
called `Beans & Rice (5kg)` with a newline in the inquiry must produce a link that opens with the
text intact, not one that truncates at the ampersand. `urllib.parse.quote` with an explicit safe set
does that; hand-building the query string is how a link breaks the first time somebody's product
name contains punctuation.

**The adapter knows nothing about the domain.** It is handed a phone number and a message and it
returns a URL. The service decides what the message says, because the message is product copy, and
copy changes for reasons a URL builder should not have to know about. That split is why this file
takes strings rather than a product.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from urllib.parse import quote

from ahia.core.errors import InvalidInputError

#: Characters left unescaped in the message. Deliberately empty: a message is free text, and every
#: character in it is data. The query separator and the fragment marker are the two that would
#: change the meaning of the URL if they travelled unescaped.
_UNSAFE_IN_MESSAGE: Final[str] = ""

MAXIMUM_MESSAGE_LENGTH: Final[int] = 1_000

#: E.164's own bounds, which is what the domain normalizer produces and what a dialler accepts.
MINIMUM_DIGITS: Final[int] = 7
MAXIMUM_DIGITS: Final[int] = 15


@dataclass(frozen=True, slots=True)
class ClickToChatLink:
    """A link that opens WhatsApp with a message already written."""

    url: str
    #: The number the link addresses, in international digits, without a plus.
    whatsapp_number: str


def build_click_to_chat_link(
    *,
    whatsapp_number: str,
    message: str,
    base_url: str = "https://wa.me",
) -> ClickToChatLink:
    """Return a `wa.me` link that opens a conversation with the message written.

    `whatsapp_number` is the international dialling form - digits only, no plus, no punctuation -
    which `models/entities/phone_number.international_digits_for` produces from whatever a business
    typed. Raises `InvalidInputError` for a number that could not be dialled and for an empty or
    oversized message, so the caller gets a field-level error rather than a link that opens a screen
    saying the number is invalid.
    """
    _require_diallable(whatsapp_number)
    cleaned = message.strip()
    if not cleaned:
        raise InvalidInputError(
            operation="build_click_to_chat_link",
            entity="whatsapp_link",
            detail="a click-to-chat link needs a message; an empty one is a link to nothing",
        )
    if len(cleaned) > MAXIMUM_MESSAGE_LENGTH:
        raise InvalidInputError(
            operation="build_click_to_chat_link",
            entity="whatsapp_link",
            detail=f"message exceeds {MAXIMUM_MESSAGE_LENGTH} characters",
        )

    encoded = quote(cleaned, safe=_UNSAFE_IN_MESSAGE)
    return ClickToChatLink(
        url=f"{base_url.rstrip('/')}/{whatsapp_number}?text={encoded}",
        whatsapp_number=whatsapp_number,
    )


def _require_diallable(whatsapp_number: str) -> None:
    """Refuse a number WhatsApp cannot address, without repeating it in the error.

    The value that failed is not included: a phone number in a log line outlives the request, and
    the caller already has the number they sent.
    """
    digits = whatsapp_number.strip()
    if not digits.isdigit() or not MINIMUM_DIGITS <= len(digits) <= MAXIMUM_DIGITS:
        raise InvalidInputError(
            operation="build_click_to_chat_link",
            entity="whatsapp_link",
            detail=(
                "a WhatsApp number is 7 to 15 digits in international form, without a plus or "
                "punctuation"
            ),
        )


def product_inquiry_message(
    *,
    business_name: str,
    product_name: str,
    product_url: str,
    price_text: str | None = None,
) -> str:
    """Return the message a customer sends about a product.

    Written here rather than in a service because it is copy, and copy is this adapter's business:
    the service says "a product inquiry for this business", and what that reads like is the
    integration's decision. A price, when there is one, is included as the string the API already
    renders, so the message and the page agree to the kobo.
    """
    price_clause = f" for {price_text}" if price_text else ""
    return (
        f"Hello {business_name}, I saw {product_name}{price_clause} on your AHIA shop "
        f"and I would like to ask about it.\n{product_url}"
    )
