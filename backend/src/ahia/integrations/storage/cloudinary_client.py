"""Cloudinary adapter for the provider-neutral storage port.

Why this file exists next to an S3-compatible adapter:

* Cloudflare R2 is the default because public storefront images are read far
  more often than they are written, and egress dominates the bill (ADR-0002).
  Cloudinary is selectable because its strengths are server-side
  transformations and delivery, so a tenant that needs sized renditions can be
  served one without AHIA storing a ladder of variants (ADR-0009).
* Neither provider may reach the domain. Everything Cloudinary-shaped lives
  here: the public identifier, the transformation encoding, the delivery URL
  signature, the SDK exception types. A service receives a storage key, a width
  and a boolean, and never learns which provider answered.

Two identifiers, one direction of truth. The caller supplies a neutral key of
the form ``tenants/{tenant_id}/{category}/{resource_id}/{filename}``. Cloudinary
addresses an asset by ``public_id``, a flat path with no file extension. The
mapping between the two is computed here, deterministically and reversibly, by
:meth:`CloudinaryStorageAdapter._public_id_for` and
:meth:`CloudinaryStorageAdapter._key_for_public_id`:

    tenants/{tenant}/products/{product}/hero.webp
        -> {upload_folder}/{tenant}/products/{product}/hero

The mapping deliberately does not rely on the SDK's ``folder`` or
``public_id_prefix`` options, because sign-time and delivery-time must agree on
an identifier that this adapter can derive on its own.

Two behaviours are worth calling out because they are not obvious:

1. The SDK is synchronous. Every call runs through ``asyncio.to_thread`` inside
   the injected resilience policy. A timeout on the policy abandons the await,
   but it cannot cancel the worker thread, so the underlying HTTP request
   finishes on its own and its result is discarded. The SDK's own request
   timeout is the real bound on how long the provider is held open.
2. Cloudinary has no cheap "head" for an asset. Existence is answered by the
   admin API, which reports a missing asset as a provider exception rather than
   as a false result. That translation happens here, together with every other
   provider exception, so no Cloudinary exception type ever escapes this file.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from hashlib import sha256
from io import BytesIO
from typing import Any, Final, Protocol, TypedDict, TypeVar, cast

import cloudinary
import cloudinary.exceptions
from cloudinary import api as cloudinary_api
from cloudinary import uploader as cloudinary_uploader
from cloudinary import utils as cloudinary_utils

from ahia.core.config import CloudinaryConfiguration
from ahia.core.errors import (
    ErrorLayer,
    StorageOperationError,
    StorageUnavailableError,
    TenantIsolationError,
)
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.ports.storage_port import (
    StoragePort,
    StorageUploadRequest,
    StoredObject,
    compute_sha256,
    key_belongs_to_tenant,
)
from ahia.core.resilience import ResiliencePolicy

T = TypeVar("T")

CLOUDINARY_PROVIDER_NAME: Final[str] = "cloudinary"

_STORAGE_LOGGER_NAME: Final[str] = "ahia.integrations.storage"

#: The top-level folder the neutral key hierarchy starts at. The adapter strips
#: it because Cloudinary's public identifier namespace is already account-wide
#: and has no notion of a tenant root.
_TENANT_ROOT_SEGMENT: Final[str] = "tenants"

#: Cloudinary's own delivery-type values. "upload" is public and cacheable;
#: "private" requires a signed URL to fetch.
_PUBLIC_DELIVERY_TYPE: Final[str] = "upload"
_PRIVATE_DELIVERY_TYPE: Final[str] = "private"

_IMAGE_RESOURCE_TYPE: Final[str] = "image"
_RAW_RESOURCE_TYPE: Final[str] = "raw"

#: The format Cloudinary is told to use when a key carries no extension. The
#: value is opaque to the provider and exists so the mapping stays total.
_MISSING_EXTENSION_FORMAT: Final[str] = "none"

#: File extensions treated as images. The adapter receives a key rather than a
#: content type, so the extension decides whether a transformation is applicable
#: and whether the asset is an image or a raw resource.
_IMAGE_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {"jpg", "jpeg", "png", "webp", "avif", "gif", "bmp", "tiff", "heic"}
)

#: Provider failures that say "ask again", as opposed to "this request will
#: never succeed". Only this group is retryable, and only when the policy is
#: handed an idempotent call.
_RETRYABLE_CLOUDINARY_ERRORS: Final[tuple[type[BaseException], ...]] = (
    cloudinary.exceptions.RateLimited,
    cloudinary.exceptions.NotAllowed,
    cloudinary.exceptions.GeneralError,
)

#: Every exception the SDK is known to raise. Kept as one tuple so a new SDK
#: exception cannot slip through the translation boundary unnoticed.
_CLOUDINARY_ERROR_TYPES: Final[tuple[type[BaseException], ...]] = (
    cloudinary.exceptions.NotFound,
    cloudinary.exceptions.NotAllowed,
    cloudinary.exceptions.AlreadyExists,
    cloudinary.exceptions.RateLimited,
    cloudinary.exceptions.BadRequest,
    cloudinary.exceptions.GeneralError,
    cloudinary.exceptions.AuthorizationRequired,
    cloudinary.exceptions.Error,
)

#: How much of a key digest is recorded when a security event must name the key
#: that was rejected. Long enough to correlate two log lines, short enough that
#: the key itself is not reconstructable.
_KEY_FINGERPRINT_LENGTH: Final[int] = 12


class _UploadParameters(TypedDict):
    """The upload options this adapter passes to the SDK, explicitly typed."""

    public_id: str
    format: str
    resource_type: str
    overwrite: bool
    invalidate: bool


class CloudinaryClient(Protocol):
    """The slice of the Cloudinary SDK this adapter uses.

    The SDK spreads one provider across several places: signing and delivery
    URLs live in ``cloudinary.utils``, uploads in ``cloudinary.uploader``, asset
    lookup in ``cloudinary.api`` and the process-global credentials in the
    package itself. This protocol therefore describes the *operations* the
    adapter needs rather than the shape of the package, so a test can inject a
    fake and the adapter cannot quietly grow a dependency on another part of the
    SDK.

    The signatures are deliberately loose: the vendor SDK is untyped, and a
    narrow signature here would be a claim about the provider that nothing
    checks. Where the adapter uses a return value, it validates the value.
    """

    def url(self, source: str, **options: Any) -> str:
        """Build a delivery URL. Returns a (url, options) tuple in the SDK."""
        ...

    def config(self) -> Any:
        """Return the SDK's process-global configuration object."""
        ...

    def upload(self, file: BytesIO, **options: Any) -> Mapping[str, Any]:
        """Upload an asset and return the provider's response."""
        ...

    def destroy(self, public_id: str, **options: Any) -> Mapping[str, Any]:
        """Delete an asset and return the provider's response."""
        ...

    def resource(self, public_id: str, **options: Any) -> Mapping[str, Any]:
        """Return an asset's details. Raises when the asset does not exist."""
        ...


