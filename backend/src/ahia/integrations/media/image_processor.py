"""Server-side image validation and optimization.

Why this exists in the request path at all:

* a trader photographs a product with a phone that produces a 12-megabyte
  image, and the product operates on a zero-cost budget. Storing originals is
  not an option.
* a client can be modified. Client-side resizing is a user-experience
  improvement that saves the trader data; it is not a control.
* EXIF in a photo of a shop counter can carry GPS coordinates and a device
  identifier. Nobody asked for that to be stored.

What it does, in order: reject on byte size, reject on declared type outside the
allowlist, reject on a decompression bomb, reject when the decoded format
disagrees with the declared content type, resize down to the configured maximum
(never up), re-encode to the configured target format at the configured quality,
and write no metadata.

What it deliberately does not do: generate a ladder of presentation variants.
One optimized asset is stored; sizing for the UI is the client's job or the
delivery provider's, per ADR-0009.
"""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Mapping
from io import BytesIO
from typing import Any, Final

from PIL import Image, UnidentifiedImageError, features

from ahia.core.config import MediaTargetFormat, StorageLimits
from ahia.core.errors import ConfigurationError, InvalidMediaError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.ports.media_port import OptimizedImage
from ahia.core.ports.storage_port import compute_sha256

_MEDIA_LOGGER_NAME: Final[str] = "ahia.integrations.media"

#: Declared content type -> the Pillow format names that legitimately back it.
#: MPO is included for JPEG because a modern phone camera writes a multi-picture
#: file whose first frame is an ordinary JPEG.
_DECLARED_TYPE_TO_FORMATS: Final[dict[str, frozenset[str]]] = {
    "image/jpeg": frozenset({"JPEG", "MPO"}),
    "image/png": frozenset({"PNG"}),
    "image/webp": frozenset({"WEBP"}),
    "image/avif": frozenset({"AVIF"}),
}

#: Target format -> (Pillow save format, output content type, feature probe).
_TARGET_FORMAT_DETAILS: Final[dict[MediaTargetFormat, tuple[str, str, str | None]]] = {
    MediaTargetFormat.WEBP: ("WEBP", "image/webp", "webp"),
    MediaTargetFormat.AVIF: ("AVIF", "image/avif", "avif"),
    MediaTargetFormat.JPEG: ("JPEG", "image/jpeg", "jpg"),
    MediaTargetFormat.PNG: ("PNG", "image/png", None),
}

#: A source image may not exceed this multiple of the configured maximum area
#: before it is treated as a decompression bomb. A legitimate phone photo is
#: comfortably inside it; a bomb is not.
_DECOMPRESSION_BOMB_AREA_MULTIPLIER: Final[int] = 4

#: Formats that have no alpha channel and therefore need mode conversion.
_FORMATS_WITHOUT_ALPHA: Final[frozenset[str]] = frozenset({"JPEG"})


