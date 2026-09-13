"""Transport contracts for product images.

The upload carries exactly two things from a client: the file itself and whether it
should be the product's cover. Everything else about the object - its key, its provider,
its stored format, its size, its dimensions, its checksum - is decided by the server and
reported back, because a client that can name its own object key can write into another
tenant's prefix, and a client that can claim a content type can lie about one.

The response includes a delivery URL, which is built by the active storage adapter for
the moment of the request rather than stored. A stored URL would be wrong the day the
domain changes or the provider is switched; the key and the provider are the durable
facts, and the URL is derived from them.

`is_primary` is accepted here rather than in a separate call because "this is the
picture for the card" is usually the reason for uploading in the first place. Changing
the cover of an existing image has its own endpoint.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ahia.models.entities.product_image_model import ProductImageModel

#: The largest filename the client may suggest. It is used for nothing but an error
#: message and a log line: the stored key is built from server-side identifiers, so a
#: filename never reaches the object store.
MaximumFilenameLength = Annotated[int, Field(ge=1, le=255)]


class ProductImageUploadSchema(BaseModel):
    """The non-file part of an upload form."""

    model_config = ConfigDict(extra="forbid")

    is_primary: bool = False


class ProductImageResponseSchema(BaseModel):
    """One stored picture, as the business sees it.

    `delivery_url` is present only when the adapter could build one. A tenant on a
    private provider gets no public URL, and the schema says so with null rather than
    inventing a link that does not resolve.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    product_id: UUID
    storage_provider: str
    storage_key: str
    mime_type: str
    size_bytes: int
    width: int
    height: int
    checksum_sha256: str
    sort_order: int
    is_primary: bool
    removed_at: datetime | None
    needs_reconciliation: bool
    created_at: datetime
    delivery_url: str | None = None

    @classmethod
    def from_entity(
        cls,
        image: ProductImageModel,
        *,
        delivery_url: str | None = None,
    ) -> ProductImageResponseSchema:
        return cls(
            id=image.id,
            tenant_id=image.tenant_id,
            product_id=image.product_id,
            storage_provider=image.storage_provider,
            storage_key=image.storage_key,
            mime_type=image.mime_type,
            size_bytes=image.size_bytes,
            width=image.width,
            height=image.height,
            checksum_sha256=image.checksum_sha256,
            sort_order=image.sort_order,
            is_primary=image.is_primary,
            removed_at=image.removed_at,
            needs_reconciliation=image.needs_reconciliation(),
            created_at=image.created_at,
            delivery_url=delivery_url,
        )


class ProductImageRemovalResponseSchema(BaseModel):
    """The result of removing an image.

    `storage_released` is the part worth reading: when the provider delete failed, the
    bytes are still stored and still counted against the tenant, and the image is marked
    for reconciliation instead of the row disappearing. A caller that only saw "200 OK"
    would have no way to know a leak was left behind.
    """

    model_config = ConfigDict(extra="forbid")

    image_id: UUID
    storage_released: bool
    reconciliation_required: bool
    released_bytes: int


class ProductImageOrderSchema(BaseModel):
    """A new gallery order, given as the complete list of image identifiers."""

    model_config = ConfigDict(extra="forbid")

    image_ids: Annotated[list[UUID], Field(min_length=1, max_length=100)]


class ProductImageReconciliationResponseSchema(BaseModel):
    """What a reconciliation pass managed to clean up."""

    model_config = ConfigDict(extra="forbid")

    attempted: int
    released: int
    still_pending: int
