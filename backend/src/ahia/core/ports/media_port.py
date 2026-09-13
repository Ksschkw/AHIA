"""The provider-neutral media processing port.

Image validation and optimization is a server responsibility, not a client one.
A client can be modified, so client-side resizing is a user-experience
improvement that saves a trader's data, never a control.

This port is provider-neutral by construction: it takes bytes and a declared
content type, and returns bytes with their measured properties. It knows nothing
about where the result will be stored.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class OptimizedImage:
    """The result of validating and optimizing one uploaded image.

    `size_bytes` is measured after processing, and it is the number that quota
    accounting must use. Charging a tenant for the original upload rather than
    the stored object would overstate usage by an order of magnitude.
    """

    content: bytes
    mime_type: str
    image_format: str
    width: int
    height: int
    size_bytes: int
    checksum_sha256: str
    original_size_bytes: int
    original_width: int
    original_height: int
    was_resized: bool
    metadata_stripped: bool

    @property
    def compression_ratio(self) -> float:
        """Return stored bytes divided by uploaded bytes."""
        if self.original_size_bytes == 0:
            return 1.0
        return self.size_bytes / self.original_size_bytes


@runtime_checkable
class MediaProcessingPort(Protocol):
    """The media capability a service receives."""

    @property
    def target_format(self) -> str:
        """Return the configured stored format."""
        ...

    @property
    def maximum_width(self) -> int: ...

    @property
    def maximum_height(self) -> int: ...

    async def optimize(
        self,
        *,
        content: bytes,
        declared_content_type: str,
        maximum_size_bytes: int,
    ) -> OptimizedImage:
        """Validate and optimize one image.

        Rejects rather than stores when any of these is true:

        * the byte length exceeds the supplied ceiling
        * the declared content type is not in the allowlist
        * the decoded image's format disagrees with the declared content type
        * the image is a decompression bomb

        Otherwise it resizes down to the configured maximum (never up), re-encodes
        to the configured target format at the configured quality, and strips
        EXIF, GPS and device metadata.
        """
        ...

    def ensure_target_format_is_available(self) -> None:
        """Fail loudly when the configured encoder is missing from the runtime.

        Called at startup. A configuration that cannot be honoured must not
        silently degrade to a different format, because the stored mime type is
        part of the persisted metadata and of the delivery contract.
        """
        ...
