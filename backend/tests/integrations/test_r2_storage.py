"""Tests for the Cloudflare R2 storage adapter.

No network and no boto3 client: a fake S3 client is injected, so the assertions
are about the adapter's behaviour - key ownership, checksum, error translation,
resilience - rather than about botocore.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import SecretStr

from ahia.core.config import R2Configuration
from ahia.core.errors import (
    DependencyBusyError,
    DependencyCircuitOpenError,
    IntegrationError,
    StorageOperationError,
    StorageUnavailableError,
    TenantIsolationError,
)
from ahia.core.ports.storage_port import StoragePort, StorageUploadRequest, compute_sha256
from ahia.core.resilience import (
    Bulkhead,
    CircuitBreaker,
    CircuitBreakerConfiguration,
    ResiliencePolicy,
    RetryPolicy,
)
from ahia.integrations.storage.r2_client import R2StorageAdapter

TENANT_ID = "8f3a1c2e-0000-4000-8000-000000000001"
OTHER_TENANT_ID = "9b4d2e3f-0000-4000-8000-000000000002"
PRODUCT_ID = "4b2c9d1e-0000-4000-8000-000000000002"
OBJECT_KEY = f"tenants/{TENANT_ID}/products/{PRODUCT_ID}/hero.webp"


class ProviderFailureError(Exception):
    """Stands in for a botocore ClientError."""

    def __init__(self, code: str) -> None:
        super().__init__(f"provider rejected the call with code {code}")
        self.response = {"Error": {"Code": code}}


class FakeS3Client:
    """A minimal S3 surface with programmable failures."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []
        self.head_calls: list[dict[str, Any]] = []
        self.presign_calls: list[dict[str, Any]] = []
        self.put_failure: Exception | None = None
        self.head_failure: Exception | None = None
        self.delete_failure: Exception | None = None
        self.closed = False

    def put_object(self, **kwargs: Any) -> Mapping[str, Any]:
        self.put_calls.append(kwargs)
        if self.put_failure is not None:
            raise self.put_failure
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {"ETag": "fake-etag"}

    def delete_object(self, **kwargs: Any) -> Mapping[str, Any]:
        self.delete_calls.append(kwargs)
        if self.delete_failure is not None:
            raise self.delete_failure
        self.objects.pop(kwargs["Key"], None)
        return {}

    def head_object(self, **kwargs: Any) -> Mapping[str, Any]:
        self.head_calls.append(kwargs)
        if self.head_failure is not None:
            raise self.head_failure
        if kwargs["Key"] not in self.objects:
            raise ProviderFailureError("404")
        return {"ContentLength": len(self.objects[kwargs["Key"]])}

    # Keyword names match boto3's S3 client surface on purpose.
    def generate_presigned_url(
        self,
        client_method: str,
        *,
        Params: Mapping[str, Any],
        ExpiresIn: int,
    ) -> str:
        self.presign_calls.append(
            {"client_method": client_method, "params": dict(Params), "expires_in": ExpiresIn}
        )
        return (
            f"https://account.r2.cloudflarestorage.com/{Params['Bucket']}/{Params['Key']}?sig=fake"
        )

    def close(self) -> None:
        self.closed = True


def build_configuration(**overrides: Any) -> R2Configuration:
    baseline: dict[str, Any] = {
        "endpoint": "https://account.r2.cloudflarestorage.com",
        "access_key_id": SecretStr("r2-access-key"),
        "secret_access_key": SecretStr("r2-secret-key"),
        "bucket": "ahia-test",
        "region": "auto",
        "public_base_url": None,
        "request_timeout_seconds": 5.0,
    }
    baseline.update(overrides)
    return R2Configuration(**baseline)


def build_policy(
    *,
    failure_threshold: int = 3,
    timeout_seconds: float = 1.0,
    retry: RetryPolicy | None = None,
) -> ResiliencePolicy:
    return ResiliencePolicy(
        dependency_name="r2",
        timeout_seconds=timeout_seconds,
        breaker=CircuitBreaker(
            "r2", CircuitBreakerConfiguration(failure_threshold=failure_threshold)
        ),
        bulkhead=Bulkhead("r2", max_concurrent_calls=8),
        retry=retry,
    )


