"""An in-memory object store, shared by the suites that need one.

A test double, so it lives with the tests. It models the storage port's contract rather than one
provider's behaviour: a key outside the tenant's prefix is refused, deleting something absent is
not an error, and both failure shapes the port defines - a raised error and a typed degraded result
- can be asked for. That is what lets a suite assert what the application does when storage is
unavailable without a network, and why the same double serves the image pipeline and the export.
"""

from __future__ import annotations

from ahia.core.errors import StorageOperationError
from ahia.core.ports.storage_port import (
    StorageUploadRequest,
    StoredObject,
    compute_sha256,
)


class RecordingStorage:
    """An in-memory object store that records what it was asked to do.

    Models the port's contract faithfully: a key that is not inside the tenant's prefix
    is refused, deleting something absent is not an error, and a configured failure
    raises a typed integration error rather than returning an empty success.
    """

    def __init__(self, *, provider_name: str = "recording") -> None:
        self._provider_name = provider_name
        self.objects: dict[str, bytes] = {}
        self.deleted_keys: list[str] = []
        self.upload_requests: list[StorageUploadRequest] = []
        self.fail_uploads = False
        self.fail_deletes = False
        self.degrade_uploads = False

    @property
    def provider_name(self) -> str:
        return self._provider_name

    async def upload(self, request: StorageUploadRequest) -> StoredObject:
        self.upload_requests.append(request)
        if self.fail_uploads:
            raise StorageOperationError(
                operation="storage_upload",
                entity="object",
                identifier=request.key,
                detail="the provider refused the upload",
            )
        if self.degrade_uploads:
            # The port's other failure shape: a typed degraded result rather than a
            # raised error, used when a fallback is configured.
            return StoredObject.degraded(
                provider=self._provider_name,
                key=request.key,
                mime_type=request.mime_type,
                size_bytes=len(request.content),
                checksum_sha256=compute_sha256(request.content),
                reason="provider unavailable",
            )
        self.objects[request.key] = request.content
        return StoredObject(
            provider=self._provider_name,
            key=request.key,
            mime_type=request.mime_type,
            size_bytes=len(request.content),
            checksum_sha256=compute_sha256(request.content),
            delivery_url=f"https://cdn.example.test/{request.key}",
        )

    async def delete(self, *, key: str, tenant_id: str) -> None:
        if not key.startswith(f"tenants/{tenant_id}/"):
            raise StorageOperationError(
                operation="storage_delete",
                entity="object",
                identifier=key,
                detail="key is outside the caller's prefix",
            )
        if self.fail_deletes:
            raise StorageOperationError(
                operation="storage_delete",
                entity="object",
                identifier=key,
                detail="the provider refused the delete",
            )
        self.objects.pop(key, None)
        self.deleted_keys.append(key)

    async def exists(self, *, key: str, tenant_id: str) -> bool:
        return key in self.objects and key.startswith(f"tenants/{tenant_id}/")

    async def build_delivery_url(
        self,
        *,
        key: str,
        presentation_width: int | None = None,
        is_public: bool = False,
    ) -> str:
        return f"https://cdn.example.test/{key}"

    async def close(self) -> None:
        return None
