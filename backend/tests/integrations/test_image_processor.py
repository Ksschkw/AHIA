"""Tests for server-side image validation and optimization.

Every case here is a way a client could try to push something past the upload
path: an oversized file, a mislabelled type, a decompression bomb, a photo the
size of a camera sensor. The processor must reject or normalize, never store
what it was given.
"""

from __future__ import annotations

import io
import logging
import struct
import zlib
from typing import Any

import pytest
from PIL import Image

from ahia.core.config import MediaTargetFormat, StorageLimits
from ahia.core.errors import ConfigurationError, InvalidMediaError
from ahia.integrations.media import image_processor
from ahia.integrations.media.image_processor import PillowImageProcessor

MEBIBYTE = 1024 * 1024


def build_limits(**overrides: Any) -> StorageLimits:
    baseline: dict[str, Any] = {
        "max_upload_bytes": 5 * MEBIBYTE,
        "max_product_image_bytes": 5 * MEBIBYTE,
        "max_image_width": 2000,
        "max_image_height": 2000,
        "max_images_per_product": 10,
        "max_tenant_storage_bytes": 500 * MEBIBYTE,
        "target_format": MediaTargetFormat.WEBP,
        "image_quality": 82,
        "strip_metadata": True,
        "allowed_content_types": ("image/jpeg", "image/png", "image/webp", "image/avif"),
    }
    baseline.update(overrides)
    return StorageLimits(**baseline)


def build_processor(**overrides: Any) -> PillowImageProcessor:
    return PillowImageProcessor(build_limits(**overrides))


def make_image(
    width: int,
    height: int,
    *,
    image_format: str = "PNG",
    mode: str = "RGB",
    exif: bytes | None = None,
    colour: tuple[int, int, int] = (200, 30, 40),
) -> bytes:
    """Render a real image so the tests exercise the real decoder."""
    image = Image.new(mode, (width, height), colour)
    buffer = io.BytesIO()
    save_arguments: dict[str, Any] = {}
    if exif is not None:
        save_arguments["exif"] = exif
    image.save(buffer, format=image_format, **save_arguments)
    return buffer.getvalue()


def jpeg_with_exif(width: int = 64, height: int = 64) -> bytes:
    """Return a JPEG carrying an EXIF block, as a phone camera would produce.

    Make and Model are the device identifiers a trader never intended to publish
    along with a photograph of a product.
    """
    image = Image.new("RGB", (width, height), (10, 120, 200))
    exif = Image.Exif()
    exif[0x010F] = "AHIA-Test-Camera"  # Make
    exif[0x0110] = "AHIA-Test-Model"  # Model
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif.tobytes())
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Format availability
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_configured_target_format_is_available_in_this_runtime() -> None:
    processor = build_processor(target_format=MediaTargetFormat.WEBP)

    processor.ensure_target_format_is_available()


