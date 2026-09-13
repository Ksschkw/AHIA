"""The provider-neutral object storage port.

Services depend on this module. They never depend on an adapter, and they never
learn whether the bytes ended up on Cloudflare R2 or Cloudinary.

The contract is deliberately narrow: the operations AHIA actually performs, over
value objects that mean the same thing regardless of who stores the file.

* no Cloudinary public identifier, no bucket name, no region, no endpoint
* no provider SDK type anywhere in a signature
* no method that returns ``None`` to mean "the provider was unavailable". A
  provider that is down produces a typed degraded object, so a caller cannot
  mistake a failure for an empty success.

Object keys are built from server-side identifiers by `StorageObjectKey`, never
from a client-supplied path. A client that can choose its own key can write into
another tenant's prefix.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


class StorageCategory(StrEnum):
    """The top-level folders of the object key hierarchy.

    A closed set. A free-form folder name would let a caller invent a prefix and
    escape the tenant scope.
    """

    STOREFRONT = "storefront"
    PRODUCTS = "products"
    RECEIPTS = "receipts"
    INVOICES = "invoices"
    REPORTS = "reports"
    DOCUMENTS = "documents"


_SEGMENT_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validate_segment(value: str, *, field_name: str) -> str:
    """Reject any identifier that could escape its folder or confuse a key."""
    if not _SEGMENT_PATTERN.match(value):
        raise ValueError(
            f"{field_name} must match {_SEGMENT_PATTERN.pattern}; "
            "path separators, traversal segments and empty values are rejected"
        )
    return value


@dataclass(frozen=True, slots=True)
class StorageObjectKey:
    """A server-constructed object key.

    Renders as ``tenants/{tenant_id}/{category}/{resource_id}/{filename}``, the
    hierarchy fixed by the database and domain specification.
    """

    tenant_id: str
    category: StorageCategory
    resource_id: str
    filename: str

    def __post_init__(self) -> None:
        _validate_segment(self.tenant_id, field_name="tenant_id")
        _validate_segment(self.resource_id, field_name="resource_id")
        _validate_segment(self.filename, field_name="filename")

    @property
    def value(self) -> str:
        """Return the canonical key string."""
        return str(
            PurePosixPath("tenants")
            / self.tenant_id
            / self.category.value
            / self.resource_id
            / self.filename
        )

    @property
    def tenant_prefix(self) -> str:
        """Return the tenant prefix, used for ownership checks."""
        return str(PurePosixPath("tenants") / self.tenant_id)

    def belongs_to_tenant(self, tenant_id: str) -> bool:
        """Return True when this key lives under the given tenant's prefix."""
        return self.value.startswith(str(PurePosixPath("tenants") / tenant_id) + "/")


def key_belongs_to_tenant(key: str, tenant_id: str) -> bool:
    """Return True when a key string is inside a tenant's prefix.

    Used to reject a key that arrived from anywhere other than
    `StorageObjectKey`.
    """
    prefix = str(PurePosixPath("tenants") / tenant_id)
    return key.startswith(prefix + "/")


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StorageUploadRequest:
    """One object to store."""

    key: str
    content: bytes
    mime_type: str
    tenant_id: str
    filename: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.content:
            raise ValueError("refusing to store an empty object")
        if not key_belongs_to_tenant(self.key, self.tenant_id):
            raise ValueError(
                "object key does not live under the tenant prefix; "
                "a cross-tenant key is a defect, not a request error"
            )


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Provider-neutral metadata about a stored object.

    This is what the database row is built from. It carries the provider that
    actually holds the bytes, so an asset written before a provider switch stays
    resolvable afterwards.
    """

    provider: str
    key: str
    mime_type: str
    size_bytes: int
    checksum_sha256: str
    delivery_url: str | None = None
    width: int | None = None
    height: int | None = None
    is_degraded: bool = False
    degradation_reason: str = ""

    @classmethod
    def degraded(
        cls,
        *,
        provider: str,
        key: str,
        mime_type: str,
        size_bytes: int,
        checksum_sha256: str,
        reason: str,
    ) -> StoredObject:
        """Return a typed result for an upload that could not be completed.

        The key and checksum are still reported, so the caller can record what
        was attempted and reconcile later. What is never reported is a success
        that did not happen.
        """
        return cls(
            provider=provider,
            key=key,
            mime_type=mime_type,
            size_bytes=size_bytes,
            checksum_sha256=checksum_sha256,
            delivery_url=None,
            is_degraded=True,
            degradation_reason=reason,
        )


def compute_sha256(content: bytes) -> str:
    """Return the hex digest used as the object checksum.

    Computed locally so the checksum is available even when the provider is
    unreachable, and so it does not depend on a provider reporting one.
    """
    return hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------------------
# Port
# ---------------------------------------------------------------------------


@runtime_checkable
class StoragePort(Protocol):
    """The storage capability a service receives.

    Implementations live under ``ahia.integrations.storage``. Every method is
    asynchronous and every method applies the adapter's resilience policy.
    """

    @property
    def provider_name(self) -> str:
        """Return the provider identifier persisted alongside every object."""
        ...

    async def upload(self, request: StorageUploadRequest) -> StoredObject:
        """Store an object and return its provider-neutral metadata.

        Raises a typed integration error when the provider fails and no fallback
        is configured. Returns a degraded `StoredObject` when the policy is
        configured to degrade instead.
        """
        ...

    async def delete(self, *, key: str, tenant_id: str) -> None:
        """Delete an object. Deleting a missing object is not an error.

        `tenant_id` is required so the adapter can verify the key is inside the
        caller's prefix before issuing a delete. A provider call cannot be
        undone, so the ownership check happens before the request, not after.
        """
        ...

    async def exists(self, *, key: str, tenant_id: str) -> bool:
        """Return True when the object exists and belongs to the tenant."""
        ...

    async def build_delivery_url(
        self,
        *,
        key: str,
        presentation_width: int | None = None,
        is_public: bool = False,
    ) -> str:
        """Return a URL a client can fetch the object from.

        `presentation_width` is a neutral request for a rendition appropriate to
        the UI. A provider that supports server-side transformations encodes it;
        a provider that does not returns the stored object, and the client sizes
        it. The caller never passes a transformation string.
        """
        ...

    async def close(self) -> None:
        """Release the adapter's resources. Called from application shutdown."""
        ...