def build_adapter(
    *,
    client: FakeS3Client | None = None,
    policy: ResiliencePolicy | None = None,
    configuration: R2Configuration | None = None,
    signed_url_ttl_seconds: int = 900,
) -> tuple[R2StorageAdapter, FakeS3Client]:
    fake_client = client or FakeS3Client()
    adapter = R2StorageAdapter(
        configuration or build_configuration(),
        policy or build_policy(),
        signed_url_ttl_seconds=signed_url_ttl_seconds,
        client_factory=lambda: fake_client,
    )
    return adapter, fake_client


def build_request(key: str = OBJECT_KEY, *, tenant_id: str = TENANT_ID) -> StorageUploadRequest:
    return StorageUploadRequest(
        key=key,
        content=b"optimized-image-bytes",
        mime_type="image/webp",
        tenant_id=tenant_id,
        filename="hero.webp",
        metadata={"tenant": tenant_id, "checksum": "abc"},
    )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_provider_name_is_r2() -> None:
    adapter, _ = build_adapter()

    assert adapter.provider_name == "r2"


@pytest.mark.unit
def test_describe_never_reveals_credentials() -> None:
    adapter, _ = build_adapter()

    described = repr(adapter.describe())

    assert "r2-secret-key" not in described
    assert "r2-access-key" not in described
    assert "ahia-test" in described


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_upload_returns_provider_neutral_metadata() -> None:
    adapter, client = build_adapter()
    request = build_request()

    stored = await adapter.upload(request)

    assert stored.provider == "r2"
    assert stored.key == OBJECT_KEY
    assert stored.mime_type == "image/webp"
    assert stored.size_bytes == len(request.content)
    assert stored.checksum_sha256 == compute_sha256(request.content)
    assert stored.is_degraded is False
    assert client.objects[OBJECT_KEY] == request.content


@pytest.mark.asyncio
@pytest.mark.unit
async def test_upload_sends_the_configured_bucket_and_content_type() -> None:
    adapter, client = build_adapter()

    await adapter.upload(build_request())

    call = client.put_calls[0]
    assert call["Bucket"] == "ahia-test"
    assert call["ContentType"] == "image/webp"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_upload_metadata_is_ascii_safe() -> None:
    adapter, client = build_adapter()
    request = StorageUploadRequest(
        key=OBJECT_KEY,
        content=b"bytes",
        mime_type="image/webp",
        tenant_id=TENANT_ID,
        metadata={"Tenant Name": "Obi Electronics\nAHIA", "bad key!": "value"},
    )

    await adapter.upload(request)

    metadata = client.put_calls[0]["Metadata"]
    assert all("\n" not in value for value in metadata.values())
    assert all(key.isascii() for key in metadata)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_upload_failure_becomes_a_typed_application_error() -> None:
    adapter, client = build_adapter()
    client.put_failure = ProviderFailureError("SlowDown")

    with pytest.raises(StorageUnavailableError) as captured:
        await adapter.upload(build_request())

    assert "code=SlowDown" in str(captured.value)
    assert "provider rejected the call" not in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_permanent_upload_failure_is_not_reported_as_unavailable() -> None:
    adapter, client = build_adapter()
    client.put_failure = ProviderFailureError("AccessDenied")

    with pytest.raises(StorageOperationError) as captured:
        await adapter.upload(build_request())

    assert "AccessDenied" in str(captured.value)
    assert captured.value.http_status == 502


@pytest.mark.asyncio
@pytest.mark.unit
async def test_external_error_never_names_the_bucket_or_the_provider() -> None:
    adapter, client = build_adapter()
    client.put_failure = ProviderFailureError("ServiceUnavailable")

    with pytest.raises(IntegrationError) as captured:
        await adapter.upload(build_request())

    external = captured.value.external()
    assert "ahia-test" not in external.message
    assert "r2" not in external.message.lower()
    assert "cloudflarestorage" not in external.message


