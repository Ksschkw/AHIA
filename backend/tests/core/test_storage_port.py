"""Tests for the provider-neutral storage port value objects.

The key hierarchy is a security boundary: an object key decides which tenant's
prefix a file lands in. These tests pin the construction rules and the rejection
of anything that could escape a prefix.
"""

from __future__ import annotations

import hashlib

import pytest

from ahia.core.ports.storage_port import (
    StorageCategory,
    StorageObjectKey,
    StoragePort,
    StorageUploadRequest,
    StoredObject,
    compute_sha256,
    key_belongs_to_tenant,
)

TENANT_ID = "8f3a1c2e-0000-4000-8000-000000000001"
PRODUCT_ID = "4b2c9d1e-0000-4000-8000-000000000002"


# ---------------------------------------------------------------------------
# Key construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_key_follows_the_documented_hierarchy() -> None:
    key = StorageObjectKey(
        tenant_id=TENANT_ID,
        category=StorageCategory.PRODUCTS,
        resource_id=PRODUCT_ID,
        filename="hero.webp",
    )

    assert key.value == f"tenants/{TENANT_ID}/products/{PRODUCT_ID}/hero.webp"


@pytest.mark.unit
@pytest.mark.parametrize(
    "category",
    [
        StorageCategory.STOREFRONT,
        StorageCategory.PRODUCTS,
        StorageCategory.RECEIPTS,
        StorageCategory.INVOICES,
        StorageCategory.REPORTS,
        StorageCategory.DOCUMENTS,
    ],
)
def test_every_category_renders_a_tenant_scoped_key(category: StorageCategory) -> None:
    key = StorageObjectKey(
        tenant_id=TENANT_ID,
        category=category,
        resource_id=PRODUCT_ID,
        filename="asset.webp",
    )

    assert key.value.startswith(f"tenants/{TENANT_ID}/")
    assert key.belongs_to_tenant(TENANT_ID)
    assert not key.belongs_to_tenant("another-tenant")


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad_segment",
    [
        "..",
        "../other-tenant",
        "tenants/../..",
        "with/slash",
        "",
        "with space",
        "semi;colon",
        "quote'",
        "a" * 129,
        ".hidden",
    ],
)
def test_key_segments_that_could_escape_the_prefix_are_rejected(bad_segment: str) -> None:
    with pytest.raises(ValueError):
        StorageObjectKey(
            tenant_id=bad_segment,
            category=StorageCategory.PRODUCTS,
            resource_id=PRODUCT_ID,
            filename="hero.webp",
        )


@pytest.mark.unit
def test_filename_is_validated_too() -> None:
    with pytest.raises(ValueError):
        StorageObjectKey(
            tenant_id=TENANT_ID,
            category=StorageCategory.PRODUCTS,
            resource_id=PRODUCT_ID,
            filename="../../etc/passwd",
        )


@pytest.mark.unit
def test_tenant_prefix_matches_the_key() -> None:
    key = StorageObjectKey(
        tenant_id=TENANT_ID,
        category=StorageCategory.PRODUCTS,
        resource_id=PRODUCT_ID,
        filename="hero.webp",
    )

    assert key.tenant_prefix == f"tenants/{TENANT_ID}"
    assert key.value.startswith(key.tenant_prefix + "/")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("key", "tenant_id", "expected"),
    [
        ("tenants/abc/products/xyz/hero.webp", "abc", True),
        ("tenants/abc/products/xyz/hero.webp", "abcd", False),
        ("tenants/abc-evil/products/xyz/hero.webp", "abc", False),
        ("other/abc/products/xyz/hero.webp", "abc", False),
        ("tenants/abc", "abc", False),
    ],
)
def test_key_belongs_to_tenant_requires_a_full_prefix_match(
    key: str, tenant_id: str, expected: bool
) -> None:
    """A shared string prefix is not ownership: `abc` must not match `abc-evil`."""
    assert key_belongs_to_tenant(key, tenant_id) is expected


# ---------------------------------------------------------------------------
# Upload request
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_upload_request_accepts_a_tenant_scoped_key() -> None:
    request = StorageUploadRequest(
        key=f"tenants/{TENANT_ID}/products/{PRODUCT_ID}/hero.webp",
        content=b"image-bytes",
        mime_type="image/webp",
        tenant_id=TENANT_ID,
    )

    assert request.mime_type == "image/webp"


@pytest.mark.unit
def test_upload_request_rejects_a_cross_tenant_key() -> None:
    with pytest.raises(ValueError, match="tenant prefix"):
        StorageUploadRequest(
            key="tenants/some-other-tenant/products/xyz/hero.webp",
            content=b"image-bytes",
            mime_type="image/webp",
            tenant_id=TENANT_ID,
        )


@pytest.mark.unit
def test_upload_request_rejects_empty_content() -> None:
    with pytest.raises(ValueError, match="empty object"):
        StorageUploadRequest(
            key=f"tenants/{TENANT_ID}/products/{PRODUCT_ID}/hero.webp",
            content=b"",
            mime_type="image/webp",
            tenant_id=TENANT_ID,
        )


# ---------------------------------------------------------------------------
# Stored object and checksum
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_stored_object_reports_provider_neutral_metadata() -> None:
    stored = StoredObject(
        provider="r2",
        key=f"tenants/{TENANT_ID}/products/{PRODUCT_ID}/hero.webp",
        mime_type="image/webp",
        size_bytes=12_345,
        checksum_sha256="a" * 64,
        delivery_url="https://cdn.example.com/hero.webp",
        width=1200,
        height=900,
    )

    assert stored.is_degraded is False
    assert stored.degradation_reason == ""
    assert stored.provider == "r2"


@pytest.mark.unit
def test_degraded_result_is_typed_and_carries_the_reason() -> None:
    """A failure must never be represented as an empty success."""
    degraded = StoredObject.degraded(
        provider="cloudinary",
        key=f"tenants/{TENANT_ID}/products/{PRODUCT_ID}/hero.webp",
        mime_type="image/webp",
        size_bytes=4096,
        checksum_sha256="b" * 64,
        reason="provider_unavailable",
    )

    assert degraded.is_degraded is True
    assert degraded.degradation_reason == "provider_unavailable"
    assert degraded.delivery_url is None
    # The key and checksum survive, so the caller can record what was attempted
    # and reconcile later.
    assert degraded.key.endswith("hero.webp")
    assert degraded.checksum_sha256 == "b" * 64


@pytest.mark.unit
def test_checksum_matches_a_known_digest() -> None:
    content = b"AHIA product image"

    assert compute_sha256(content) == hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------------------
# Protocol shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_port_is_structurally_satisfied_by_a_fake_adapter() -> None:
    """Services depend on the protocol, so a test double needs no inheritance."""

    class FakeStorage:
        provider_name = "fake"

        async def upload(self, request: StorageUploadRequest) -> StoredObject:
            return StoredObject(
                provider=self.provider_name,
                key=request.key,
                mime_type=request.mime_type,
                size_bytes=len(request.content),
                checksum_sha256=compute_sha256(request.content),
            )

        async def delete(self, *, key: str, tenant_id: str) -> None:
            return None

        async def exists(self, *, key: str, tenant_id: str) -> bool:
            return False

        async def build_delivery_url(
            self,
            *,
            key: str,
            presentation_width: int | None = None,
            is_public: bool = False,
        ) -> str:
            return f"https://example.invalid/{key}"

        async def close(self) -> None:
            return None

    assert isinstance(FakeStorage(), StoragePort)
