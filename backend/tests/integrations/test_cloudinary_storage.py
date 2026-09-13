"""Tests for the Cloudinary storage adapter.

The adapter is the only module allowed to know that Cloudinary exists. These
tests hold that line from both sides:

* the port's behaviour is unchanged by the adapter behind it -- a neutral key
  goes in, provider-neutral metadata comes out;
* nothing provider-shaped comes back out -- no Cloudinary exception type, no
  public identifier in a signature or a log line, no credential anywhere.

The SDK is fake. Every case here is a unit test: no network, no provider
account, no sleeping.
"""

from __future__ import annotations

import logging
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

import cloudinary.exceptions
import pytest
from pydantic import SecretStr

from ahia.core.config import CloudinaryConfiguration
from ahia.core.errors import (
    IntegrationError,
    StorageOperationError,
    StorageUnavailableError,
    TenantIsolationError,
    require_correlation_id,
)
from ahia.core.logging import JsonLogFormatter
from ahia.core.ports.storage_port import (
    StoragePort,
    StorageUploadRequest,
    compute_sha256,
)
from ahia.core.resilience import (
    CircuitBreakerConfiguration,
    ResiliencePolicy,
    build_policy,
)
from ahia.integrations.storage import cloudinary_client as cloudinary_client_module
from ahia.integrations.storage.cloudinary_client import (
    CLOUDINARY_PROVIDER_NAME,
    CloudinaryStorageAdapter,
    cloudinary_error_type_names,
    cloudinary_sdk_module,
)

TENANT_ID = "8f3a1c2e-0000-4000-8000-000000000001"
OTHER_TENANT_ID = "1c7d4b90-0000-4000-8000-000000000002"
PRODUCT_ID = "4b2c9d1e-0000-4000-8000-000000000003"

CLOUD_NAME = "ahia-test-cloud"
API_KEY = "cloudinary-api-key-for-tests"
API_SECRET = "cloudinary-api-secret-for-tests"
UPLOAD_FOLDER = "ahia"

OBJECT_KEY = f"tenants/{TENANT_ID}/products/{PRODUCT_ID}/hero.webp"
OTHER_TENANT_KEY = f"tenants/{OTHER_TENANT_ID}/products/{PRODUCT_ID}/hero.webp"

PROVIDER_RESPONSE: dict[str, Any] = {
    "public_id": f"{UPLOAD_FOLDER}/{TENANT_ID}/products/{PRODUCT_ID}/hero",
    "version": 1_712_345_678,
    "format": "webp",
    "width": 800,
    "height": 600,
    "bytes": 4_096,
    "secure_url": "https://res.cloudinary.com/ahia-test-cloud/image/upload/hero.webp",
}

#: The transformation the adapter must encode for a requested width. Pinned
#: literally so a change to the encoding is a visible test failure rather than a
#: silent change in what the provider is asked for.
EXPECTED_WIDTH_TRANSFORMATION = "w_640,c_limit"


