"""Storage adapter selection.

This module is the only place in the codebase that branches on the configured
provider. Everything downstream receives a `StoragePort` and cannot tell which
adapter it got, which is what makes `STORAGE_PROVIDER=r2` and
`STORAGE_PROVIDER=cloudinary` a configuration change rather than a code change.

The resilience policy is built here too, one per dependency, with the provider's
name attached. A breaker belongs to the dependency, so an unhealthy Cloudinary
endpoint must not trip calls to R2 and an unhealthy R2 bucket must not trip
Cloudinary. Both adapters assert that they received a policy built for them.
"""

from __future__ import annotations

from typing import Final

from ahia.core.config import Settings, StorageProviderName
from ahia.core.errors import ConfigurationError
from ahia.core.logging import StructuredLogger, get_logger
from ahia.core.ports.storage_port import StoragePort
from ahia.core.resilience import (
    CircuitBreakerConfiguration,
    ResiliencePolicy,
    RetryPolicy,
    build_policy,
)

_STORAGE_LOGGER_NAME: Final[str] = "ahia.integrations.storage"

#: Base delay for outbound storage retry. Small, because a storage call sits in
#: a user's request path; the ceiling bounds the worst case.
_RETRY_BASE_DELAY_SECONDS: Final[float] = 0.2
_RETRY_MAXIMUM_DELAY_SECONDS: Final[float] = 2.0


def build_storage_policy(
    settings: Settings,
    *,
    logger: StructuredLogger | None = None,
) -> ResiliencePolicy:
    """Build the outbound policy for the active storage provider.

    One policy per provider, named after it. The timeout comes from the
    provider's own configuration because the providers have different latency
    shapes; everything else comes from the shared storage policy settings, so
    switching providers does not silently change how forgiving the boundary is.
    """
    provider = settings.storage_provider
    timeout_seconds = (
        settings.r2_request_timeout_seconds
        if provider is StorageProviderName.R2
        else settings.cloudinary_request_timeout_seconds
    )

    return build_policy(
        provider.value,
        timeout_seconds=timeout_seconds,
        breaker_configuration=CircuitBreakerConfiguration(
            failure_threshold=settings.storage_circuit_failure_threshold,
            reset_timeout_seconds=settings.storage_circuit_reset_seconds,
        ),
        max_concurrent_calls=settings.storage_max_concurrent_calls,
        retry=RetryPolicy(
            max_attempts=settings.storage_retry_max_attempts,
            base_delay_seconds=_RETRY_BASE_DELAY_SECONDS,
            max_delay_seconds=_RETRY_MAXIMUM_DELAY_SECONDS,
        ),
        logger=logger,
    )


def build_storage_adapter(
    settings: Settings,
    *,
    logger: StructuredLogger | None = None,
) -> StoragePort:
    """Build the storage adapter for the configured provider.

    Called from the composition root, once, at startup. The imports are local so
    that a deployment which never selects a provider does not pay its import
    cost, and so a vendor SDK is loaded only when it is actually in use.
    """
    resolved_logger = logger or get_logger(_STORAGE_LOGGER_NAME)
    policy = build_storage_policy(settings, logger=resolved_logger)

    if settings.storage_provider is StorageProviderName.R2:
        from ahia.integrations.storage.r2_client import R2StorageAdapter

        r2_configuration = settings.r2_configuration()
        adapter = R2StorageAdapter(
            r2_configuration,
            policy,
            signed_url_ttl_seconds=settings.storage_signed_url_ttl_seconds,
            logger=resolved_logger,
        )
        resolved_logger.info("storage_adapter_selected", **r2_configuration.describe())
        return adapter

    if settings.storage_provider is StorageProviderName.CLOUDINARY:
        from ahia.integrations.storage.cloudinary_client import CloudinaryStorageAdapter

        cloudinary_configuration = settings.cloudinary_configuration()
        cloudinary_adapter = CloudinaryStorageAdapter(
            cloudinary_configuration,
            policy,
            logger=resolved_logger,
        )
        resolved_logger.info("storage_adapter_selected", **cloudinary_configuration.describe())
        return cloudinary_adapter

    # Unreachable through configuration, because the provider is an enum. Kept
    # so a future enum member cannot silently fall through to no adapter at all.
    raise ConfigurationError(  # pragma: no cover
        operation="build_storage_adapter",
        entity="storage_provider",
        detail=f"no adapter is implemented for provider {settings.storage_provider!r}",
    )
