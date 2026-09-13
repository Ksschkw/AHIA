"""Cloudflare R2 storage adapter.

Cloudflare R2 speaks the S3 API, so the adapter is built on boto3 with a custom
endpoint. Everything R2-specific lives in this file: the endpoint, the bucket,
the credential shape, the signing, and the way a signed URL is produced. A
service never sees any of it.

Two decisions worth stating.

Sync SDK in an async service
    boto3 is synchronous. Every call therefore runs in a worker thread through
    ``asyncio.to_thread``, inside the resilience policy, so the event loop keeps
    serving other requests. The cost is that a timeout cannot cancel the worker
    thread: the caller receives a typed timeout and stops waiting, but the
    underlying request finishes or fails on its own. That is an accepted
    trade-off versus reimplementing SigV4 signing by hand, which is exactly the
    kind of cryptography a product must not roll itself.

Retries belong to the policy, not to botocore
    botocore's own retry layer is disabled. Two retry layers would multiply
    attempts (3 attempts times 5 retries), ignore the idempotency rule, and make
    the circuit breaker's failure count meaningless.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any, Final, Protocol

from ahia.core.config import R2Configuration
from ahia.core.errors import StorageOperationError, StorageUnavailableError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.ports.storage_port import (
    StorageUploadRequest,
    StoredObject,
    compute_sha256,
    key_belongs_to_tenant,
)
from ahia.core.resilience import ResiliencePolicy

_R2_LOGGER_NAME: Final[str] = "ahia.integrations.storage.r2"

#: Error codes that mean "the object is not there" rather than "the call failed".
_NOT_FOUND_ERROR_CODES: Final[frozenset[str]] = frozenset({"404", "NoSuchKey", "NotFound"})

#: Error codes that mean the dependency is unavailable rather than the request
#: being wrong.
_UNAVAILABLE_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        "500",
        "502",
        "503",
        "504",
        "RequestTimeout",
        "RequestTimeoutException",
        "SlowDown",
        "ServiceUnavailable",
        "InternalError",
        "EndpointConnectionError",
        "ConnectTimeoutError",
        "ReadTimeoutError",
    }
)


class ObjectStorageClient(Protocol):
    """The subset of the S3 client surface this adapter uses.

    Declared as a protocol so a test can inject a fake without importing boto3
    and without network access.
    """

    def put_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def delete_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def head_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    # The keyword names are boto3's, not ours: the S3 client takes `Params` and
    # `ExpiresIn` by keyword, so the protocol must match exactly.
    def generate_presigned_url(
        self,
        client_method: str,
        *,
        Params: Mapping[str, Any],
        ExpiresIn: int,
    ) -> str: ...


def _build_boto3_client(configuration: R2Configuration) -> ObjectStorageClient:
    """Construct the S3-compatible client for R2.

    Imported inside the function so the module can be imported in an environment
    where boto3 is absent, which keeps the port unit-testable in isolation.
    """
    import boto3  # noqa: PLC0415 - deferred so the port stays importable without the vendor SDK
    from botocore.config import Config  # noqa: PLC0415

    client_configuration = Config(
        signature_version="s3v4",
        connect_timeout=configuration.request_timeout_seconds,
        read_timeout=configuration.request_timeout_seconds,
        # The resilience policy owns retry. See the module docstring.
        retries={"max_attempts": 1, "mode": "standard"},
        s3={"addressing_style": "path"},
    )
    return boto3.client(  # type: ignore[no-any-return]
        "s3",
        endpoint_url=configuration.endpoint,
        aws_access_key_id=configuration.access_key_id.get_secret_value(),
        aws_secret_access_key=configuration.secret_access_key.get_secret_value(),
        region_name=configuration.region,
        config=client_configuration,
    )


class R2StorageAdapter:
    """Implements `StoragePort` against Cloudflare R2."""

    def __init__(
        self,
        configuration: R2Configuration,
        policy: ResiliencePolicy,
        *,
        signed_url_ttl_seconds: int = 900,
        client_factory: Callable[[], ObjectStorageClient] | None = None,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._configuration = configuration
        self._policy = policy
        self._signed_url_ttl_seconds = signed_url_ttl_seconds
        self._client_factory = client_factory or (lambda: _build_boto3_client(configuration))
        self._client: ObjectStorageClient | None = None
        self._logger = (logger or get_logger(_R2_LOGGER_NAME)).bind(
            provider=self.provider_name,
            bucket=configuration.bucket,
        )

    @property
    def provider_name(self) -> str:
        return "r2"

    def describe(self) -> dict[str, str]:
        """Return non-secret diagnostics for startup logging."""
        return self._configuration.describe()

    # ------------------------------------------------------------------
    # StoragePort
    # ------------------------------------------------------------------

    async def upload(self, request: StorageUploadRequest) -> StoredObject:
        """Store an object and return provider-neutral metadata.

        A provider failure raises a typed error. The adapter does not degrade on
        its own: deciding whether an image upload can be recorded as pending is a
        business decision, and it belongs to the service that owns the use case.
        """
        checksum = compute_sha256(request.content)

        async def push_object() -> Mapping[str, Any]:
            return await asyncio.to_thread(self._put_object, request)

        await self._policy.execute(
            push_object,
            operation="upload_object",
            # A PUT of the same key with the same bytes is idempotent, so retry
            # is safe here.
            is_idempotent=True,
        )

        return StoredObject(
            provider=self.provider_name,
            key=request.key,
            mime_type=request.mime_type,
            size_bytes=len(request.content),
            checksum_sha256=checksum,
            delivery_url=await self.build_delivery_url(key=request.key),
        )

    async def delete(self, *, key: str, tenant_id: str) -> None:
        """Delete an object. Deleting a missing object is not an error."""
        self._reject_cross_tenant_key(key, tenant_id, operation="delete_object")

        async def remove_object() -> None:
            await asyncio.to_thread(self._delete_object, key)

        await self._policy.execute(
            remove_object,
            operation="delete_object",
            # DELETE on a key is idempotent.
            is_idempotent=True,
        )

    async def exists(self, *, key: str, tenant_id: str) -> bool:
        """Return True when the object exists and belongs to the tenant.

        A provider failure raises rather than returning False. "False" is an
        answer, and answering "the object is not there" when the truth is "the
        provider did not respond" is how data gets overwritten or deleted.
        """
        self._reject_cross_tenant_key(key, tenant_id, operation="exists_object")

        async def head_object() -> bool:
            return await asyncio.to_thread(self._head_object, key)

        return await self._policy.execute(
            head_object,
            operation="exists_object",
            is_idempotent=True,
        )

    async def build_delivery_url(
        self,
        *,
        key: str,
        presentation_width: int | None = None,
        is_public: bool = False,
    ) -> str:
        """Return a delivery URL for the object.

        R2 has no server-side transformation, so `presentation_width` is accepted
        and ignored: the stored object is returned and the client sizes it. The
        parameter exists on the port so a service never branches on the provider.

        A private object gets a short-lived signed URL. A public object gets the
        configured public base URL, and if none is configured it still gets a
        signed URL rather than an unauthenticated guessable path.
        """
        if is_public and self._configuration.public_base_url:
            base = self._configuration.public_base_url.rstrip("/")
            return f"{base}/{key}"

        return await asyncio.to_thread(self._presign_get, key)

    async def close(self) -> None:
        """Release the underlying client."""
        client = self._client
        self._client = None
        if client is None:
            return
        close_method = getattr(client, "close", None)
        if callable(close_method):
            await asyncio.to_thread(close_method)

    # ------------------------------------------------------------------
    # Provider calls (synchronous, always invoked through to_thread)
    # ------------------------------------------------------------------

    @property
    def _s3_client(self) -> ObjectStorageClient:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def _put_object(self, request: StorageUploadRequest) -> Mapping[str, Any]:
        arguments: dict[str, Any] = {
            "Bucket": self._configuration.bucket,
            "Key": request.key,
            "Body": request.content,
            "ContentType": request.mime_type,
        }
        if request.metadata:
            arguments["Metadata"] = _sanitize_metadata(request.metadata)
        try:
            return self._s3_client.put_object(**arguments)
        except Exception as provider_error:
            raise self._translate(provider_error, operation="upload_object") from provider_error

    def _delete_object(self, key: str) -> None:
        try:
            self._s3_client.delete_object(Bucket=self._configuration.bucket, Key=key)
        except Exception as provider_error:
            raise self._translate(provider_error, operation="delete_object") from provider_error

    def _head_object(self, key: str) -> bool:
        try:
            self._s3_client.head_object(Bucket=self._configuration.bucket, Key=key)
        except Exception as provider_error:
            if _is_not_found(provider_error):
                return False
            raise self._translate(provider_error, operation="exists_object") from provider_error
        return True

    def _presign_get(self, key: str) -> str:
        try:
            return self._s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._configuration.bucket, "Key": key},
                ExpiresIn=self._signed_url_ttl_seconds,
            )
        except Exception as provider_error:
            raise self._translate(
                provider_error, operation="build_delivery_url"
            ) from provider_error

    # ------------------------------------------------------------------
    # Ownership and error translation
    # ------------------------------------------------------------------

    def _reject_cross_tenant_key(self, key: str, tenant_id: str, *, operation: str) -> None:
        """Refuse to act on a key outside the caller's tenant prefix.

        Checked before the provider is called, because a provider delete cannot
        be undone and a cross-tenant key is a defect in the caller rather than a
        client error.
        """
        if key_belongs_to_tenant(key, tenant_id):
            return
        self._logger.error(
            "storage_cross_tenant_key_rejected",
            operation=operation,
            tenant_id=tenant_id,
            key_prefix=key[:64],
        )
        raise StorageOperationError(
            operation=operation,
            entity="storage_object",
            detail="key is outside the caller's tenant prefix",
        )

    def _translate(self, provider_error: BaseException, *, operation: str) -> BaseException:
        """Translate a provider exception into the application hierarchy.

        The provider's message is discarded. An S3 error can echo the request,
        including a signed URL or a connection string.
        """
        error_code = _provider_error_code(provider_error)
        detail = f"provider=r2 bucket={self._configuration.bucket} code={error_code}"
        if error_code in _UNAVAILABLE_ERROR_CODES:
            return StorageUnavailableError(operation=operation, detail=detail, cause=provider_error)
        return StorageOperationError(operation=operation, detail=detail, cause=provider_error)


def _provider_error_code(provider_error: BaseException) -> str:
    """Extract a short, safe error code from a provider exception."""
    response = getattr(provider_error, "response", None)
    if isinstance(response, Mapping):
        error_block = response.get("Error")
        if isinstance(error_block, Mapping) and error_block.get("Code"):
            return str(error_block["Code"])
        metadata = response.get("ResponseMetadata")
        if isinstance(metadata, Mapping) and metadata.get("HTTPStatusCode"):
            return str(metadata["HTTPStatusCode"])
    return type(provider_error).__name__


def _is_not_found(provider_error: BaseException) -> bool:
    return _provider_error_code(provider_error) in _NOT_FOUND_ERROR_CODES


def _sanitize_metadata(metadata: Mapping[str, str]) -> dict[str, str]:
    """Return object metadata that is safe to send to the provider.

    S3 metadata is transported as HTTP headers, so a non-ASCII value or a
    newline would corrupt the request. Values are restricted to printable ASCII
    and keys are lowercased, which is what the S3 API expects.
    """
    sanitized: dict[str, str] = {}
    for key, value in metadata.items():
        safe_key = "".join(
            character for character in key.lower() if character.isalnum() or character in "-_"
        )
        safe_value = "".join(character for character in value if 32 <= ord(character) < 127)
        if safe_key:
            sanitized[safe_key[:64]] = safe_value[:256]
    return sanitized