@pytest.mark.unit
def test_missing_encoder_fails_loudly_at_startup() -> None:
    processor = build_processor()
    # Simulate a runtime image library without the AVIF encoder.
    object.__setattr__(processor, "_limits", build_limits(target_format=MediaTargetFormat.AVIF))

    original_probe = image_processor._encoder_is_available
    image_processor._encoder_is_available = lambda feature: False
    try:
        with pytest.raises(ConfigurationError) as captured:
            processor.ensure_target_format_is_available()
    finally:
        image_processor._encoder_is_available = original_probe

    assert "MEDIA_TARGET_FORMAT" in str(captured.value)


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_oversized_upload_is_rejected() -> None:
    processor = build_processor()
    content = make_image(2400, 2400)

    with pytest.raises(InvalidMediaError) as captured:
        await processor.optimize(
            content=content,
            declared_content_type="image/png",
            maximum_size_bytes=len(content) - 1,
        )

    assert "exceeds the configured ceiling" in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_disallowed_content_type_is_rejected() -> None:
    processor = build_processor()

    with pytest.raises(InvalidMediaError) as captured:
        await processor.optimize(
            content=b"%PDF-1.7 not an image",
            declared_content_type="application/pdf",
            maximum_size_bytes=MEBIBYTE,
        )

    assert "allowlist" in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_mislabelled_content_type_is_rejected() -> None:
    """A PNG announced as a JPEG is rejected on the decoder's evidence."""
    processor = build_processor()
    png_bytes = make_image(64, 64, image_format="PNG")

    with pytest.raises(InvalidMediaError) as captured:
        await processor.optimize(
            content=png_bytes,
            declared_content_type="image/jpeg",
            maximum_size_bytes=MEBIBYTE,
        )

    assert "does not match the decoded image" in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_undecodable_bytes_are_rejected() -> None:
    processor = build_processor()

    with pytest.raises(InvalidMediaError) as captured:
        await processor.optimize(
            content=b"\x89PNG\r\n\x1a\n truncated",
            declared_content_type="image/png",
            maximum_size_bytes=MEBIBYTE,
        )

    assert "could not be decoded" in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_decompression_bomb_is_rejected_before_decoding() -> None:
    """A 20000x20000 image is rejected from the header, not after allocation."""
    processor = build_processor(max_image_width=2000, max_image_height=2000)
    # A PNG header claiming an 18-megapixel canvas: above the configured ceiling
    # of four times the allowed area, below the image library's own bomb limit.
    # Building the real thing would allocate 72 MB of pixel data.
    bomb_header = _png_with_declared_size(6000, 3000)

    with pytest.raises(InvalidMediaError) as captured:
        await processor.optimize(
            content=bomb_header,
            declared_content_type="image/png",
            maximum_size_bytes=50 * MEBIBYTE,
        )

    assert "decompression" in str(captured.value)
    assert "bomb" in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_empty_content_is_rejected() -> None:
    processor = build_processor()

    with pytest.raises(InvalidMediaError):
        await processor.optimize(
            content=b"",
            declared_content_type="image/png",
            maximum_size_bytes=MEBIBYTE,
        )


# ---------------------------------------------------------------------------
# Optimization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_oversized_image_is_resized_within_the_bounds() -> None:
    processor = build_processor(max_image_width=800, max_image_height=800)
    # 1600x800 is twice the configured width and inside the decompression-bomb
    # ceiling, so it exercises resizing rather than rejection.
    content = make_image(1600, 800)

    result = await processor.optimize(
        content=content,
        declared_content_type="image/png",
        maximum_size_bytes=MEBIBYTE,
    )

    assert result.was_resized is True
    assert result.width <= 800
    assert result.height <= 800
    # Aspect ratio preserved: 2400x1200 is 2:1.
    assert abs((result.width / result.height) - 2.0) < 0.02
    assert result.original_width == 1600
    assert result.original_height == 800


@pytest.mark.asyncio
@pytest.mark.unit
async def test_small_image_is_never_upscaled() -> None:
    processor = build_processor(max_image_width=2000, max_image_height=2000)
    content = make_image(320, 240)

    result = await processor.optimize(
        content=content,
        declared_content_type="image/png",
        maximum_size_bytes=MEBIBYTE,
    )

    assert result.was_resized is False
    assert (result.width, result.height) == (320, 240)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_output_format_follows_configuration() -> None:
    for target_format, expected_mime, expected_format in (
        (MediaTargetFormat.WEBP, "image/webp", "WEBP"),
        (MediaTargetFormat.JPEG, "image/jpeg", "JPEG"),
        (MediaTargetFormat.PNG, "image/png", "PNG"),
    ):
        processor = build_processor(target_format=target_format)
        content = make_image(200, 200)

        result = await processor.optimize(
            content=content,
            declared_content_type="image/png",
            maximum_size_bytes=MEBIBYTE,
        )

        assert result.mime_type == expected_mime
        assert result.image_format == expected_format
        # The bytes really are the configured format, not just labelled as it.
        with Image.open(io.BytesIO(result.content)) as stored:
            assert stored.format == expected_format