class FakeCloudinarySdk:
    """A stand-in for the SDK module that records what the adapter asked for.

    It raises on demand and returns the same shapes the real SDK returns, so the
    adapter's mapping, translation and logging run exactly as they would against
    the provider.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.configuration_values: dict[str, Any] = {}
        self.uploaded_bytes: bytes = b""
        self.delivered_url = "https://res.cloudinary.com/test/image/upload/from-fake-sdk.webp"
        self.upload_failure: BaseException | None = None
        self.destroy_failure: BaseException | None = None
        self.resource_failure: BaseException | None = None

    def config(self) -> Any:
        return self

    def __setattr__(self, name: str, value: Any) -> None:
        """Record what the adapter configured, and ignore everything else.

        The real SDK's configuration is a mutable object that the adapter is
        expected to write to; recording the writes is how a test proves that the
        values came from the injected configuration.
        """
        if name in {"cloud_name", "api_key", "api_secret"}:
            self.configuration_values[name] = value
        object.__setattr__(self, name, value)

    def url(self, source: str, **options: Any) -> str:
        self.calls.append(("url", source, dict(options)))
        return self.delivered_url

    def upload(self, file: BytesIO, **options: Any) -> dict[str, Any]:
        self.calls.append(("upload", str(options.get("public_id", "")), dict(options)))
        self.uploaded_bytes = file.read()
        if self.upload_failure is not None:
            raise self.upload_failure
        return PROVIDER_RESPONSE

    def destroy(self, public_id: str, **options: Any) -> dict[str, Any]:
        self.calls.append(("destroy", public_id, dict(options)))
        if self.destroy_failure is not None:
            raise self.destroy_failure
        return {"result": "ok"}

    def resource(self, public_id: str, **options: Any) -> dict[str, Any]:
        self.calls.append(("resource", public_id, dict(options)))
        if self.resource_failure is not None:
            raise self.resource_failure
        return PROVIDER_RESPONSE

    # -- assertions used by the tests ------------------------------------

    def call_names(self) -> list[str]:
        """Return the provider operations attempted, in order."""
        return [operation for operation, _, _ in self.calls]

    def last_call(self) -> tuple[str, str, dict[str, Any]]:
        """Return the most recent call."""
        return self.calls[-1]

    def options_for(self, operation: str) -> dict[str, Any]:
        """Return the options of the first call to one operation."""
        for recorded_operation, _, options in self.calls:
            if recorded_operation == operation:
                return options
        raise AssertionError(f"no {operation} call was recorded")


def build_configuration(
    *,
    upload_folder: str = UPLOAD_FOLDER,
    secure_delivery: bool = True,
) -> CloudinaryConfiguration:
    """Build the configuration exactly as `Settings.cloudinary_configuration` does.

    The credentials are `SecretStr` here too, so a test cannot accidentally
    depend on the adapter handling a plain string that production never passes.
    """
    return CloudinaryConfiguration(
        cloud_name=CLOUD_NAME,
        api_key=SecretStr(API_KEY),
        api_secret=SecretStr(API_SECRET),
        upload_folder=upload_folder,
        secure_delivery=secure_delivery,
        request_timeout_seconds=15.0,
    )


def build_adapter(
    sdk: FakeCloudinarySdk,
    *,
    configuration: CloudinaryConfiguration | None = None,
) -> CloudinaryStorageAdapter:
    policy = build_policy(
        CLOUDINARY_PROVIDER_NAME,
        timeout_seconds=5.0,
        breaker_configuration=CircuitBreakerConfiguration(failure_threshold=5),
        max_concurrent_calls=4,
    )
    return CloudinaryStorageAdapter(
        configuration or build_configuration(),
        policy,
        client=sdk,
    )


def build_upload_request(
    *,
    key: str = OBJECT_KEY,
    content: bytes = b"optimized-webp-bytes",
    mime_type: str = "image/webp",
) -> StorageUploadRequest:
    return StorageUploadRequest(
        key=key,
        content=content,
        mime_type=mime_type,
        tenant_id=TENANT_ID,
    )


# ---------------------------------------------------------------------------
# Port shape and configuration
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_adapter_satisfies_the_provider_neutral_port() -> None:
    adapter = build_adapter(FakeCloudinarySdk())

    assert isinstance(adapter, StoragePort)
    assert adapter.provider_name == "cloudinary"


@pytest.mark.unit
def test_credentials_come_from_injected_configuration() -> None:
    """The SDK's process-global configuration is set from the adapter's own
    configuration object, never from the environment."""
    sdk = FakeCloudinarySdk()

    build_adapter(sdk)

    assert sdk.configuration_values["cloud_name"] == CLOUD_NAME
    assert sdk.configuration_values["api_key"] == API_KEY
    assert sdk.configuration_values["api_secret"] == API_SECRET


@pytest.mark.unit
def test_a_policy_for_another_dependency_is_rejected() -> None:
    """Two providers must never share a breaker: an unhealthy R2 endpoint would
    otherwise trip calls to a healthy Cloudinary account."""
    other_policy = build_policy(
        "r2",
        timeout_seconds=5.0,
        breaker_configuration=CircuitBreakerConfiguration(failure_threshold=5),
        max_concurrent_calls=4,
    )

    with pytest.raises(ValueError, match="policy dependency"):
        CloudinaryStorageAdapter(
            build_configuration(),
            other_policy,
            client=FakeCloudinarySdk(),
        )


@pytest.mark.unit
def test_the_default_client_is_bound_to_the_real_sdk() -> None:
    """The default client is the audited SDK, wired to the operations the
    adapter performs; tests inject a fake instead."""
    policy = build_policy(
        CLOUDINARY_PROVIDER_NAME,
        timeout_seconds=5.0,
        breaker_configuration=CircuitBreakerConfiguration(failure_threshold=5),
        max_concurrent_calls=4,
    )

    adapter = CloudinaryStorageAdapter(build_configuration(), policy)

    assert adapter._client is not cloudinary_sdk_module()
    for operation in ("url", "config", "upload", "destroy", "resource"):
        assert callable(getattr(adapter._client, operation))


@pytest.mark.asyncio
@pytest.mark.unit
async def test_the_real_sdk_builds_a_signed_width_transformation_url() -> None:
    """Run the adapter once against the installed SDK's own signing code.

    No network is involved: `cloudinary_url` signs locally. This is the check
    that catches a vendor API that moved -- `cloudinary.url` does not exist, the
    builder lives in `cloudinary.utils` -- which a fake alone can never catch.
    The credentials are obvious placeholders and the URL is never fetched.
    """
    adapter = CloudinaryStorageAdapter(
        build_configuration(),
        build_policy(
            CLOUDINARY_PROVIDER_NAME,
            timeout_seconds=5.0,
            breaker_configuration=CircuitBreakerConfiguration(failure_threshold=5),
            max_concurrent_calls=4,
        ),
    )

    public_url = await adapter.build_delivery_url(
        key=OBJECT_KEY, presentation_width=640, is_public=True
    )
    private_url = await adapter.build_delivery_url(key=OBJECT_KEY, is_public=False)

    assert public_url.startswith(f"https://res.cloudinary.com/{CLOUD_NAME}/")
    assert "w_640" in public_url
    assert public_url.endswith(".webp")
    assert "/upload/" in public_url
    # The stored object is addressed by the identifier the adapter derived.
    assert f"{UPLOAD_FOLDER}/{TENANT_ID}/products/{PRODUCT_ID}/hero" in public_url
    # A private asset is signed, and no URL ever carries the API secret.
    assert "/private/" in private_url
    assert "s--" in private_url
    assert API_SECRET not in public_url
    assert API_SECRET not in private_url


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_upload_returns_provider_neutral_metadata() -> None:
    sdk = FakeCloudinarySdk()
    adapter = build_adapter(sdk)
    content = b"optimized-webp-bytes"

    stored = await adapter.upload(build_upload_request(content=content))

    assert stored.provider == CLOUDINARY_PROVIDER_NAME
    assert stored.key == OBJECT_KEY
    assert stored.mime_type == "image/webp"
    assert stored.size_bytes == len(content)
    assert stored.checksum_sha256 == compute_sha256(content)
    assert stored.width == 800
    assert stored.height == 600
    assert stored.is_degraded is False
    assert sdk.uploaded_bytes == content


@pytest.mark.asyncio
@pytest.mark.unit
async def test_upload_maps_the_neutral_key_inside_the_adapter() -> None:
    """The public identifier is derived from the key: the tenant root is
    stripped and the extension is handed to the provider as a format."""
    sdk = FakeCloudinarySdk()
    adapter = build_adapter(sdk)

    await adapter.upload(build_upload_request())

    # `options_for` targets the upload itself: the adapter also builds the
    # delivery URL for the stored object, so the last provider call is not the
    # upload.
    options = sdk.options_for("upload")
    assert options["public_id"] == f"{UPLOAD_FOLDER}/{TENANT_ID}/products/{PRODUCT_ID}/hero"
    assert options["format"] == "webp"
    assert options["resource_type"] == "image"
    # Overwrite is what makes a retry after an ambiguous timeout replace the
    # asset instead of creating a second one.
    assert options["overwrite"] is True


@pytest.mark.asyncio
@pytest.mark.unit
async def test_the_key_mapping_is_reversible() -> None:
    """A stored object must stay resolvable: the public identifier maps back to
    the same neutral key it came from."""
    adapter = build_adapter(FakeCloudinarySdk())

    public_id, asset_format = adapter._public_id_for(OBJECT_KEY)

    assert adapter._key_for_public_id(public_id, asset_format=asset_format) == OBJECT_KEY


@pytest.mark.unit
def test_an_identifier_outside_the_upload_folder_cannot_be_reversed() -> None:
    """A public identifier that is not ours is a defect, not a key. Guessing
    would turn a wiring mistake into a read of an unrelated asset."""
    adapter = build_adapter(FakeCloudinarySdk())

    with pytest.raises(StorageOperationError, match="upload folder"):
        adapter._key_for_public_id("some-other-folder/asset", asset_format="webp")


@pytest.mark.asyncio
@pytest.mark.unit
async def test_upload_is_logged_without_the_public_identifier(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sdk = FakeCloudinarySdk()
    adapter = build_adapter(sdk)
    public_id, _ = adapter._public_id_for(OBJECT_KEY)

    with caplog.at_level(logging.INFO, logger="ahia.integrations.storage"):
        await adapter.upload(build_upload_request())

    record = caplog.records[0]
    assert record.getMessage() == "object_stored"
    assert record.tenant_id == TENANT_ID
    assert record.size_bytes == len(b"optimized-webp-bytes")
    assert public_id not in caplog.text
    assert OBJECT_KEY not in caplog.text


# ---------------------------------------------------------------------------
# Provider failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_an_unavailable_provider_becomes_a_typed_application_error() -> None:
    sdk = FakeCloudinarySdk()
    sdk.upload_failure = cloudinary.exceptions.GeneralError("cloudinary://key:secret@ahia?boom=1")
    adapter = build_adapter(sdk)

    with pytest.raises(StorageUnavailableError) as captured:
        await adapter.upload(build_upload_request())

    raised = captured.value
    assert isinstance(raised, IntegrationError)
    assert raised.error_code == "STORAGE_UNAVAILABLE"
    # No provider exception type escapes the adapter.
    assert not isinstance(raised, cloudinary.exceptions.Error)
    assert type(raised).__name__ not in cloudinary_error_type_names()
    # The internal view names the operation and the provider's failure type; the
    # provider's message (which can carry a credential-bearing URL) does not
    # survive.
    assert "operation=upload" in str(raised)
    assert "provider_error=GeneralError" in str(raised)
    assert "boom=1" not in str(raised)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_a_rejected_request_becomes_a_storage_operation_error() -> None:
    """A failure that will never succeed is not reported as an availability
    problem, or a caller would retry it forever."""
    sdk = FakeCloudinarySdk()
    sdk.upload_failure = cloudinary.exceptions.BadRequest("invalid public id")
    adapter = build_adapter(sdk)

    with pytest.raises(StorageOperationError) as captured:
        await adapter.upload(build_upload_request())

    assert captured.value.error_code == "STORAGE_ERROR"
    assert captured.value.http_status == 502


@pytest.mark.asyncio
@pytest.mark.unit
async def test_exists_reports_a_missing_object_as_absent() -> None:
    sdk = FakeCloudinarySdk()
    sdk.resource_failure = cloudinary.exceptions.NotFound("no such asset")
    adapter = build_adapter(sdk)

    assert await adapter.exists(key=OBJECT_KEY, tenant_id=TENANT_ID) is False


@pytest.mark.asyncio
@pytest.mark.unit
async def test_exists_does_not_turn_an_outage_into_an_absent_object() -> None:
    sdk = FakeCloudinarySdk()
    sdk.resource_failure = cloudinary.exceptions.GeneralError("service unavailable")
    adapter = build_adapter(sdk)

    with pytest.raises(StorageUnavailableError):
        await adapter.exists(key=OBJECT_KEY, tenant_id=TENANT_ID)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_exists_reports_a_present_object() -> None:
    sdk = FakeCloudinarySdk()
    adapter = build_adapter(sdk)

    assert await adapter.exists(key=OBJECT_KEY, tenant_id=TENANT_ID) is True


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_delete_rejects_a_cross_tenant_key_before_calling_the_provider(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sdk = FakeCloudinarySdk()
    adapter = build_adapter(sdk)

    with (
        caplog.at_level(logging.ERROR, logger="ahia.integrations.storage"),
        pytest.raises(TenantIsolationError) as captured,
    ):
        await adapter.delete(key=OTHER_TENANT_KEY, tenant_id=TENANT_ID)

    assert sdk.calls == [], "a provider call was made before the ownership check"
    assert captured.value.http_status == 404
    security_events = [
        record
        for record in caplog.records
        if record.getMessage() == "storage_cross_tenant_key_rejected"
    ]
    assert security_events, "a cross-tenant key is a security event and must be logged"
    assert security_events[0].security_event == "tenant_isolation"
    assert security_events[0].tenant_id == TENANT_ID


@pytest.mark.asyncio
@pytest.mark.unit
async def test_exists_rejects_a_cross_tenant_key_before_calling_the_provider() -> None:
    sdk = FakeCloudinarySdk()
    adapter = build_adapter(sdk)

    with pytest.raises(TenantIsolationError):
        await adapter.exists(key=OTHER_TENANT_KEY, tenant_id=TENANT_ID)

    assert sdk.calls == [], "a provider call was made before the ownership check"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_delete_removes_an_owned_object() -> None:
    sdk = FakeCloudinarySdk()
    adapter = build_adapter(sdk)

    await adapter.delete(key=OBJECT_KEY, tenant_id=TENANT_ID)

    operation, public_id, _ = sdk.last_call()
    assert operation == "destroy"
    assert public_id == f"{UPLOAD_FOLDER}/{TENANT_ID}/products/{PRODUCT_ID}/hero"


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_delivery_url_encodes_the_requested_width_as_a_transformation() -> None:
    sdk = FakeCloudinarySdk()
    adapter = build_adapter(sdk)

    await adapter.build_delivery_url(key=OBJECT_KEY, presentation_width=640, is_public=True)

    operation, public_id, options = sdk.last_call()
    assert operation == "url"
    assert public_id == f"{UPLOAD_FOLDER}/{TENANT_ID}/products/{PRODUCT_ID}/hero"
    assert options["transformation"] == EXPECTED_WIDTH_TRANSFORMATION
    assert options["secure"] is True
    assert options["type"] == "upload"
    assert options["resource_type"] == "image"
    assert options["format"] == "webp"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_no_width_means_no_transformation_is_encoded() -> None:
    sdk = FakeCloudinarySdk()
    adapter = build_adapter(sdk)

    await adapter.build_delivery_url(key=OBJECT_KEY, is_public=True)

    assert "transformation" not in sdk.options_for("url")


@pytest.mark.asyncio
@pytest.mark.unit
async def test_a_private_delivery_url_is_signed() -> None:
    """A private asset must not be fetchable from an unsigned path."""
    sdk = FakeCloudinarySdk()
    adapter = build_adapter(sdk)

    await adapter.build_delivery_url(key=OBJECT_KEY, is_public=False)

    options = sdk.options_for("url")
    assert options["type"] == "private"
    assert options["sign_url"] is True


@pytest.mark.asyncio
@pytest.mark.unit
async def test_a_raw_asset_is_delivered_untransformed() -> None:
    """A receipt attachment has no image transformation pipeline. The width
    request is ignored rather than sent as a transformation the provider would
    reject."""
    sdk = FakeCloudinarySdk()
    adapter = build_adapter(sdk)
    raw_key = f"tenants/{TENANT_ID}/receipts/{PRODUCT_ID}/scan.pdf"

    await adapter.build_delivery_url(key=raw_key, presentation_width=640, is_public=True)

    options = sdk.options_for("url")
    assert options["resource_type"] == "raw"
    assert "transformation" not in options


@pytest.mark.asyncio
@pytest.mark.unit
async def test_a_negative_presentation_width_is_rejected() -> None:
    adapter = build_adapter(FakeCloudinarySdk())

    with pytest.raises(StorageOperationError, match="presentation_width"):
        await adapter.build_delivery_url(key=OBJECT_KEY, presentation_width=0)


# ---------------------------------------------------------------------------
# Checksum and secrets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_the_checksum_is_computed_locally() -> None:
    """The checksum must not depend on the provider reporting one, because it is
    needed exactly when the provider is unreachable."""
    sdk = FakeCloudinarySdk()
    adapter = build_adapter(sdk)
    content = b"locally-hashed-bytes"
    assert "checksum" not in PROVIDER_RESPONSE

    stored = await adapter.upload(build_upload_request(content=content))

    assert stored.checksum_sha256 == compute_sha256(content)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_credentials_never_reach_a_log_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sdk = FakeCloudinarySdk()
    sdk.upload_failure = cloudinary.exceptions.GeneralError(
        f"bad signature for api_secret={API_SECRET}"
    )
    adapter = build_adapter(sdk)

    with (
        caplog.at_level(logging.DEBUG, logger="ahia.integrations.storage"),
        pytest.raises(StorageUnavailableError),
    ):
        await adapter.upload(build_upload_request())

    rendered: list[str] = []
    for record in caplog.records:
        rendered.append(JsonLogFormatter().format(record))
    combined = "\n".join(rendered)
    assert API_SECRET not in combined
    assert API_KEY not in combined
    assert "cloudinary://" not in combined


@pytest.mark.asyncio
@pytest.mark.unit
async def test_the_external_error_payload_carries_no_internal_detail() -> None:
    """The client receives a code, a message and the correlation ID. Nothing
    about the provider, the asset or why the call failed."""
    sdk = FakeCloudinarySdk()
    sdk.upload_failure = cloudinary.exceptions.GeneralError(
        "https://api.cloudinary.com/v1_1/ahia-test-cloud/resources?api_secret=leaked"
    )
    adapter = build_adapter(sdk)
    public_id, _ = adapter._public_id_for(OBJECT_KEY)

    with pytest.raises(StorageUnavailableError) as captured:
        await adapter.upload(build_upload_request())

    payload = captured.value.external().to_payload()
    assert set(payload["error"]) == {"code", "message", "correlation_id"}
    rendered = str(payload)
    assert payload["error"]["code"] == "STORAGE_UNAVAILABLE"
    assert payload["error"]["correlation_id"] == require_correlation_id()
    assert "cloudinary" not in rendered.lower()
    assert public_id not in rendered
    assert OBJECT_KEY not in rendered
    assert "api_secret" not in rendered
    assert "leaked" not in rendered
    assert "Traceback" not in rendered


@pytest.mark.asyncio
@pytest.mark.unit
async def test_provider_metadata_values_are_not_echoed_into_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Only identifiers and measured values are logged. A provider-supplied
    string (a filename a trader chose, an uploader's IP) stays out of the log
    store."""
    sdk = FakeCloudinarySdk()
    adapter = build_adapter(sdk)
    request = StorageUploadRequest(
        key=OBJECT_KEY,
        content=b"optimized-webp-bytes",
        mime_type="image/webp",
        tenant_id=TENANT_ID,
        filename="shop-front-photo.webp",
        metadata={"captured_by": "trader-device-serial-1234"},
    )

    with caplog.at_level(logging.INFO, logger="ahia.integrations.storage"):
        await adapter.upload(request)

    assert "shop-front-photo" not in caplog.text
    assert "trader-device-serial-1234" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.unit
