"""The product image entity: one stored picture, described without naming a provider.

A product image is metadata plus a pointer. The bytes live outside the database, in
whichever object storage the deployment selected, and this entity is the row that knows
where they are, how big they are and whether anybody still wants them.

**No column is named after a provider.** The columns are `storage_provider` and
`storage_key`: the first records who holds the bytes, the second is the path within
that provider. A column called `r2_key` would make switching providers a migration
rather than a configuration change, and every row written before the switch would
suddenly be in a column that lies about where it lives. Because the provider is a value
per row, assets written under one provider stay resolvable after a switch - which is
what makes the switch safe rather than merely possible.

Four rules the entity enforces.

The object key is server-shaped and tenant-scoped
    The key is `tenants/{tenant_id}/products/{product_id}/{image_id}` and is built by
    the service from server-side identifiers, never from a client-supplied path. This
    entity checks the shape; the service checks that the key sits inside the tenant's
    prefix, using the storage port's own rule rather than a second copy of it.

The measured size is what the tenant is charged for
    `size_bytes` is the size of the optimized object, not of what was uploaded.
    Charging for the original would overstate usage by an order of magnitude for a
    phone photo that was resized to a fraction of it.

Removal is a state, not a deletion
    `removed_at` marks an image the business no longer wants. The row stays until the
    provider confirms the object is gone: a row deleted while the object still exists
    is storage nobody is accounting for, which is precisely the leak this column
    prevents. When the provider delete fails, `reconciliation_reason` records why, and
    reconciliation retries it.

One primary image per product, and never a removed one
    `is_primary` is decided by the business, not by position: the primary image is the
    one on the storefront card. The database enforces "at most one" with a partial
    unique index; this entity enforces that a removed image cannot be primary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError

MAXIMUM_STORAGE_PROVIDER_LENGTH: Final[int] = 32
MAXIMUM_STORAGE_KEY_LENGTH: Final[int] = 512
MAXIMUM_MIME_TYPE_LENGTH: Final[int] = 128
MAXIMUM_RECONCILIATION_REASON_LENGTH: Final[int] = 200

#: A sha256 digest rendered as lowercase hexadecimal. The checksum is what lets a
#: reconciliation job prove an object is the one this row describes.
_CHECKSUM_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")

#: `type/subtype`, lowercase, no parameters. Parameters and casing would make two rows
#: that describe the same picture compare as different.
_MIME_TYPE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,63}$"
)


@dataclass(frozen=True, slots=True)
class ProductImageModel:
    """One stored picture of one product."""

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
    created_at: datetime
    is_primary: bool = False
    removed_at: datetime | None = None
    reconciliation_reason: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.created_at, field_name="created_at", image_id=self.id)
        if self.removed_at is not None:
            _require_aware(self.removed_at, field_name="removed_at", image_id=self.id)
            if self.removed_at < self.created_at:
                raise EntityInvariantError(
                    operation="build_product_image",
                    entity="product_image",
                    identifier=str(self.id),
                    detail="removed_at is earlier than created_at",
                )

        self._check_storage_reference()
        self._check_content_description()
        self._check_placement()
        self._check_removal()

    # ------------------------------------------------------------------
    # Field rules
    # ------------------------------------------------------------------

    def _check_storage_reference(self) -> None:
        provider = self.storage_provider.strip()
        if not provider:
            raise EntityInvariantError(
                operation="build_product_image",
                entity="product_image",
                identifier=str(self.id),
                detail="storage_provider is empty",
            )
        if len(provider) > MAXIMUM_STORAGE_PROVIDER_LENGTH:
            raise EntityInvariantError(
                operation="build_product_image",
                entity="product_image",
                identifier=str(self.id),
                detail=f"storage_provider exceeds {MAXIMUM_STORAGE_PROVIDER_LENGTH} characters",
            )

        key = self.storage_key
        if not key.strip():
            raise EntityInvariantError(
                operation="build_product_image",
                entity="product_image",
                identifier=str(self.id),
                detail="storage_key is empty",
            )
        if len(key) > MAXIMUM_STORAGE_KEY_LENGTH:
            raise EntityInvariantError(
                operation="build_product_image",
                entity="product_image",
                identifier=str(self.id),
                detail=f"storage_key exceeds {MAXIMUM_STORAGE_KEY_LENGTH} characters",
            )
        # Shape only. Whether the key lives inside this tenant's prefix is checked by
        # the service with the storage port's own rule: a second implementation of the
        # key format here would be a second answer to "whose object is this".
        if key.startswith("/") or key.endswith("/") or ".." in key.split("/"):
            raise EntityInvariantError(
                operation="build_product_image",
                entity="product_image",
                identifier=str(self.id),
                detail="storage_key is not a well-formed object key",
            )

    def _check_content_description(self) -> None:
        if not _MIME_TYPE_PATTERN.match(self.mime_type):
            raise EntityInvariantError(
                operation="build_product_image",
                entity="product_image",
                identifier=str(self.id),
                detail=f"mime_type is not a plain lowercase type/subtype: {self.mime_type!r}",
            )
        if self.size_bytes <= 0:
            raise EntityInvariantError(
                operation="build_product_image",
                entity="product_image",
                identifier=str(self.id),
                detail="size_bytes must be positive",
            )
        for field_name, value in (("width", self.width), ("height", self.height)):
            if value <= 0:
                raise EntityInvariantError(
                    operation="build_product_image",
                    entity="product_image",
                    identifier=str(self.id),
                    detail=f"{field_name} must be positive",
                )
        if not _CHECKSUM_PATTERN.match(self.checksum_sha256):
            raise EntityInvariantError(
                operation="build_product_image",
                entity="product_image",
                identifier=str(self.id),
                detail="checksum_sha256 is not a lowercase hexadecimal sha256 digest",
            )

    def _check_placement(self) -> None:
        if self.sort_order < 0:
            raise EntityInvariantError(
                operation="build_product_image",
                entity="product_image",
                identifier=str(self.id),
                detail="sort_order is negative",
            )

    def _check_removal(self) -> None:
        if self.removed_at is not None and self.is_primary:
            # The storefront card cannot show an image nobody wants any more.
            raise EntityInvariantError(
                operation="build_product_image",
                entity="product_image",
                identifier=str(self.id),
                detail="a removed image cannot be the primary image",
            )
        if self.reconciliation_reason is not None:
            if self.removed_at is None:
                raise EntityInvariantError(
                    operation="build_product_image",
                    entity="product_image",
                    identifier=str(self.id),
                    detail="a reconciliation reason without a removal has no meaning",
                )
            if not self.reconciliation_reason.strip():
                raise EntityInvariantError(
                    operation="build_product_image",
                    entity="product_image",
                    identifier=str(self.id),
                    detail="reconciliation_reason is empty; use None instead",
                )
            if len(self.reconciliation_reason) > MAXIMUM_RECONCILIATION_REASON_LENGTH:
                raise EntityInvariantError(
                    operation="build_product_image",
                    entity="product_image",
                    identifier=str(self.id),
                    detail=(
                        "reconciliation_reason exceeds "
                        f"{MAXIMUM_RECONCILIATION_REASON_LENGTH} characters"
                    ),
                )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        image_id: UUID,
        tenant_id: UUID,
        product_id: UUID,
        storage_provider: str,
        storage_key: str,
        mime_type: str,
        size_bytes: int,
        width: int,
        height: int,
        checksum_sha256: str,
        sort_order: int,
        now: datetime,
        is_primary: bool = False,
    ) -> ProductImageModel:
        """Create an image row from what the provider and the media processor reported.

        The values are unpacked from `StoredObject` and `OptimizedImage` by the service
        rather than passed as those objects, so this entity depends on no port: a domain
        object that knows the shape of an adapter's result has stopped being independent
        of infrastructure.
        """
        return cls(
            id=image_id,
            tenant_id=tenant_id,
            product_id=product_id,
            storage_provider=storage_provider.strip(),
            storage_key=storage_key,
            mime_type=mime_type,
            size_bytes=size_bytes,
            width=width,
            height=height,
            checksum_sha256=checksum_sha256,
            sort_order=sort_order,
            created_at=now,
            is_primary=is_primary,
        )

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def is_removed(self) -> bool:
        """Return True when the business no longer wants this image."""
        return self.removed_at is not None

    def is_visible_to_customers(self) -> bool:
        """Return True when the image is still part of the product's presentation."""
        return self.removed_at is None

    def needs_reconciliation(self) -> bool:
        """Return True when the stored object may still exist after a failed delete."""
        return self.reconciliation_reason is not None

    def describe_for_audit(self) -> dict[str, str]:
        """Return identifiers and the storage reference, never the picture itself.

        The key is included because it is what an operator needs to find the object;
        it is not a credential, and the row is useless for support without it.
        """
        return {
            "image_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "product_id": str(self.product_id),
            "storage_provider": self.storage_provider,
            "storage_key": self.storage_key,
            "is_primary": "true" if self.is_primary else "false",
            "is_removed": "true" if self.is_removed() else "false",
        }

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def shown_at(self, *, sort_order: int, is_primary: bool) -> ProductImageModel:
        """Return the image placed at a position in the product's gallery.

        Removed images are refused: reordering what nobody wants is a no-op that looks
        like a change, and a caller doing it has confused a tombstone for a picture.
        """
        if self.is_removed():
            raise EntityInvariantError(
                operation="reorder_product_image",
                entity="product_image",
                identifier=str(self.id),
                detail="a removed image cannot be placed in the gallery",
            )
        return replace(self, sort_order=sort_order, is_primary=is_primary)

    def marked_primary(self) -> ProductImageModel:
        """Return the image as the product's primary picture."""
        if self.is_removed():
            raise EntityInvariantError(
                operation="mark_primary_image",
                entity="product_image",
                identifier=str(self.id),
                detail="a removed image cannot be the primary image",
            )
        return replace(self, is_primary=True)

    def unmarked_primary(self) -> ProductImageModel:
        """Return the image as an ordinary gallery member."""
        return replace(self, is_primary=False)

    def removed(
        self, *, at: datetime, reconciliation_reason: str | None = None
    ) -> ProductImageModel:
        """Return the image marked as no longer wanted.

        `reconciliation_reason` is set when the stored object could not be deleted. The
        row then carries the reason until reconciliation retries, which is the
        difference between a leak somebody can find and a leak nobody knows about.
        """
        if self.is_removed():
            return self
        return replace(
            self,
            removed_at=at,
            is_primary=False,
            reconciliation_reason=reconciliation_reason,
        )


def _require_aware(moment: datetime, *, field_name: str, image_id: UUID) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="build_product_image",
            entity="product_image",
            identifier=str(image_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