@pytest.mark.asyncio
@pytest.mark.unit
async def test_upload_is_retried_for_a_transient_failure() -> None:
    adapter, client = build_adapter(
        policy=build_policy(
            failure_threshold=10,
            retry=RetryPolicy(max_attempts=3, base_delay_seconds=0.001, max_delay_seconds=0.002),
        )
    )
    attempts = {"count": 0}
    original_put_object = client.put_object

    def flaky_put_object(**kwargs: Any) -> Mapping[str, Any]:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ProviderFailureError("503")
        return original_put_object(**kwargs)

    client.put_object = flaky_put_object  # type: ignore[method-assign]

    stored = await adapter.upload(build_request())

    assert stored.is_degraded is False
    assert attempts["count"] == 3


@pytest.mark.asyncio
@pytest.mark.unit
async def test_upload_times_out_with_a_typed_error() -> None:
    adapter, client = build_adapter(policy=build_policy(timeout_seconds=0.01))

    def slow_put_object(**kwargs: Any) -> Mapping[str, Any]:
        time.sleep(0.5)
        return {}

    client.put_object = slow_put_object  # type: ignore[method-assign]

    with pytest.raises(IntegrationError) as captured:
        await adapter.upload(build_request())

    assert captured.value.error_code in {"DEPENDENCY_TIMEOUT", "DEPENDENCY_UNAVAILABLE"}


@pytest.mark.asyncio
@pytest.mark.unit
async def test_breaker_opens_and_fails_fast_after_repeated_failures() -> None:
    adapter, client = build_adapter(policy=build_policy(failure_threshold=2))
    client.put_failure = ProviderFailureError("503")

    for _ in range(2):
        with pytest.raises(StorageUnavailableError):
            await adapter.upload(build_request())

    with pytest.raises(DependencyCircuitOpenError):
        await adapter.upload(build_request())


# ---------------------------------------------------------------------------
# Delete and exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_delete_removes_the_object() -> None:
    adapter, client = build_adapter()
    await adapter.upload(build_request())

    await adapter.delete(key=OBJECT_KEY, tenant_id=TENANT_ID)

    assert OBJECT_KEY not in client.objects
    assert client.delete_calls[0]["Bucket"] == "ahia-test"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_delete_of_a_missing_object_is_not_an_error() -> None:
    adapter, _ = build_adapter()

    await adapter.delete(key=OBJECT_KEY, tenant_id=TENANT_ID)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_exists_reports_presence() -> None:
    adapter, _ = build_adapter()
    await adapter.upload(build_request())

    assert await adapter.exists(key=OBJECT_KEY, tenant_id=TENANT_ID) is True


@pytest.mark.asyncio
@pytest.mark.unit
async def test_exists_returns_false_for_a_missing_object() -> None:
    adapter, _ = build_adapter()

    assert await adapter.exists(key=OBJECT_KEY, tenant_id=TENANT_ID) is False


@pytest.mark.asyncio
@pytest.mark.unit
async def test_exists_raises_rather_than_answering_false_when_the_provider_fails() -> None:
    """`False` is an answer; it must not be given when the truth is unknown."""
    adapter, client = build_adapter()
    client.head_failure = ProviderFailureError("503")

    with pytest.raises(StorageUnavailableError):
        await adapter.exists(key=OBJECT_KEY, tenant_id=TENANT_ID)


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.parametrize("method_name", ["delete", "exists"])
async def test_cross_tenant_key_is_rejected_before_the_provider_is_called(
    method_name: str, caplog: pytest.LogCaptureFixture
) -> None:
    adapter, client = build_adapter()
    cross_tenant_key = f"tenants/{OTHER_TENANT_ID}/products/{PRODUCT_ID}/hero.webp"

    with (
        caplog.at_level(logging.ERROR, logger="ahia.integrations.storage.r2"),
        pytest.raises(TenantIsolationError) as captured,
    ):
        if method_name == "delete":
            await adapter.delete(key=cross_tenant_key, tenant_id=TENANT_ID)
        else:
            await adapter.exists(key=cross_tenant_key, tenant_id=TENANT_ID)

    assert "tenant prefix" in str(captured.value)
    # Externally this is a 404 that is indistinguishable from a missing object,
    # which is the same answer the Cloudinary adapter gives.
    assert captured.value.external().code == "NOT_FOUND"
    assert client.delete_calls == []
    assert client.head_calls == []
    assert caplog.records[0].getMessage() == "storage_cross_tenant_key_rejected"