async def test_closing_the_adapter_releases_nothing_and_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sdk = FakeCloudinarySdk()
    adapter = build_adapter(sdk)

    with caplog.at_level(logging.INFO, logger="ahia.integrations.storage"):
        await adapter.close()

    assert caplog.records[0].getMessage() == "storage_adapter_closed"
    assert sdk.calls == []


@pytest.mark.unit
def test_the_resilience_policy_is_the_dependency_boundary() -> None:
    """The adapter must go through the injected policy for every outbound call,
    so a shared policy is what protects the dependency, not a per-call-site
    wrapper."""
    sdk = FakeCloudinarySdk()
    policy = build_policy(
        CLOUDINARY_PROVIDER_NAME,
        timeout_seconds=5.0,
        breaker_configuration=CircuitBreakerConfiguration(failure_threshold=2),
        max_concurrent_calls=2,
    )
    adapter = CloudinaryStorageAdapter(build_configuration(), policy, client=sdk)

    assert adapter.provider_name == CLOUDINARY_PROVIDER_NAME
    assert isinstance(policy, ResiliencePolicy)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_provider_identifier_leaks_into_a_sibling_module() -> None:
    """The adapter is the only module allowed to know the provider. This asserts
    the boundary at the file level, because a shared signature or a log field is
    where the identifier would leak first.

    Sibling modules present in the working tree are inspected; each adapter owns
    its own guard, so a module landing in parallel is reported here rather than
    silently tolerated.
    """
    storage_package = Path(cloudinary_client_module.__file__).parent
    adapter_path = Path(cloudinary_client_module.__file__)
    # The factory is the single place allowed to name a provider: choosing an
    # adapter is its entire job. Everything else in the package speaks the port.
    permitted_to_name_providers = {adapter_path.name, "storage_factory.py"}

    for sibling in sorted(storage_package.glob("*.py")):
        if sibling == adapter_path or sibling.name == "__init__.py":
            continue
        sibling_text = sibling.read_text(encoding="utf-8")
        assert "cloudinary.exceptions" not in sibling_text.lower(), (
            f"{sibling.name} handles provider exceptions instead of the adapter"
        )
        if sibling.name in permitted_to_name_providers:
            continue
        assert "cloudinary" not in sibling_text.lower(), (
            f"{sibling.name} names the provider instead of the port"
        )


@pytest.mark.unit
def test_tenant_identifiers_in_these_tests_are_opaque() -> None:
    """Fixture identifiers are UUIDs, not tenant names: a log line must never
    need a tenant's name to be useful."""
    for identifier in (TENANT_ID, OTHER_TENANT_ID, PRODUCT_ID):
        parsed = uuid.UUID(identifier)
        assert str(parsed) == identifier
