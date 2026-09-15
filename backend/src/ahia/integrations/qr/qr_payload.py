"""The string a QR code encodes: a stable public URL, and nothing else.

**Only a public URL goes in.** A QR code is printed, photographed and pasted into group chats, and
it is read by a camera that shows the payload to whoever is holding the phone. Internal identifiers,
stock counts, prices and tokens for private resources are not "encoded compactly" - they are
published. The payload is the same address a person would type, which is the only thing that keeps a
printed code honest when the product changes behind it.

**The URL is absolute and built from configuration.** A relative path in a QR code is a code that
works only inside the application that printed it, which is not what a poster is for. The base comes
from `public_web_base_url`, so a deployment that moves its domain changes one setting rather than
every poster already on a wall.

**A payload that is not a public address is refused rather than encoded.** The builder accepts the
paths this product actually publishes - a shop, a product of a shop, a shared invoice - and refuses
anything else. A convenience function that encodes whatever it is handed is a function that will one
day encode an admin URL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from urllib.parse import quote

from ahia.core.errors import InvalidInputError

#: How much a QR code can carry before it stops being readable at a useful size. Version 40 with
#: low error correction holds 2 953 bytes; a printed code that needs a bigger version than that is
#: a code nobody can scan from a poster, so the payload is bounded well below it.
MAXIMUM_PAYLOAD_LENGTH: Final[int] = 512

#: The public path prefixes this product publishes. A closed set: an encoder that accepts any path
#: is an encoder that will one day accept an administrative one.
PUBLIC_PATH_PREFIXES: Final[tuple[str, ...]] = ("/shop/", "/share/")


@dataclass(frozen=True, slots=True)
class QrPayload:
    """What a QR code carries, and what it is for.

    `public_url` is the same string as `payload`. It is named twice because the two names mean
    different things to different readers: a printer wants a payload, and a support conversation
    wants a URL it can open.
    """

    payload: str
    public_url: str
    path: str


def build_qr_payload(*, path: str, base_url: str) -> QrPayload:
    """Return the payload for a public path, made absolute against the configured base.

    Raises `InvalidInputError` for a path this product does not publish, for a path carrying a query
    string or a fragment, and for a payload that would be too long to scan.
    """
    cleaned = path.strip()
    if not cleaned.startswith("/"):
        raise InvalidInputError(
            operation="build_qr_payload",
            entity="qr_payload",
            detail="a QR payload is built from an absolute path, so it can be made absolute",
        )
    if not any(cleaned.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES):
        raise InvalidInputError(
            operation="build_qr_payload",
            entity="qr_payload",
            detail=("only public addresses are encoded: " + ", ".join(PUBLIC_PATH_PREFIXES)),
        )
    if "?" in cleaned or "#" in cleaned:
        # A query string in a printed code is a parameter somebody will have to change later, and a
        # fragment never reaches the server at all.
        raise InvalidInputError(
            operation="build_qr_payload",
            entity="qr_payload",
            detail="a printed address carries no query string and no fragment",
        )

    public_url = f"{base_url.rstrip('/')}{quote(cleaned, safe='/-_.~')}"
    if len(public_url) > MAXIMUM_PAYLOAD_LENGTH:
        raise InvalidInputError(
            operation="build_qr_payload",
            entity="qr_payload",
            detail=f"payload exceeds {MAXIMUM_PAYLOAD_LENGTH} characters and would not scan",
        )
    return QrPayload(payload=public_url, public_url=public_url, path=cleaned)