# ---------------------------------------------------------------------------
# Delivery URLs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_private_asset_gets_a_signed_url() -> None:
    adapter, client = build_adapter(signed_url_ttl_seconds=120)

    url = await adapter.build_delivery_url(key=OBJECT_KEY)

    assert "sig=fake" in url
    assert client.presign_calls[0]["expires_in"] == 120
    assert client.presign_calls[0]["params"]["Key"] == OBJECT_KEY


@pytest.mark.asyncio
@pytest.mark.unit
async def test_public_asset_uses_the_configured_public_base_url() -> None:
    adapter, client = build_adapter(
        configuration=build_configuration(public_base_url="https://cdn.ahia.app")
    )

    url = await adapter.build_delivery_url(key=OBJECT_KEY, is_public=True)

    assert url == f"https://cdn.ahia.app/{OBJECT_KEY}"
    assert client.presign_calls == []


@pytest.mark.asyncio
@pytest.mark.unit
async def test_public_request_without_a_public_base_url_still_signs() -> None:
    """No configured public origin means no unauthenticated path."""
    adapter, client = build_adapter()

    url = await adapter.build_delivery_url(key=OBJECT_KEY, is_public=True)

    assert "sig=fake" in url
    assert len(client.presign_calls) == 1


@pytest.mark.asyncio
@pytest.mark.unit
async def test_presentation_width_is_accepted_and_ignored_by_r2() -> None:
    """R2 has no server-side transform; the port stays provider-neutral."""
    adapter, _ = build_adapter()

    url = await adapter.build_delivery_url(key=OBJECT_KEY, presentation_width=480)

    assert "sig=fake" in url


@pytest.mark.asyncio
@pytest.mark.unit
async def test_uploaded_object_reports_a_delivery_url() -> None:
    adapter, _ = build_adapter()

    stored = await adapter.upload(build_request())

    assert stored.delivery_url is not None


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_close_releases_the_client() -> None:
    adapter, client = build_adapter()
    await adapter.upload(build_request())

    await adapter.close()

    assert client.closed is True


@pytest.mark.asyncio
@pytest.mark.unit
async def test_close_is_safe_when_no_client_was_created() -> None:
    adapter, _ = build_adapter()

    await adapter.close()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_adapter_satisfies_the_storage_port() -> None:
    adapter, _ = build_adapter()

    assert isinstance(adapter, StoragePort)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_bulkhead_refuses_concurrent_uploads_beyond_its_limit() -> None:
    """A full bulkhead refuses rather than queueing without bound."""
    adapter, _ = build_adapter(
        policy=ResiliencePolicy(
            dependency_name="r2",
            timeout_seconds=5.0,
            breaker=CircuitBreaker("r2", CircuitBreakerConfiguration(failure_threshold=10)),
            bulkhead=Bulkhead("r2", max_concurrent_calls=1),
        )
    )

    results = await asyncio.gather(
        *(adapter.upload(build_request()) for _ in range(3)),
        return_exceptions=True,
    )

    refusals = [result for result in results if isinstance(result, DependencyBusyError)]
    successes = [result for result in results if not isinstance(result, Exception)]

    assert len(refusals) == 2
    assert len(successes) == 1


@pytest.mark.asyncio
@pytest.mark.unit
async def test_bulkhead_can_queue_when_a_bounded_wait_is_configured() -> None:
    adapter, _ = build_adapter(
        policy=ResiliencePolicy(
            dependency_name="r2",
            timeout_seconds=5.0,
            breaker=CircuitBreaker("r2", CircuitBreakerConfiguration(failure_threshold=10)),
            bulkhead=Bulkhead("r2", max_concurrent_calls=1, max_wait_seconds=2.0),
        )
    )

    results = await asyncio.gather(*(adapter.upload(build_request()) for _ in range(3)))

    assert all(result.is_degraded is False for result in results)