class PillowImageProcessor:
    """Implements `MediaProcessingPort` using Pillow."""

    def __init__(
        self,
        limits: StorageLimits,
        *,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._limits = limits
        self._logger = (logger or get_logger(_MEDIA_LOGGER_NAME)).bind(component="image_processor")

    @property
    def target_format(self) -> str:
        return self._limits.target_format.value

    @property
    def maximum_width(self) -> int:
        return self._limits.max_image_width

    @property
    def maximum_height(self) -> int:
        return self._limits.max_image_height

    def ensure_target_format_is_available(self) -> None:
        """Fail loudly at startup when the configured encoder is missing.

        Silently producing a different format would contradict the persisted
        mime type and the delivery contract, so it is a startup failure.
        """
        save_format, content_type, feature_probe = _TARGET_FORMAT_DETAILS[
            self._limits.target_format
        ]
        if feature_probe is None:
            return
        if not _encoder_is_available(feature_probe):
            raise ConfigurationError(
                operation="configure_media_processing",
                entity="media_target_format",
                detail=(
                    f"MEDIA_TARGET_FORMAT={self._limits.target_format.value} is configured but "
                    f"the runtime image library cannot encode {save_format} ({content_type})"
                ),
            )

    async def optimize(
        self,
        *,
        content: bytes,
        declared_content_type: str,
        maximum_size_bytes: int,
    ) -> OptimizedImage:
        """Validate and optimize an image without blocking the event loop.

        Pillow decode and encode are CPU-bound and synchronous, so the work runs
        in a worker thread. This is in-process CPU work, not an outbound
        boundary, so no circuit breaker is applied to it.
        """
        return await asyncio.to_thread(
            self._optimize_synchronously,
            content,
            declared_content_type,
            maximum_size_bytes,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _optimize_synchronously(
        self,
        content: bytes,
        declared_content_type: str,
        maximum_size_bytes: int,
    ) -> OptimizedImage:
        self._reject_oversized_upload(content, maximum_size_bytes, declared_content_type)
        self._reject_disallowed_content_type(declared_content_type)

        with warnings.catch_warnings():
            # A DecompressionBombWarning is a failure here, not something to log
            # and continue past.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            try:
                with Image.open(BytesIO(content)) as opened_image:
                    detected_format = opened_image.format or ""
                    self._reject_mismatched_format(declared_content_type, detected_format)
                    self._reject_decompression_bomb(opened_image)
                    original_width, original_height = opened_image.size
                    opened_image.load()
                    optimized_content, width, height, was_resized = self._render(
                        opened_image,
                        original_width=original_width,
                        original_height=original_height,
                    )
            except InvalidMediaError:
                raise
            except Image.DecompressionBombError as bomb_error:
                raise InvalidMediaError(
                    operation="optimize_image",
                    entity="product_image",
                    detail=f"decompression bomb rejected: declared={declared_content_type}",
                    cause=bomb_error,
                ) from bomb_error
            except (UnidentifiedImageError, OSError, ValueError) as decode_error:
                raise InvalidMediaError(
                    operation="optimize_image",
                    entity="product_image",
                    detail=(
                        f"image could not be decoded: declared={declared_content_type} "
                        f"error={type(decode_error).__name__}"
                    ),
                    cause=decode_error,
                ) from decode_error

        save_format, output_content_type, _ = _TARGET_FORMAT_DETAILS[self._limits.target_format]
        result = OptimizedImage(
            content=optimized_content,
            mime_type=output_content_type,
            image_format=save_format,
            width=width,
            height=height,
            size_bytes=len(optimized_content),
            checksum_sha256=compute_sha256(optimized_content),
            original_size_bytes=len(content),
            original_width=original_width,
            original_height=original_height,
            was_resized=was_resized,
            metadata_stripped=self._limits.strip_metadata,
        )
        self._logger.info(
            "image_optimized",
            declared_content_type=declared_content_type,
            output_format=save_format,
            original_bytes=result.original_size_bytes,
            stored_bytes=result.size_bytes,
            original_width=result.original_width,
            original_height=result.original_height,
            stored_width=result.width,
            stored_height=result.height,
            was_resized=was_resized,
        )
        return result

    def _reject_oversized_upload(
        self,
        content: bytes,
        maximum_size_bytes: int,
        declared_content_type: str,
    ) -> None:
        if len(content) > maximum_size_bytes:
            raise InvalidMediaError(
                operation="optimize_image",
                entity="product_image",
                detail=(
                    f"upload exceeds the configured ceiling: received={len(content)} "
                    f"limit={maximum_size_bytes} declared={declared_content_type}"
                ),
            )

    def _reject_disallowed_content_type(self, declared_content_type: str) -> None:
        if declared_content_type not in self._limits.allowed_content_types:
            raise InvalidMediaError(
                operation="optimize_image",
                entity="product_image",
                detail=(
                    f"content type not in the allowlist: declared={declared_content_type} "
                    f"allowed={','.join(self._limits.allowed_content_types)}"
                ),
            )
        if declared_content_type not in _DECLARED_TYPE_TO_FORMATS:
            # The allowlist is configuration; this catches a configuration whose
            # entries the processor cannot actually verify.
            raise ConfigurationError(
                operation="optimize_image",
                entity="media_allowed_content_types",
                detail=f"no decoder mapping for allowed type {declared_content_type}",
            )

    def _reject_mismatched_format(self, declared_content_type: str, detected_format: str) -> None:
        """Reject a file whose bytes disagree with its declared type.

        A content type is a client claim. The decoder's answer is evidence, and
        the evidence decides.
        """
        expected_formats = _DECLARED_TYPE_TO_FORMATS[declared_content_type]
        if detected_format not in expected_formats:
            raise InvalidMediaError(
                operation="optimize_image",
                entity="product_image",
                detail=(
                    f"declared type does not match the decoded image: "
                    f"declared={declared_content_type} decoded={detected_format or 'unknown'}"
                ),
            )

    def _reject_decompression_bomb(self, image: Image.Image) -> None:
        """Reject an image whose pixel count implies an unbounded allocation.

        Checked from the header, before the pixel data is decoded, so a bomb
        cannot consume memory on the way to being rejected.
        """
        width, height = image.size
        if width <= 0 or height <= 0:
            raise InvalidMediaError(
                operation="optimize_image",
                entity="product_image",
                detail=f"image reports a non-positive dimension: {width}x{height}",
            )
        configured_area = self._limits.max_image_width * self._limits.max_image_height
        allowed_area = configured_area * _DECOMPRESSION_BOMB_AREA_MULTIPLIER
        if width * height > allowed_area:
            raise InvalidMediaError(
                operation="optimize_image",
                entity="product_image",
                detail=(
                    f"pixel count exceeds the decompression-bomb ceiling: "
                    f"{width}x{height} allowed_area={allowed_area}"
                ),
            )

    def _render(
        self,
        image: Image.Image,
        *,
        original_width: int,
        original_height: int,
    ) -> tuple[bytes, int, int, bool]:
        """Resize, convert, re-encode and return the stored bytes."""
        target_width, target_height = self._fit_within(
            original_width,
            original_height,
            self._limits.max_image_width,
            self._limits.max_image_height,
        )
        was_resized = (target_width, target_height) != (original_width, original_height)

        # Captured from the source before any resize, because a resized image
        # does not carry the original's metadata blocks forward on its own.
        source_info = dict(image.info)

        rendered = (
            image
            if not was_resized
            else image.resize((target_width, target_height), Image.Resampling.LANCZOS)
        )

        save_format, _, _ = _TARGET_FORMAT_DETAILS[self._limits.target_format]
        rendered = _convert_mode_for_format(rendered, save_format)

        buffer = BytesIO()
        save_arguments = _save_arguments(
            save_format,
            quality=self._limits.image_quality,
            strip_metadata=self._limits.strip_metadata,
            source_info=source_info,
        )
        rendered.save(buffer, format=save_format, **save_arguments)
        return buffer.getvalue(), target_width, target_height, was_resized

    @staticmethod
    def _fit_within(
        width: int,
        height: int,
        maximum_width: int,
        maximum_height: int,
    ) -> tuple[int, int]:
        """Scale down to fit the bounds, preserving aspect ratio, never up.

        Upscaling would inflate storage for no added information, so an image
        already inside the bounds is returned unchanged.
        """
        if width <= maximum_width and height <= maximum_height:
            return width, height
        scale = min(maximum_width / width, maximum_height / height)
        scaled_width = max(1, int(width * scale))
        scaled_height = max(1, int(height * scale))
        return scaled_width, scaled_height


def _convert_mode_for_format(image: Image.Image, save_format: str) -> Image.Image:
    """Return an image whose colour mode the target encoder can write.

    A PNG screenshot with transparency cannot be written as JPEG, and a palette
    image cannot be written as WebP without conversion. The conversion is
    explicit rather than left to the encoder to fail on.
    """
    if save_format in _FORMATS_WITHOUT_ALPHA:
        if image.mode in {"RGBA", "LA", "P"}:
            background = Image.new("RGB", image.size, (255, 255, 255))
            if image.mode == "P":
                image = image.convert("RGBA")
            background.paste(image, mask=image.split()[-1])
            return background
        if image.mode not in {"RGB", "L"}:
            return image.convert("RGB")
        return image

    if save_format == "WEBP" and image.mode == "P":
        return image.convert("RGBA")
    return image


def _save_arguments(
    save_format: str,
    *,
    quality: int,
    strip_metadata: bool,
    source_info: Mapping[Any, Any],
) -> dict[str, object]:
    """Return encoder arguments for the target format.

    Metadata handling is explicit rather than incidental. When stripping is on,
    which is the default and the intended production setting, no EXIF, ICC or
    text chunk is forwarded: the source's GPS coordinates, device identifiers and
    camera information are gone. Pillow writes those blocks only when handed
    them, so omitting them is the strip.

    When stripping is deliberately turned off, the source blocks are forwarded
    for the formats that accept them. That path exists so the flag is a real
    control rather than a setting that does nothing.
    """
    arguments: dict[str, object] = {}
    if save_format in {"WEBP", "AVIF", "JPEG"}:
        arguments["quality"] = quality
        arguments["optimize"] = True
    if save_format == "JPEG":
        arguments["progressive"] = True
    if save_format == "PNG":
        # PNG is lossless, so "quality" does not apply; the compression level is
        # bounded instead.
        arguments["optimize"] = True
        arguments["compress_level"] = 9

    if not strip_metadata:
        exif_payload = source_info.get("exif")
        if isinstance(exif_payload, bytes) and exif_payload:
            arguments["exif"] = exif_payload
        icc_payload = source_info.get("icc_profile")
        if isinstance(icc_payload, bytes) and icc_payload:
            arguments["icc_profile"] = icc_payload
    return arguments


def _encoder_is_available(feature_probe: str) -> bool:
    """Return True when Pillow can encode the named format in this runtime."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            return bool(features.check(feature_probe))
    except (ValueError, UserWarning):
        return False