@pytest.mark.asyncio
@pytest.mark.unit
async def test_webp_output_is_smaller_than_the_source_png() -> None:
    processor = build_processor(target_format=MediaTargetFormat.WEBP, image_quality=80)
    content = make_image(1600, 1200, image_format="PNG")

    result = await processor.optimize(
        content=content,
        declared_content_type="image/png",
        maximum_size_bytes=5 * MEBIBYTE,
    )

    assert result.size_bytes < result.original_size_bytes
    assert result.compression_ratio < 1.0


@pytest.mark.asyncio
@pytest.mark.unit
async def test_metadata_is_stripped_by_default() -> None:
    processor = build_processor(target_format=MediaTargetFormat.JPEG, strip_metadata=True)
    content = jpeg_with_exif(400, 300)

    with Image.open(io.BytesIO(content)) as source:
        assert source.getexif(), "the fixture must actually carry EXIF"

    result = await processor.optimize(
        content=content,
        declared_content_type="image/jpeg",
        maximum_size_bytes=5 * MEBIBYTE,
    )

    with Image.open(io.BytesIO(result.content)) as stored:
        assert not stored.getexif(), "GPS and device metadata must not survive the upload"
        assert not stored.info.get("exif")


@pytest.mark.asyncio
@pytest.mark.unit
async def test_metadata_can_be_retained_when_explicitly_configured() -> None:
    processor = build_processor(target_format=MediaTargetFormat.JPEG, strip_metadata=False)
    content = jpeg_with_exif(400, 300)

    result = await processor.optimize(
        content=content,
        declared_content_type="image/jpeg",
        maximum_size_bytes=5 * MEBIBYTE,
    )

    with Image.open(io.BytesIO(result.content)) as stored:
        assert stored.getexif(), "the flag must be a real control, not a no-op"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_result_carries_the_measured_size_and_checksum() -> None:
    processor = build_processor()
    content = make_image(600, 400)

    result = await processor.optimize(
        content=content,
        declared_content_type="image/png",
        maximum_size_bytes=MEBIBYTE,
    )

    assert result.size_bytes == len(result.content)
    assert len(result.checksum_sha256) == 64
    assert result.original_size_bytes == len(content)
    assert result.metadata_stripped is True


@pytest.mark.asyncio
@pytest.mark.unit
async def test_transparent_png_converted_to_jpeg_keeps_a_white_background() -> None:
    """A PNG with alpha cannot be written as JPEG; it must not fail or go black."""
    processor = build_processor(target_format=MediaTargetFormat.JPEG)
    image = Image.new("RGBA", (100, 100), (255, 0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    result = await processor.optimize(
        content=buffer.getvalue(),
        declared_content_type="image/png",
        maximum_size_bytes=MEBIBYTE,
    )

    with Image.open(io.BytesIO(result.content)) as stored:
        assert stored.mode == "RGB"
        red, green, blue = stored.convert("RGB").getpixel((50, 50))
        assert (red, green, blue) == (255, 255, 255)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_palette_image_is_converted_rather_than_rejected() -> None:
    processor = build_processor(target_format=MediaTargetFormat.WEBP)
    image = Image.new("P", (64, 64))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    result = await processor.optimize(
        content=buffer.getvalue(),
        declared_content_type="image/png",
        maximum_size_bytes=MEBIBYTE,
    )

    assert result.image_format == "WEBP"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_optimization_is_logged_with_internal_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    processor = build_processor(max_image_width=400, max_image_height=400)

    with caplog.at_level(logging.INFO, logger="ahia.integrations.media"):
        await processor.optimize(
            content=make_image(600, 400),
            declared_content_type="image/png",
            maximum_size_bytes=MEBIBYTE,
        )

    record = caplog.records[0]
    assert record.getMessage() == "image_optimized"
    assert record.was_resized is True
    assert record.stored_width <= 400


def _png_with_declared_size(width: int, height: int) -> bytes:
    """Build a PNG header that declares an enormous canvas.

    The image data is never decoded, which is the point: the rejection must come
    from the header, before any allocation proportional to the declared size.
    """

    def chunk(chunk_type: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + chunk_type
            + payload
            + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IEND", b"")
