"""Product image use cases: the upload pipeline, the gallery, and removal.

**The pipeline, in order, and why the order matters.**

    1. authorize                     products.update
    2. resolve the product           tenant-scoped, so another business's product is a 404
    3. check the per-product limit   before spending anything
    4. validate and optimize         decode, refuse a bomb, resize down, strip metadata
    5. reserve tenant quota          holds the bytes against the quota while the upload runs
    6. upload through the port       under a key the server builds, never a client's
    7. persist the metadata          and commit the reservation, in one transaction
    8. compensate on failure         delete the object and release the reservation

Step 4 precedes step 5 because the size that is charged for is the *optimized* size: a
6 MB phone photo becomes a 90 KB WebP, and reserving the original would overstate usage
by an order of magnitude. Step 3 precedes step 4 because a business that already has the
maximum number of images should be told so before the server decodes anything.

**CLIENT-SIDE VALIDATION IS NOT SECURITY.** The client checks a file's size and type to
save a trader's data on a slow connection. Every one of those checks is repeated here,
against the bytes that actually arrived, and the declared content type is compared with
the format that was decoded - a client can be modified, and a declared type is a claim.

**The key is built by the server.** `tenants/{tenant_id}/products/{product_id}/{image_id}`
comes from identifiers the server generated or verified. Nothing a client sends reaches
the object store, so a client cannot write into another tenant's prefix or overwrite an
existing object.

**A failure after the upload compensates rather than leaving wreckage.** If the metadata
row cannot be written, the object is deleted and the reservation released. If that
compensating delete fails, the failure is logged loudly with the key, because an object
nobody references is exactly the leak the reconciliation path exists to find.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid4

from ahia.core.config import StorageLimits
from ahia.core.database import UnitOfWork
from ahia.core.errors import (
    InvalidInputError,
    NotFoundError,
    ResourceLimitExceededError,
    StorageUnavailableError,
)
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.permissions.product_permissions import PRODUCTS_READ, PRODUCTS_UPDATE
from ahia.core.ports.media_port import MediaProcessingPort, OptimizedImage
from ahia.core.ports.storage_port import (
    StorageCategory,
    StorageObjectKey,
    StoragePort,
    StorageUploadRequest,
    StoredObject,
    key_belongs_to_tenant,
)
from ahia.core.tenant_context import TenantContext
from ahia.crud import product_crud, product_image_crud
from ahia.models.entities.product_image_model import ProductImageModel
from ahia.services.storage_quota_service import StorageQuotaService

_PRODUCT_IMAGE_LOGGER_NAME: Final[str] = "ahia.services.product_image"

#: Why a stored object was left behind, recorded on the row so reconciliation can retry.
REASON_PROVIDER_DELETE_FAILED: Final[str] = "provider delete failed"

#: The image formats the media processor can store, mapped to a file extension for the
#: object key. The extension is a convenience for a human reading a bucket listing; the
#: mime type on the row is what the delivery path uses.
_EXTENSION_BY_MIME_TYPE: Final[dict[str, str]] = {
    "image/webp": "webp",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/avif": "avif",
}


@dataclass(frozen=True, slots=True)
class ProductImageRemoval:
    """What happened when an image was removed."""

    image_id: UUID
    storage_released: bool
    reconciliation_required: bool
    released_bytes: int


@dataclass(frozen=True, slots=True)
class ProductImageReconciliation:
    """What a reconciliation pass managed to clean up."""

    attempted: int
    released: int
    still_pending: int


class ProductImageService:
    """Gallery use cases."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        storage: StoragePort,
        media: MediaProcessingPort,
        storage_quota_service: StorageQuotaService,
        limits: StorageLimits,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._storage = storage
        self._media = media
        self._quota = storage_quota_service
        self._limits = limits
        self._logger = (logger or get_logger(_PRODUCT_IMAGE_LOGGER_NAME)).bind(
            component="product_image_service", layer="service"
        )

    # ------------------------------------------------------------------
    # The upload pipeline
    # ------------------------------------------------------------------

    async def attach_image(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
        content: bytes,
        declared_content_type: str,
        is_primary: bool = False,
    ) -> ProductImageModel:
        """Validate, optimize, store and record one image against a product.

        Returns the stored metadata. The caller is handed an entity, not a row and not a
        provider object: whatever the adapter answered has been reduced to neutral
        facts by this point.
        """
        tenant_context.require_permission(
            PRODUCTS_UPDATE,
            operation="attach_product_image",
            resource_type="product",
            resource_id=str(product_id),
            logger=self._logger,
        )

        await self._require_product(tenant_context, product_id=product_id)
        await self._require_gallery_space(tenant_context, product_id=product_id)

        # Raises InvalidMediaError for an oversize file, an unlisted content type, a
        # decoded format that disagrees with the declared one, or a decompression bomb.
        optimized = await self._media.optimize(
            content=content,
            declared_content_type=declared_content_type,
            maximum_size_bytes=self._limits.max_product_image_bytes,
        )

        image_id = uuid4()
        key = self._build_key(
            tenant_id=tenant_context.tenant_id,
            product_id=product_id,
            image_id=image_id,
            mime_type=optimized.mime_type,
        )
        reservation = await self._quota.reserve(
            tenant_context,
            incoming_bytes=optimized.size_bytes,
            operation="attach_product_image",
        )

        try:
            stored = await self._upload(
                key=key,
                content=optimized.content,
                optimized_mime=optimized.mime_type,
                tenant_id=tenant_context.tenant_id,
                product_id=product_id,
            )
        except Exception:
            # The provider raised. Nothing was stored, so the claim goes back before the
            # failure is re-raised: a reservation nobody releases is quota the tenant
            # paid for and cannot use until the stale-reservation reaper runs.
            await self._quota.release_reservation(reservation, reason="upload_failed")
            raise

        if stored.is_degraded:
            # The port reports a degraded result rather than an empty success. Nothing
            # was stored, so the reservation goes back and the caller gets a typed
            # failure instead of a row pointing at an object that does not exist.
            await self._quota.release_reservation(
                reservation, reason=stored.degradation_reason or "upload_degraded"
            )
            raise StorageUnavailableError(
                operation="attach_product_image",
                entity="product_image",
                identifier=str(image_id),
                detail=(
                    f"the storage provider did not accept the upload: {stored.degradation_reason}"
                ),
            )

        try:
            image = await self._persist(
                tenant_context,
                product_id=product_id,
                image_id=image_id,
                stored=stored,
                optimized=optimized,
                is_primary=is_primary,
            )
        except Exception:
            # The object is already stored. Leaving it would be an object nobody
            # references and nobody is charged for, so it is deleted and the reservation
            # released before the failure is re-raised.
            await self._compensate_failed_persist(
                tenant_context, key=key, reason="metadata_write_failed"
            )
            await self._quota.release_reservation(reservation, reason="metadata_write_failed")
            raise

        await self._quota.commit_reservation(reservation, operation="attach_product_image")

        self._logger.info(
            "product_image_attached",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            product_id=str(product_id),
            image_id=str(image.id),
            storage_provider=stored.provider,
            mime_type=image.mime_type,
            stored_bytes=image.size_bytes,
            uploaded_bytes=optimized.original_size_bytes,
            was_resized=optimized.was_resized,
            is_primary=image.is_primary,
        )
        return image

    async def _upload(
        self,
        *,
        key: StorageObjectKey,
        content: bytes,
        optimized_mime: str,
        tenant_id: UUID,
        product_id: UUID,
    ) -> StoredObject:
        return await self._storage.upload(
            StorageUploadRequest(
                key=key.value,
                content=content,
                mime_type=optimized_mime,
                tenant_id=str(tenant_id),
                filename=key.filename,
                metadata={"product_id": str(product_id)},
            )
        )

    async def _persist(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
        image_id: UUID,
        stored: StoredObject,
        optimized: OptimizedImage,
        is_primary: bool,
    ) -> ProductImageModel:
        """Write the metadata row, demoting the previous cover in the same transaction."""
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            next_position = await product_image_crud.count_for_product(
                session, tenant_id=tenant_context.tenant_id, product_id=product_id
            )

            if is_primary:
                await self._demote_current_primary(
                    session, tenant_context=tenant_context, product_id=product_id
                )

            image = await product_image_crud.create(
                session,
                ProductImageModel.create(
                    image_id=image_id,
                    tenant_id=tenant_context.tenant_id,
                    product_id=product_id,
                    storage_provider=stored.provider,
                    storage_key=stored.key,
                    mime_type=stored.mime_type,
                    size_bytes=stored.size_bytes,
                    width=optimized.width,
                    height=optimized.height,
                    checksum_sha256=stored.checksum_sha256,
                    sort_order=next_position,
                    now=datetime.now(UTC),
                    is_primary=is_primary,
                ),
            )
            await unit_of_work.commit()
        return image

    # ------------------------------------------------------------------
    # Reading the gallery
    # ------------------------------------------------------------------

    async def list_images(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
    ) -> list[ProductImageModel]:
        """Return a product's gallery, in the order the business arranged it."""
        tenant_context.require_permission(
            PRODUCTS_READ,
            operation="list_product_images",
            resource_type="product",
            resource_id=str(product_id),
            logger=self._logger,
        )
        await self._require_product(tenant_context, product_id=product_id)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            return await product_image_crud.list_for_product(
                unit_of_work.session_handle,
                tenant_id=tenant_context.tenant_id,
                product_id=product_id,
            )

    async def build_delivery_url(self, image: ProductImageModel) -> str | None:
        """Return a URL for the image, built now rather than stored.

        The URL depends on the active provider and on whether the object is public, so
        storing one would be storing a fact that changes. The key and the provider are
        the durable facts; this is derived from them on every read.
        """
        return await self._storage.build_delivery_url(
            key=image.storage_key,
            presentation_width=self._limits.max_image_width,
            is_public=True,
        )

    # ------------------------------------------------------------------
    # Arranging the gallery
    # ------------------------------------------------------------------

    async def set_primary_image(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
        image_id: UUID,
    ) -> ProductImageModel:
        """Make one image the product's cover, demoting whatever held it."""
        tenant_context.require_permission(
            PRODUCTS_UPDATE,
            operation="set_primary_product_image",
            resource_type="product",
            resource_id=str(product_id),
            logger=self._logger,
        )

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            await self._require_product(tenant_context, product_id=product_id)
            image = await product_image_crud.require_by_id(
                session, tenant_id=tenant_context.tenant_id, image_id=image_id
            )
            if image.product_id != product_id:
                raise NotFoundError(
                    operation="set_primary_product_image",
                    entity="product_image",
                    identifier=str(image_id),
                    detail="no image matched on this product",
                )
            await self._demote_current_primary(
                session, tenant_context=tenant_context, product_id=product_id
            )
            stored = await product_image_crud.update(session, image.marked_primary())
            await unit_of_work.commit()

        self._logger.info(
            "product_image_marked_primary",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            product_id=str(product_id),
            image_id=str(image_id),
        )
        return stored

    async def reorder_images(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
        image_ids: Sequence[UUID],
    ) -> list[ProductImageModel]:
        """Apply a complete gallery order.

        The whole order is required, not a single move: a partial order leaves the
        positions of the images that were not mentioned ambiguous, and two clients
        dragging pictures at once would interleave into an order neither of them asked
        for. An order that does not name exactly the current gallery is refused, so a
        client cannot drop an image out of the gallery by forgetting it.
        """
        tenant_context.require_permission(
            PRODUCTS_UPDATE,
            operation="reorder_product_images",
            resource_type="product",
            resource_id=str(product_id),
            logger=self._logger,
        )

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            await self._require_product(tenant_context, product_id=product_id)
            gallery = await product_image_crud.list_for_product(
                session, tenant_id=tenant_context.tenant_id, product_id=product_id
            )
            current_ids = {image.id for image in gallery}

            if set(image_ids) != current_ids or len(image_ids) != len(current_ids):
                raise InvalidInputError(
                    operation="reorder_product_images",
                    entity="product_image",
                    identifier=str(product_id),
                    detail=(
                        "the order must name every image in the gallery exactly once; "
                        f"the gallery holds {len(current_ids)}"
                    ),
                )

            by_id = {image.id: image for image in gallery}
            for position, image_id in enumerate(image_ids):
                current = by_id[image_id]
                await product_image_crud.update(
                    session,
                    # The cover flag is preserved: arranging the gallery is not a
                    # statement about which picture is on the card.
                    current.shown_at(sort_order=position, is_primary=current.is_primary),
                )
            stored = await product_image_crud.list_for_product(
                session, tenant_id=tenant_context.tenant_id, product_id=product_id
            )
            await unit_of_work.commit()

        self._logger.info(
            "product_images_reordered",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            product_id=str(product_id),
            image_count=len(stored),
        )
        return stored

    # ------------------------------------------------------------------
    # Removal
    # ------------------------------------------------------------------

    async def remove_image(
        self,
        tenant_context: TenantContext,
        *,
        product_id: UUID,
        image_id: UUID,
    ) -> ProductImageRemoval:
        """Delete the stored object, release its quota, and drop the row.

        Removal is not a database delete with a provider call attached: the object is
        deleted first, and the row is only removed once the provider confirms. When the
        delete fails, the row stays with a reconciliation reason and the quota stays
        committed, because the bytes are still there. Releasing quota for an object that
        still exists would understate usage and let storage grow with nobody watching.
        """
        tenant_context.require_permission(
            PRODUCTS_UPDATE,
            operation="remove_product_image",
            resource_type="product",
            resource_id=str(product_id),
            logger=self._logger,
        )

        now = datetime.now(UTC)
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            session = unit_of_work.session_handle
            image = await product_image_crud.require_by_id(
                session, tenant_id=tenant_context.tenant_id, image_id=image_id
            )
            if image.product_id != product_id:
                raise NotFoundError(
                    operation="remove_product_image",
                    entity="product_image",
                    identifier=str(image_id),
                    detail="no image matched on this product",
                )

            deleted = await self._delete_object(
                tenant_context, image=image, operation="remove_product_image"
            )

            if not deleted:
                stored = await product_image_crud.update(
                    session,
                    image.removed(at=now, reconciliation_reason=REASON_PROVIDER_DELETE_FAILED),
                )
                await unit_of_work.commit()
                self._logger.warning(
                    "product_image_removal_pending_reconciliation",
                    tenant_id=str(tenant_context.tenant_id),
                    actor_id=str(tenant_context.user_id),
                    product_id=str(product_id),
                    image_id=str(image_id),
                    storage_key=image.storage_key,
                    bytes_still_stored=image.size_bytes,
                    security_event="storage_leak_prevented",
                )
                return ProductImageRemoval(
                    image_id=stored.id,
                    storage_released=False,
                    reconciliation_required=True,
                    released_bytes=0,
                )

            await product_image_crud.delete_row(session, image)
            await unit_of_work.commit()
            released_bytes = image.size_bytes

        await self._quota.record_deletion(
            tenant_context,
            removed_bytes=released_bytes,
            operation="remove_product_image",
        )

        self._logger.info(
            "product_image_removed",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            product_id=str(product_id),
            image_id=str(image_id),
            released_bytes=released_bytes,
        )
        return ProductImageRemoval(
            image_id=image_id,
            storage_released=True,
            reconciliation_required=False,
            released_bytes=released_bytes,
        )

    async def reconcile_pending_deletions(
        self,
        tenant_context: TenantContext,
    ) -> ProductImageReconciliation:
        """Retry deletions that failed, releasing quota for the ones that now succeed.

        A row marked for reconciliation is retried and either cleaned up or left marked
        again. Nothing here removes a row whose object it could not delete: the point of
        the pass is to reduce the leak, never to hide it.
        """
        tenant_context.require_permission(
            PRODUCTS_UPDATE,
            operation="reconcile_product_images",
            resource_type="product_image",
            resource_id=str(tenant_context.tenant_id),
            logger=self._logger,
        )

        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            pending = await product_image_crud.list_pending_reconciliation(
                unit_of_work.session_handle, tenant_context.tenant_id
            )

        released = 0
        still_pending = 0
        for image in pending:
            if await self._delete_object(
                tenant_context, image=image, operation="reconcile_product_images"
            ):
                unit_of_work = self._unit_of_work_factory()
                async with unit_of_work:
                    session = unit_of_work.session_handle
                    current = await product_image_crud.get_by_id(
                        session, tenant_id=tenant_context.tenant_id, image_id=image.id
                    )
                    if current is None:
                        # Another pass, or an operator, already cleaned it up.
                        continue
                    await product_image_crud.delete_row(session, current)
                    await unit_of_work.commit()
                await self._quota.record_deletion(
                    tenant_context,
                    removed_bytes=image.size_bytes,
                    operation="reconcile_product_images",
                )
                released += 1
            else:
                still_pending += 1

        self._logger.info(
            "product_image_reconciliation_completed",
            tenant_id=str(tenant_context.tenant_id),
            actor_id=str(tenant_context.user_id),
            attempted=len(pending),
            released=released,
            still_pending=still_pending,
        )
        return ProductImageReconciliation(
            attempted=len(pending), released=released, still_pending=still_pending
        )

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def _delete_object(
        self,
        tenant_context: TenantContext,
        *,
        image: ProductImageModel,
        operation: str,
    ) -> bool:
        """Delete the stored object, reporting whether the provider confirmed it."""
        self._logger.info(
            "product_image_delete_attempted",
            tenant_id=str(tenant_context.tenant_id),
            image_id=str(image.id),
            storage_provider=image.storage_provider,
            storage_key=image.storage_key,
            operation=operation,
        )
        try:
            await self._storage.delete(
                key=image.storage_key, tenant_id=str(tenant_context.tenant_id)
            )
        except Exception as error:  # noqa: BLE001 - any provider failure means "still stored"
            self._logger.error(
                "product_image_delete_failed",
                tenant_id=str(tenant_context.tenant_id),
                image_id=str(image.id),
                storage_key=image.storage_key,
                operation=operation,
                error_type=type(error).__name__,
            )
            return False
        return True

    async def _compensate_failed_persist(
        self,
        tenant_context: TenantContext,
        *,
        key: StorageObjectKey,
        reason: str,
    ) -> None:
        """Delete an object that was stored but will never be referenced."""
        if not key_belongs_to_tenant(key.value, str(tenant_context.tenant_id)):
            # Cannot happen: the key was built from the authorized tenant. If it ever
            # did, deleting it would be a cross-tenant write, so it is refused loudly
            # rather than attempted.
            self._logger.error(
                "product_image_compensation_refused",
                tenant_id=str(tenant_context.tenant_id),
                storage_key=key.value,
                reason="key_outside_tenant_prefix",
            )
            return
        try:
            await self._storage.delete(key=key.value, tenant_id=str(tenant_context.tenant_id))
        except Exception as error:  # noqa: BLE001 - reported, never raised over the original
            # An object nobody references is exactly the leak reconciliation exists to
            # find, so the key is logged at ERROR with the tenant it belongs to.
            self._logger.error(
                "product_image_compensation_failed",
                tenant_id=str(tenant_context.tenant_id),
                storage_key=key.value,
                reason=reason,
                error_type=type(error).__name__,
                security_event="orphaned_object_created",
            )

    async def _demote_current_primary(
        self,
        session: object,
        *,
        tenant_context: TenantContext,
        product_id: UUID,
    ) -> None:
        """Clear the primary flag from whichever image currently holds it.

        Done inside the caller's transaction, so the demotion and the promotion commit
        together. Two simultaneous requests are then serialised by the partial unique
        index rather than by luck: the second one fails loudly instead of producing two
        covers.
        """
        gallery = await product_image_crud.list_for_product(
            session,  # type: ignore[arg-type]
            tenant_id=tenant_context.tenant_id,
            product_id=product_id,
        )
        for image in gallery:
            if image.is_primary:
                await product_image_crud.update(
                    session,  # type: ignore[arg-type]
                    image.unmarked_primary(),
                )

    async def _require_product(self, tenant_context: TenantContext, *, product_id: UUID) -> None:
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            product = await product_crud.get_by_id(
                unit_of_work.session_handle,
                tenant_id=tenant_context.tenant_id,
                product_id=product_id,
            )
        if product is None:
            self._logger.warning(
                "product_image_access_denied",
                reason="product_not_in_tenant",
                tenant_id=str(tenant_context.tenant_id),
                product_id=str(product_id),
                security_event="tenant_isolation",
            )
            raise NotFoundError(
                operation="attach_product_image",
                entity="product",
                identifier=str(product_id),
                detail="no product matched in this business",
            )

    async def _require_gallery_space(
        self, tenant_context: TenantContext, *, product_id: UUID
    ) -> None:
        unit_of_work = self._unit_of_work_factory()
        async with unit_of_work:
            used = await product_image_crud.count_for_product(
                unit_of_work.session_handle,
                tenant_id=tenant_context.tenant_id,
                product_id=product_id,
            )
        if used >= self._limits.max_images_per_product:
            raise ResourceLimitExceededError(
                operation="attach_product_image",
                entity="product_image",
                identifier=str(product_id),
                detail=(
                    f"this product already has the maximum of "
                    f"{self._limits.max_images_per_product} images"
                ),
            )

    def _build_key(
        self,
        *,
        tenant_id: UUID,
        product_id: UUID,
        image_id: UUID,
        mime_type: str,
    ) -> StorageObjectKey:
        """Build the object key from server-side identifiers.

        The extension comes from the stored format rather than from the uploaded
        filename: a client-supplied name would let a caller suggest a path, and the
        stored format is the only thing that describes the object's contents.
        """
        extension = _EXTENSION_BY_MIME_TYPE.get(mime_type, "bin")
        return StorageObjectKey(
            tenant_id=str(tenant_id),
            category=StorageCategory.PRODUCTS,
            resource_id=str(product_id),
            filename=f"{image_id}.{extension}",
        )
