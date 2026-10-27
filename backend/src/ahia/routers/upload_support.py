"""HTTP body and upload utilities shared across routers."""

from __future__ import annotations

from fastapi import Request

from ahia.core.errors import InvalidMediaError


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
