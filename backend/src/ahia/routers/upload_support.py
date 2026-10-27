"""HTTP body and upload utilities shared across routers."""

from __future__ import annotations

import base64
import binascii
import json

from fastapi import Request

from ahia.core.errors import InvalidMediaError


def _extract_json_payload(content: bytes) -> bytes:
    """Extract base64 or raw string from JSON body if present."""
    try:
        payload = json.loads(content.decode("utf-8"))
        if isinstance(payload, dict):
            val = (
                payload.get("image_base64")
                or payload.get("data")
                or payload.get("image")
                or payload.get("avatar")
                or payload.get("file")
            )
            if isinstance(val, str) and val.strip():
                return val.strip().encode("utf-8")
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    return content


def _decode_data_url(stripped: bytes) -> tuple[bytes, str | None]:
    """Decode a data:image/...;base64,... URI into raw bytes and detected content type."""
    header, sep, b64_part = stripped.partition(b";base64,")
    if sep:
        ctype = header.decode("utf-8", errors="ignore").replace("data:", "").strip()
        try:
            return base64.b64decode(b64_part), ctype
        except (binascii.Error, ValueError):
            return stripped, None
    _, sep2, b64_part2 = stripped.partition(b",")
    if sep2:
        try:
            return base64.b64decode(b64_part2), None
        except (binascii.Error, ValueError):
            return stripped, None
    return stripped, None


def _is_known_image(content: bytes) -> bool:
    """Return whether content starts with JPEG, PNG, or WebP magic bytes."""
    return (
        content.startswith(b"\xff\xd8\xff")
        or content.startswith(b"\x89PNG\r\n\x1a\n")
        or (content.startswith(b"RIFF") and b"WEBP" in content[:12])
    )


def _decode_base64_payload(content: bytes, declared_type: str) -> tuple[bytes, str]:
    """Decode data URL or plain base64 string into raw binary bytes."""
    stripped = content.strip()
    if stripped.startswith(b"data:image/"):
        decoded, ctype = _decode_data_url(stripped)
        return decoded, ctype or declared_type

    if declared_type not in (
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
    ) and not _is_known_image(stripped):
        try:
            decoded = base64.b64decode(stripped, validate=True)
            if _is_known_image(decoded):
                return decoded, declared_type
        except (binascii.Error, ValueError):
            pass
    return stripped, declared_type


def _infer_image_type(content: bytes, declared_type: str) -> str:
    """Determine the effective image MIME type from magic bytes if undeclared."""
    if declared_type in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        return declared_type
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"RIFF") and b"WEBP" in content[:12]:
        return "image/webp"
    return "image/jpeg"


async def extract_upload_content_and_type(
    request: Request, *, limit_bytes: int
) -> tuple[bytes, str]:
    """Extract raw image bytes and declared content type from an HTTP upload.

    Supports:
    1. Raw binary image stream with Content-Type: image/*
    2. JSON payload with image_base64 / data / image / avatar field
    3. Direct data URL (data:image/...;base64,...) or base64 stream
    """
    raw_content = await read_body_within_limit(request, limit_bytes=limit_bytes)
    content_type = declared_content_type(request)

    if content_type == "application/json" or raw_content.lstrip().startswith(b"{"):
        raw_content = _extract_json_payload(raw_content)

    raw_content, content_type = _decode_base64_payload(raw_content, content_type)
    content_type = _infer_image_type(raw_content, content_type)

    return raw_content, content_type


async def read_body_within_limit(request: Request, *, limit_bytes: int) -> bytes:
    """Read the request body, refusing anything larger than the ceiling.

    Streamed rather than buffered: a body that is already too large is stopped while it
    arrives, so a client cannot make the server hold a gigabyte before deciding it is
    unacceptable.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit_bytes:
            raise InvalidMediaError(
                operation="read_upload",
                entity="media_upload",
                detail=f"the uploaded file exceeds {limit_bytes} bytes",
            )
        chunks.append(chunk)

    content = b"".join(chunks)
    if not content:
        raise InvalidMediaError(
            operation="read_upload",
            entity="media_upload",
            detail="the request body was empty",
        )
    return content


def declared_content_type(request: Request) -> str:
    """Return the media type the client declared, without its parameters.

    `image/png; charset=binary` is a content type with a parameter the pipeline has no
    use for; comparing the whole header against an allowlist would reject valid uploads
    for a reason that has nothing to do with the picture.
    """
    header = request.headers.get("content-type", "")
    return header.split(";", 1)[0].strip().lower()