class _CloudinarySdkBinding:
    """The real SDK's functions, bound by name for the adapter's protocol.

    Each method is a one-line delegation. The binding exists so the adapter
    depends on the operations it performs rather than on the SDK's module
    layout, which is a vendor implementation detail that has already moved once
    (the delivery URL builder lives in ``cloudinary.utils``, not at the package
    root).
    """

    @staticmethod
    def url(source: str, **options: Any) -> str:
        built_url, _ = cloudinary_utils.cloudinary_url(source, **options)
        return str(built_url)

    @staticmethod
    def config() -> Any:
        return cloudinary.config()

    @staticmethod
    def upload(file: BytesIO, **options: Any) -> Mapping[str, Any]:
        return cast(Mapping[str, Any], cloudinary_uploader.upload(file, **options))

    @staticmethod
    def destroy(public_id: str, **options: Any) -> Mapping[str, Any]:
        return cast(Mapping[str, Any], cloudinary_uploader.destroy(public_id, **options))

    @staticmethod
    def resource(public_id: str, **options: Any) -> Mapping[str, Any]:
        return cast(Mapping[str, Any], cloudinary_api.resource(public_id, **options))


def cloudinary_sdk_module() -> CloudinaryClient:
    """Return the real SDK as the adapter's client.

    The composition root's default. The returned binding holds no state of its
    own, so constructing one per process introduces no module-level singleton,
    and the only process-wide object the adapter writes through it is the SDK's
    own configuration, filled from the injected `CloudinaryConfiguration`.
    """
    return _CloudinarySdkBinding()


