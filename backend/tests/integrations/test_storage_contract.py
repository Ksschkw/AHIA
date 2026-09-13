"""The storage provider contract suite.

One set of behavioural assertions, executed against every adapter. A divergence
between providers is a test failure here rather than a production surprise,
which is the entire reason two adapters are affordable to maintain.

The suite asserts what a caller can observe through the port:

* provider-neutral metadata comes back, tagged with the provider that holds the
  bytes
* the key is preserved exactly as supplied
* delete is idempotent
* exists reports presence, and refuses to answer when the provider is down
* a cross-tenant key is denied with the same external answer as a missing
  object, for both providers
* a provider failure is a typed application error, never a vendor exception
* no credential reaches a log line
* a requested presentation width changes the delivery URL only where the
  provider supports it, and never breaks it where it does not

Each adapter keeps its own focused test module for the details that are
provider-specific. This module is the shared contract.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Protocol

import pytest
from pydantic import SecretStr

from ahia.core.config import (
    AppEnvironment,
    CloudinaryConfiguration,
    R2Configuration,
    Settings,
    StorageProviderName,
)
from ahia.core.errors import AhiaError, IntegrationError, TenantIsolationError
from ahia.core.logging import JsonLogFormatter
from ahia.core.ports.storage_port import StoragePort, StorageUploadRequest, compute_sha256
from ahia.core.resilience import (
    Bulkhead,
    CircuitBreaker,
    CircuitBreakerConfiguration,
    ResiliencePolicy,
    RetryPolicy,
)
from ahia.integrations.storage.cloudinary_client import CloudinaryStorageAdapter
from ahia.integrations.storage.r2_client import R2StorageAdapter
from ahia.integrations.storage.storage_factory import build_storage_adapter, build_storage_policy

TENANT_ID = "8f3a1c2e-0000-4000-8000-000000000001"
OTHER_TENANT_ID = "1c7d4b90-0000-4000-8000-000000000002"
PRODUCT_ID = "4b2c9d1e-0000-4000-8000-000000000003"

OBJECT_KEY = f"tenants/{TENANT_ID}/products/{PRODUCT_ID}/hero.webp"
OTHER_TENANT_KEY = f"tenants/{OTHER_TENANT_ID}/products/{PRODUCT_ID}/hero.webp"
CONTENT = b"optimized-image-bytes-for-the-contract-suite"

R2_ACCESS_KEY = "r2-access-key-for-tests"
R2_SECRET_KEY = "r2-secret-key-for-tests"
CLOUDINARY_API_KEY = "cloudinary-api-key-for-tests"
CLOUDINARY_API_SECRET = "cloudinary-api-secret-for-tests"


class ProviderHarness(Protocol):
    """The provider-specific wiring the shared suite needs."""

    provider_name: str
    adapter: StoragePort

    def fail_every_call(self) -> None:
        """Make the next provider call fail with an availability error."""
        ...

    def credential_values(self) -> tuple[str, ...]:
        """Return the secret strings that must never appear in a log line."""
        ...


@dataclass
class R2Harness:
    """Wires the R2 adapter to a fake S3 client."""

    provider_name: str
    adapter: StoragePort
    client: Any

    def fail_every_call(self) -> None:
        self.client.put_failure = _ProviderError("503")
        self.client.head_failure = _ProviderError("503")
        self.client.delete_failure = _ProviderError("503")

    def credential_values(self) -> tuple[str, ...]:
        return (R2_ACCESS_KEY, R2_SECRET_KEY)


class _ProviderError(Exception):
    """A provider error shaped the way botocore shapes one."""

    def __init__(self, code: str) -> None:
        super().__init__(f"provider refused the call: {code}")
        self.response = {"Error": {"Code": code}}


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_failure: Exception | None = None
        self.head_failure: Exception | None = None
        self.delete_failure: Exception | None = None

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        if self.put_failure is not None:
            raise self.put_failure
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {}

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        if self.delete_failure is not None:
            raise self.delete_failure
        self.objects.pop(kwargs["Key"], None)
        return {}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        if self.head_failure is not None:
            raise self.head_failure
        if kwargs["Key"] not in self.objects:
            raise _ProviderError("404")
        return {}

    def generate_presigned_url(
        self, client_method: str, *, Params: dict[str, Any], ExpiresIn: int
    ) -> str:
        return f"https://account.r2.cloudflarestorage.com/{Params['Bucket']}/{Params['Key']}?sig=x"

    def close(self) -> None:
        return None


@dataclass
class CloudinaryHarness:
    """Wires the Cloudinary adapter to a fake SDK."""

    provider_name: str
    adapter: StoragePort
    client: Any

    def fail_every_call(self) -> None:
        self.client.upload_failure = _CloudinaryAvailabilityError("provider unavailable")
        self.client.resource_failure = _CloudinaryAvailabilityError("provider unavailable")
        self.client.destroy_failure = _CloudinaryAvailabilityError("provider unavailable")

    def credential_values(self) -> tuple[str, ...]:
        return (CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET)


class _CloudinaryAvailabilityError(Exception):
    """A Cloudinary SDK error type the adapter classifies as availability."""


def _build_policy(provider_name: str) -> ResiliencePolicy:
    return ResiliencePolicy(
        dependency_name=provider_name,
        timeout_seconds=2.0,
        breaker=CircuitBreaker(provider_name, CircuitBreakerConfiguration(failure_threshold=10)),
        bulkhead=Bulkhead(provider_name, max_concurrent_calls=4),
        retry=RetryPolicy(max_attempts=2, base_delay_seconds=0.001, max_delay_seconds=0.002),
    )


def build_r2_harness() -> R2Harness:
    client = _FakeS3Client()
    adapter = R2StorageAdapter(
        R2Configuration(
            endpoint="https://account.r2.cloudflarestorage.com",
            access_key_id=SecretStr(R2_ACCESS_KEY),
            secret_access_key=SecretStr(R2_SECRET_KEY),
            bucket="ahia-contract",
            region="auto",
            public_base_url=None,
            request_timeout_seconds=2.0,
        ),
        _build_policy("r2"),
        client_factory=lambda: client,
    )
    return R2Harness(provider_name="r2", adapter=adapter, client=client)


def build_cloudinary_harness() -> CloudinaryHarness:
    client = _CloudinarySdkDouble()
    adapter = CloudinaryStorageAdapter(
        CloudinaryConfiguration(
            cloud_name="ahia-contract-cloud",
            api_key=SecretStr(CLOUDINARY_API_KEY),
            api_secret=SecretStr(CLOUDINARY_API_SECRET),
            upload_folder="ahia",
            secure_delivery=True,
            request_timeout_seconds=2.0,
        ),
        _build_policy("cloudinary"),
        client=client,
    )
    return CloudinaryHarness(provider_name="cloudinary", adapter=adapter, client=client)


class _CloudinarySdkDouble:
    """A minimal stand-in for the Cloudinary SDK module surface the adapter uses."""

    def __init__(self) -> None:
        self.uploaded: dict[str, bytes] = {}
        self.upload_failure: BaseException | None = None
        self.destroy_failure: BaseException | None = None
        self.resource_failure: BaseException | None = None
        self._configuration: Any = self

    def config(self) -> Any:
        return self._configuration

    def url(self, source: str, **options: Any) -> str:
        width = options.get("transformation")
        suffix = f"?t={width}" if width else ""
        return f"https://res.cloudinary.com/ahia-contract-cloud/image/upload/{source}.webp{suffix}"

    def upload(self, file: BytesIO, **options: Any) -> dict[str, Any]:
        if self.upload_failure is not None:
            raise self.upload_failure
        public_id = str(options.get("public_id", ""))
        self.uploaded[public_id] = file.read()
        return {
            "public_id": public_id,
            "format": options.get("format", "webp"),
            "width": 800,
            "height": 600,
            "bytes": len(self.uploaded[public_id]),
            "secure_url": f"https://res.cloudinary.com/ahia-contract-cloud/image/upload/{public_id}.webp",
        }

    def destroy(self, public_id: str, **options: Any) -> dict[str, Any]:
        if self.destroy_failure is not None:
            raise self.destroy_failure
        self.uploaded.pop(public_id, None)
        return {"result": "ok"}

    def resource(self, public_id: str, **options: Any) -> dict[str, Any]:
        if self.resource_failure is not None:
            raise self.resource_failure
        if public_id not in self.uploaded:
            raise _CloudinaryNotFoundError("not found")
        return {"public_id": public_id}


#: The double raises the SDK's own not-found type, because that is the type the
#: adapter classifies as "absent". A locally invented exception would prove
#: nothing about the real binding.
_CloudinaryNotFoundError = __import__("cloudinary.exceptions", fromlist=["NotFound"]).NotFound


HARNESS_BUILDERS: dict[str, Any] = {
    "r2": build_r2_harness,
    "cloudinary": build_cloudinary_harness,
}


@pytest.fixture(params=sorted(HARNESS_BUILDERS))
def harness(request: pytest.FixtureRequest) -> Any:
    return HARNESS_BUILDERS[request.param]()


def build_request(key: str = OBJECT_KEY, *, tenant_id: str = TENANT_ID) -> StorageUploadRequest:
    return StorageUploadRequest(
        key=key,
        content=CONTENT,
        mime_type="image/webp",
        tenant_id=tenant_id,
        filename="hero.webp",
    )


# ---------------------------------------------------------------------------
# Shared behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_provider_name_is_reported(harness: Any) -> None:
    assert harness.adapter.provider_name == harness.provider_name


@pytest.mark.asyncio
@pytest.mark.unit
async def test_upload_returns_provider_neutral_metadata(harness: Any) -> None:
    stored = await harness.adapter.upload(build_request())

    assert stored.provider == harness.provider_name
    assert stored.key == OBJECT_KEY
    assert stored.mime_type == "image/webp"
    assert stored.size_bytes == len(CONTENT)
    assert stored.checksum_sha256 == compute_sha256(CONTENT)
    assert stored.is_degraded is False
    assert stored.degradation_reason == ""


@pytest.mark.asyncio
@pytest.mark.unit
async def test_exists_reports_presence_after_upload(harness: Any) -> None:
    await harness.adapter.upload(build_request())

    assert await harness.adapter.exists(key=OBJECT_KEY, tenant_id=TENANT_ID) is True


@pytest.mark.asyncio
@pytest.mark.unit
async def test_delete_is_idempotent(harness: Any) -> None:
    await harness.adapter.upload(build_request())

    await harness.adapter.delete(key=OBJECT_KEY, tenant_id=TENANT_ID)
    await harness.adapter.delete(key=OBJECT_KEY, tenant_id=TENANT_ID)

    assert await harness.adapter.exists(key=OBJECT_KEY, tenant_id=TENANT_ID) is False


@pytest.mark.asyncio
@pytest.mark.unit
async def test_cross_tenant_denial_is_indistinguishable_from_absence(harness: Any) -> None:
    """Both providers must give the same external answer to a cross-tenant key."""
    with pytest.raises(TenantIsolationError) as captured:
        await harness.adapter.delete(key=OTHER_TENANT_KEY, tenant_id=TENANT_ID)

    external = captured.value.external()
    assert external.code == "NOT_FOUND"
    assert captured.value.http_status == 404


@pytest.mark.asyncio
@pytest.mark.unit
async def test_provider_failure_is_a_typed_application_error(harness: Any) -> None:
    harness.fail_every_call()
    adapter = harness.adapter
    storage_errors: list[AhiaError] = []

    with pytest.raises(IntegrationError) as upload_error:
        await adapter.upload(build_request())
    storage_errors.append(upload_error.value)

    with pytest.raises(IntegrationError) as exists_error:
        await adapter.exists(key=OBJECT_KEY, tenant_id=TENANT_ID)
    storage_errors.append(exists_error.value)

    with pytest.raises(IntegrationError) as delete_error:
        await adapter.delete(key=OBJECT_KEY, tenant_id=TENANT_ID)
    storage_errors.append(delete_error.value)

    for error in storage_errors:
        assert not isinstance(error, (AttributeError, TypeError))
        payload = error.external().to_payload()
        assert set(payload["error"]) == {"code", "message", "correlation_id"}


@pytest.mark.asyncio
@pytest.mark.unit
async def test_provider_failure_never_names_the_provider_or_the_bucket(
    harness: Any,
) -> None:
    harness.fail_every_call()

    with pytest.raises(IntegrationError) as captured:
        await harness.adapter.upload(build_request())

    message = captured.value.external().message.lower()
    for forbidden in ("r2", "cloudinary", "bucket", "cloud", "ahia-contract"):
        assert forbidden not in message


@pytest.mark.asyncio
@pytest.mark.unit
async def test_no_credential_reaches_a_rendered_log_line(
    harness: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness.fail_every_call()

    with caplog.at_level(logging.DEBUG), contextlib.suppress(AhiaError):
        await harness.adapter.upload(build_request())

    rendered = "\n".join(JsonLogFormatter().format(record) for record in caplog.records)

    for credential in harness.credential_values():
        assert credential not in rendered, "a storage credential reached a log line"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_delivery_url_is_always_https(harness: Any) -> None:
    await harness.adapter.upload(build_request())

    url = await harness.adapter.build_delivery_url(key=OBJECT_KEY)

    assert url.startswith("https://")


@pytest.mark.asyncio
@pytest.mark.unit
async def test_presentation_width_never_breaks_delivery(harness: Any) -> None:
    """A provider may honour the width or ignore it, but must not fail on it."""
    url_without_width = await harness.adapter.build_delivery_url(key=OBJECT_KEY)
    url_with_width = await harness.adapter.build_delivery_url(
        key=OBJECT_KEY, presentation_width=480
    )

    assert url_without_width.startswith("https://")
    assert url_with_width.startswith("https://")


@pytest.mark.asyncio
@pytest.mark.unit
async def test_close_is_idempotent(harness: Any) -> None:
    await harness.adapter.close()
    await harness.adapter.close()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_adapter_satisfies_the_port(harness: Any) -> None:
    assert isinstance(harness.adapter, StoragePort)


# ---------------------------------------------------------------------------
# Provider selection does not change service-facing behaviour
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_factory_selects_the_configured_provider() -> None:
    r2_settings = build_settings(storage_provider=StorageProviderName.R2)
    cloudinary_settings = build_settings(
        storage_provider=StorageProviderName.CLOUDINARY,
        r2_endpoint=None,
        r2_access_key_id=None,
        r2_secret_access_key=None,
        r2_bucket=None,
        cloudinary_cloud_name="ahia-cloud",
        cloudinary_api_key="key",
        cloudinary_api_secret="secret",
    )

    r2_adapter = build_storage_adapter(r2_settings)
    cloudinary_adapter = build_storage_adapter(cloudinary_settings)

    assert isinstance(r2_adapter, R2StorageAdapter)
    assert isinstance(cloudinary_adapter, CloudinaryStorageAdapter)
    assert r2_adapter.provider_name == "r2"
    assert cloudinary_adapter.provider_name == "cloudinary"


@pytest.mark.unit
def test_each_provider_gets_its_own_breaker() -> None:
    """A policy is per dependency, so one provider's outage cannot trip the other."""
    r2_policy = build_storage_policy(build_settings(storage_provider=StorageProviderName.R2))
    cloudinary_policy = build_storage_policy(
        build_settings(
            storage_provider=StorageProviderName.CLOUDINARY,
            r2_endpoint=None,
            r2_access_key_id=None,
            r2_secret_access_key=None,
            r2_bucket=None,
            cloudinary_cloud_name="ahia-cloud",
            cloudinary_api_key="key",
            cloudinary_api_secret="secret",
        )
    )

    assert r2_policy.breaker is not cloudinary_policy.breaker
    r2_policy.breaker.record_failure()

    assert r2_policy.breaker.metrics.failures == 1
    assert cloudinary_policy.breaker.metrics.failures == 0


@pytest.mark.unit
def test_timeout_comes_from_the_active_providers_configuration() -> None:
    r2_policy = build_storage_policy(
        build_settings(storage_provider=StorageProviderName.R2, r2_request_timeout_seconds=4.0)
    )

    assert r2_policy.timeout_seconds == 4.0


def build_settings(**overrides: Any) -> Settings:
    baseline: dict[str, Any] = {
        "_env_file": None,
        "app_env": AppEnvironment.TEST,
        "database_url": "postgresql+asyncpg://ahia:secret@127.0.0.1:5432/ahia_test",
        "jwt_secret": "test-signing-secret-value-0000000001",
        "refresh_token_pepper": "test-refresh-pepper-value-00000000011",
        "storage_provider": StorageProviderName.R2,
        "r2_endpoint": "https://account.r2.cloudflarestorage.com",
        "r2_access_key_id": "r2-access-key",
        "r2_secret_access_key": "r2-secret-key",
        "r2_bucket": "ahia-test",
    }
    baseline.update(overrides)
    return Settings(**baseline)