class CloudinaryStorageAdapter(StoragePort):
    """Stores objects on Cloudinary behind the provider-neutral port.

    Constructed once, in the composition root, with its configuration and its
    resilience policy injected. The policy belongs to the dependency rather than
    to a call site, so the breaker sees every Cloudinary call the process makes.
    """

    def __init__(
        self,
        configuration: CloudinaryConfiguration,
        policy: ResiliencePolicy,
        *,
        client: CloudinaryClient | None = None,
        logger: StructuredLogger | None = None,
    ) -> None:
        if policy.dependency_name != self.provider_name:
            # A policy built for another dependency would let an unhealthy R2
            # endpoint trip calls to Cloudinary. The wiring is the composition
            # root's job; getting it wrong is caught here, at construction.
            raise ValueError(
                f"policy dependency must be {self.provider_name!r}, "
                f"received {policy.dependency_name!r}"
            )

        self._configuration = configuration
        self._policy = policy
        self._client = client if client is not None else cloudinary_sdk_module()
        self._logger = (logger or get_logger(_STORAGE_LOGGER_NAME)).bind(
            component="cloudinary_storage_adapter",
            provider=self.provider_name,
        )

        # The SDK keeps one process-global configuration object, and touching a
        # shared instance here is what "configure the client" means for this
        # library. The adapter is constructed once, in the composition root, and
        # the values come only from the injected configuration: the SDK is never
        # asked to read the environment, and an idle `CLOUDINARY_URL` in a
        # deployment whose active provider is R2 has no effect.
        #
        # The SDK's environment read happens at import time and cannot be
        # prevented; what matters is that the values applied here win, and that
        # a credential never reaches a log line or an error message.
        sdk_configuration = self._client.config()
        sdk_configuration.cloud_name = configuration.cloud_name
        sdk_configuration.api_key = configuration.api_key.get_secret_value()
        sdk_configuration.api_secret = configuration.api_secret.get_secret_value()

    @property
    def provider_name(self) -> str:
        """Return the provider identifier persisted alongside every object."""
        return CLOUDINARY_PROVIDER_NAME

    # ------------------------------------------------------------------
    # StoragePort
    # ------------------------------------------------------------------

    async def upload(self, request: StorageUploadRequest) -> StoredObject:
        """Store an object and return its provider-neutral metadata.

        The checksum and the reported size are computed from the bytes in hand,
        never read back from the provider: a checksum that depends on the
        provider's answer is unavailable exactly when it is needed most.

        The upload is announced as idempotent because it carries
        ``overwrite=True``: the same key rewrites the same stored object, so a
        retry after an ambiguous timeout replaces the asset rather than creating
        a second identifier to reconcile.
        """
        public_id, asset_format = self._public_id_for(request.key)

        def stage_upload() -> Mapping[str, Any]:
            parameters: _UploadParameters = {
                "public_id": public_id,
                "format": asset_format,
                "resource_type": self._resource_type_for_key(request.key),
                "overwrite": True,
                "invalidate": True,
            }
            return self._client.upload(BytesIO(request.content), **parameters)

        response = await self._run_through_policy(
            stage_upload,
            operation="upload",
            is_idempotent=True,
        )

        stored = StoredObject(
            provider=self.provider_name,
            key=request.key,
            mime_type=request.mime_type,
            size_bytes=len(request.content),
            checksum_sha256=compute_sha256(request.content),
            delivery_url=await self.build_delivery_url(key=request.key, is_public=True),
            width=_positive_dimension(response.get("width")),
            height=_positive_dimension(response.get("height")),
        )
        self._logger.info(
            "object_stored",
            tenant_id=request.tenant_id,
            key_reference=self._key_reference(request.key),
            mime_type=request.mime_type,
            size_bytes=stored.size_bytes,
            provider_version=_provider_version(response),
        )
        return stored

    async def delete(self, *, key: str, tenant_id: str) -> None:
        """Delete an object. Deleting a missing object is not an error.

        The ownership check runs before the provider is contacted, because a
        delete cannot be undone.
        """
        self._require_tenant_ownership(operation="delete", key=key, tenant_id=tenant_id)
        public_id, _ = self._public_id_for(key)

        def stage_delete() -> Mapping[str, Any]:
            return self._client.destroy(
                public_id,
                resource_type=self._resource_type_for_key(key),
                invalidate=True,
            )

        await self._run_through_policy(stage_delete, operation="delete", is_idempotent=True)
        self._logger.info(
            "object_deleted",
            tenant_id=tenant_id,
            key_reference=self._key_reference(key),
        )

    async def exists(self, *, key: str, tenant_id: str) -> bool:
        """Return True when the object exists and belongs to the tenant.

        A missing asset is an answer, not a failure: `NotFoundError` is the only
        provider error converted to `False`. Everything else propagates, so an
        outage is never reported as "the object is not there".
        """
        self._require_tenant_ownership(operation="exists", key=key, tenant_id=tenant_id)
        public_id, _ = self._public_id_for(key)

        def stage_lookup() -> bool:
            try:
                self._client.resource(
                    public_id,
                    resource_type=self._resource_type_for_key(key),
                )
            except cloudinary.exceptions.NotFound:
                return False
            except _CLOUDINARY_ERROR_TYPES as provider_error:
                raise self._translate_provider_failure(provider_error, operation="exists") from (
                    provider_error
                )
            return True

        return await self._run_through_policy(stage_lookup, operation="exists", is_idempotent=True)

    async def build_delivery_url(
        self,
        *,
        key: str,
        presentation_width: int | None = None,
        is_public: bool = False,
    ) -> str:
        """Return a URL a client can fetch the object from.

        `presentation_width` is a neutral request. Cloudinary honours it by
        generating a sized rendition on delivery, which is the whole reason this
        provider is selectable: no extra variant is stored (ADR-0009). The
        transformation string built from the width exists only inside this
        method.
        """
        public_id, asset_format = self._public_id_for(key)

        def stage_url() -> str:
            options: dict[str, Any] = {
                "resource_type": self._resource_type_for_key(key),
                "type": _PUBLIC_DELIVERY_TYPE if is_public else _PRIVATE_DELIVERY_TYPE,
                "secure": self._configuration.secure_delivery,
                "sign_url": not is_public,
                "format": asset_format,
            }
            transformation = _transformation_for(key, presentation_width)
            if transformation is not None:
                options["transformation"] = transformation
            return str(self._client.url(public_id, **options))

        return await self._run_through_policy(
            stage_url,
            operation="build_delivery_url",
            is_idempotent=True,
        )

    async def close(self) -> None:
        """Release the adapter's resources.

        Nothing is held open. The SDK issues a request per call rather than
        pooling a connection the adapter owns, and the configuration object is
        process-global rather than per-adapter. The method exists because the
        port requires it and because a future SDK that does pool connections
        must have somewhere to close them.
        """
        self._logger.info("storage_adapter_closed")

    # ------------------------------------------------------------------
    # Key mapping
    # ------------------------------------------------------------------

    def _public_id_for(self, key: str) -> tuple[str, str]:
        """Return (Cloudinary public identifier, asset format) for a neutral key.

        The mapping is a pure function of the key and the configured upload
        folder, which is what makes ``exists``, ``delete`` and delivery agree on
        one identifier without a database column holding the provider's name for
        it.

        The extension is dropped rather than embedded: the SDK strips a trailing
        extension into its own ``format`` option, which would put a dot-free
        public identifier on the outside and an un-strippable format on the
        inside. The extension therefore never reaches the provider, and the
        format is passed explicitly so the stored asset's format is derived from
        the key rather than guessed by the SDK from a file name.
        """
        relative_key = _relative_storage_key(key)
        folder = self._configuration.upload_folder.strip("/")
        prefixed_key = f"{folder}/{relative_key}" if folder else relative_key
        path_without_extension, extension = _split_filename_extension(prefixed_key)
        return path_without_extension, extension or _MISSING_EXTENSION_FORMAT

    def _key_for_public_id(self, public_id: str, *, asset_format: str) -> str:
        """Return the neutral key a Cloudinary public identifier came from.

        The inverse of :meth:`_public_id_for`. If the inverse of a mapping is
        not defined, the mapping is not reversible, and a stored object becomes
        unresolvable the moment anything needs its neutral key again.
        """
        folder = self._configuration.upload_folder.strip("/")
        if folder:
            prefix = f"{folder}/"
            if not public_id.startswith(prefix):
                raise StorageOperationError(
                    operation="reverse_key_mapping",
                    layer=ErrorLayer.INTEGRATION,
                    entity="storage_object",
                    detail=(
                        "public identifier is outside the configured upload folder: "
                        f"expected_prefix={folder}"
                    ),
                )
            relative_key = public_id[len(prefix) :]
        else:
            relative_key = public_id

        if asset_format and asset_format != _MISSING_EXTENSION_FORMAT:
            relative_key = f"{relative_key}.{asset_format}"
        return f"{_TENANT_ROOT_SEGMENT}/{relative_key}"

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _run_through_policy(
        self,
        synchronous_call: Callable[[], T],
        *,
        operation: str,
        is_idempotent: bool,
    ) -> T:
        """Run one SDK call under the injected policy, in a worker thread.

        Every outbound Cloudinary call passes through here, so timeout, breaker,
        bulkhead, retry and error translation cannot be forgotten at a call
        site. The callable is synchronous because the SDK is.

        A policy timeout abandons the await; it cannot cancel the worker thread,
        so the HTTP request runs to completion and its result is discarded. That
        is a property of running a synchronous SDK off the event loop rather
        than a defect to work around, and the SDK's own request timeout bounds
        how long the thread lives.
        """

        async def call_provider() -> T:
            try:
                return await asyncio.to_thread(synchronous_call)
            except _CLOUDINARY_ERROR_TYPES as provider_error:
                raise self._translate_provider_failure(
                    provider_error, operation=operation
                ) from provider_error

        return await self._policy.execute(
            call_provider,
            operation=operation,
            is_idempotent=is_idempotent,
            retryable_errors=_RETRYABLE_CLOUDINARY_ERRORS,
        )

    def _translate_provider_failure(
        self,
        provider_error: BaseException,
        *,
        operation: str,
    ) -> StorageUnavailableError | StorageOperationError:
        """Translate a Cloudinary exception into the application hierarchy.

        Availability is separated from every other failure so the transport
        layer can map one to 503 and the other to 502 without knowing that
        Cloudinary exists. The provider exception is attached as the cause:
        `ErrorContext` records the cause chain as type names only, so the SDK's
        message (which can carry a request URL) never reaches a log or a client.
        """
        detail = (
            f"provider={self.provider_name} operation={operation} "
            f"provider_error={type(provider_error).__name__}"
        )
        if isinstance(provider_error, _RETRYABLE_CLOUDINARY_ERRORS):
            return StorageUnavailableError(operation=operation, detail=detail, cause=provider_error)
        return StorageOperationError(operation=operation, detail=detail, cause=provider_error)

    def _require_tenant_ownership(self, *, operation: str, key: str, tenant_id: str) -> None:
        """Reject a key that is not inside the caller's tenant prefix.

        A cross-tenant key is a defect in the caller, not a request error, and
        the operation is refused before the provider is contacted. It is logged
        as a security event because reaching another tenant's prefix means
        something upstream constructed a key from the wrong tenant.
        """
        if key_belongs_to_tenant(key, tenant_id):
            return
        key_reference = self._key_reference(key)
        self._logger.error(
            "storage_cross_tenant_key_rejected",
            security_event="tenant_isolation",
            operation=operation,
            tenant_id=tenant_id,
            key_reference=key_reference,
        )
        raise TenantIsolationError(
            operation=operation,
            layer=ErrorLayer.SECURITY,
            entity="storage_object",
            identifier=key_reference,
            detail=(
                f"key is outside the tenant prefix: tenant_id={tenant_id} "
                f"key_reference={key_reference}"
            ),
        )

    @staticmethod
    def _key_reference(key: str) -> str:
        """Return a short digest that identifies a key without being the key.

        The adapter is the only place allowed to know a public identifier, and a
        log line is not an exception to that rule. The digest lets two lines
        about the same object be correlated by an engineer reading the logs,
        without putting a client-reachable path into the log store.
        """
        return sha256(key.encode("utf-8")).hexdigest()[:_KEY_FINGERPRINT_LENGTH]

    def _resource_type_for_key(self, key: str) -> str:
        """Return the Cloudinary resource type for a neutral key.

        The neutral key carries no content type, so the extension decides. The
        media pipeline stores images; a receipt or invoice attachment is stored
        as a raw asset, where an image transformation does not apply and the
        port's width request is deliberately ignored rather than silently
        mangled.
        """
        _, extension = _split_filename_extension(key)
        if extension in _IMAGE_EXTENSIONS:
            return _IMAGE_RESOURCE_TYPE
        return _RAW_RESOURCE_TYPE


def _relative_storage_key(key: str) -> str:
    """Strip the tenant root from a neutral key.

    The prefix is required rather than optional: a key without it did not come
    from `StorageObjectKey`, and guessing what it meant would be worse than
    refusing it.
    """
    prefix = f"{_TENANT_ROOT_SEGMENT}/"
    if not key.startswith(prefix):
        raise StorageOperationError(
            operation="map_storage_key",
            layer=ErrorLayer.INTEGRATION,
            entity="storage_object",
            detail=f"key does not start with {prefix!r}",
        )
    relative_key = key[len(prefix) :]
    if not relative_key:
        raise StorageOperationError(
            operation="map_storage_key",
            layer=ErrorLayer.INTEGRATION,
            entity="storage_object",
            detail="key has no path after the tenant root",
        )
    return relative_key


def _split_filename_extension(path: str) -> tuple[str, str]:
    """Split a path into (everything before the last dot, lowercase extension).

    Only the final path segment is examined, so a dot in a tenant or resource
    identifier cannot be mistaken for a file extension.
    """
    last_separator = path.rfind("/")
    last_dot = path.rfind(".")
    if last_dot <= last_separator + 1:
        return path, ""
    return path[:last_dot], path[last_dot + 1 :].lower()


def _transformation_for(key: str, presentation_width: int | None) -> dict[str, Any] | None:
    """Encode a requested presentation width as a Cloudinary transformation.

    This is the only place in the codebase that knows Cloudinary's
    transformation syntax. Everywhere else the caller asks for a width, because
    a provider string crossing the port would put the provider back into every
    service signature.

    The scale mode is `c_limit`: down to the requested width, never up. A stored
    asset smaller than the request is delivered unchanged rather than inflated.

    **Returned as a mapping, not as a string, and that is not a style choice.**
    The SDK treats a transformation given as a string as the name of a
    transformation *saved in the account*, and renders it as `t_w_640,c_limit` -
    which Cloudinary answers with a 400 for an account where no such named
    transformation exists. A mapping is rendered inline as the parameters it
    contains, which is what a per-request width actually is. This cost a broken
    image on every product card to find, so it is written down.
    """
    if presentation_width is None:
        return None
    if presentation_width < 1:
        raise StorageOperationError(
            operation="build_delivery_url",
            layer=ErrorLayer.INTEGRATION,
            entity="storage_object",
            detail=f"presentation_width must be positive, received {presentation_width}",
        )
    if _split_filename_extension(key)[1] not in _IMAGE_EXTENSIONS:
        # A raw asset has no image transformation pipeline, so the stored object
        # is delivered unchanged and the client sizes it (ADR-0009).
        return None
    return {"width": presentation_width, "crop": "limit"}


def _positive_dimension(reported: Any) -> int | None:
    """Return a provider-reported dimension when it is a usable positive integer.

    The provider's answer is not trusted to be a well-formed number, and a
    missing dimension is reported as absent rather than as a zero that a caller
    would render as an empty image.
    """
    if isinstance(reported, bool) or not isinstance(reported, int):
        return None
    return reported if reported > 0 else None


def _provider_version(response: Mapping[str, Any]) -> str:
    """Return the provider's asset version for the log line.

    The version is what identifies which stored revision was written, which is
    the useful half of the provider's response. The public identifier is not
    logged.
    """
    reported = response.get("version")
    return str(reported) if reported is not None else "unknown"


def cloudinary_error_type_names() -> tuple[str, ...]:
    """Return the provider exception names this adapter translates.

    Exposed for the test suite, which asserts that a provider failure never
    surfaces as one of these names. Read-only and derived from the SDK, so the
    assertion cannot drift from the translation table.
    """
    return tuple(error_type.__name__ for error_type in _CLOUDINARY_ERROR_TYPES)
