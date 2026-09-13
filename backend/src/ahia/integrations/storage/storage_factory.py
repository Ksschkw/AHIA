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

from ahia.core.config import (
    CloudinaryConfiguration,
    R2Configuration,
    Settings,
    StorageProviderName,
)
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
    provider: StorageProviderName | None = None,
    logger: StructuredLogger | None = None,
) -> ResiliencePolicy:
    """Build the outbound policy for one storage provider.

    One policy per provider, named after it. The timeout comes from the
    provider's own configuration because the providers have different latency
    shapes; everything else comes from the shared storage policy settings, so
    switching providers does not silently change how forgiving the boundary is.

    The provider defaults to the active one. Passing another is how a deployment that
    has used both - before and after a switch - gives each its own breaker, so an
    unhealthy endpoint on one cannot trip calls to the other.
    """
    provider = provider or settings.storage_provider
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
    """Build the storage adapter for the active provider.

    Kept as the single-adapter entry point, because most callers want exactly that.
    `build_storage_adapters` is what the composition root uses, so a deployment that has
    credentials for both providers can still read an object written before a switch.
    """
    return build_storage_adapters(settings, logger=logger)[settings.storage_provider.value]


def build_storage_adapters(
    settings: Settings,
    *,
    logger: StructuredLogger | None = None,
) -> dict[str, StoragePort]:
    """Build an adapter for every provider whose credentials are configured.

    The key is the provider's own name, which is the value stored on every image row.
    Writes always go to the active adapter; this mapping exists so that a row written
    before a switch is still read, deleted and linked by the provider that actually
    holds its bytes - asking the new provider to sign a key in the old one's bucket
    would produce a link that does not resolve.

    A provider with incomplete credentials is absent rather than an error: a deployment
    that has only ever used one provider has no credentials for the other, and that is a
    normal configuration. The *active* provider missing is a fault, and it raises.
    """
    resolved_logger = logger or get_logger(_STORAGE_LOGGER_NAME)
    adapters: dict[str, StoragePort] = {}

    for provider in StorageProviderName:
        configuration = settings.storage_configuration_for(provider)
        if configuration is None:
            continue
        adapters[provider.value] = _build_adapter(
            settings,
            provider=provider,
            configuration=configuration,
            logger=resolved_logger,
        )

    active = settings.storage_provider.value
    if active not in adapters:
        raise ConfigurationError(
            operation="build_storage_adapter",
            entity="storage_provider",
            detail=f"the active provider {active!r} has no complete configuration",
        )
    resolved_logger.info(
        "storage_adapters_available",
        active_provider=active,
        configured_providers=sorted(adapters),
    )
    return adapters


def _build_adapter(
    settings: Settings,
    *,
    provider: StorageProviderName,
    configuration: R2Configuration | CloudinaryConfiguration,
    logger: StructuredLogger,
) -> StoragePort:
    """Construct one adapter. The vendor SDK is imported only for the provider in use."""
    policy = build_storage_policy(settings, provider=provider, logger=logger)

    if provider is StorageProviderName.R2:
        from ahia.integrations.storage.r2_client import R2StorageAdapter

        assert isinstance(configuration, R2Configuration)
        adapter = R2StorageAdapter(
            configuration,
            policy,
            signed_url_ttl_seconds=settings.storage_signed_url_ttl_seconds,
            logger=logger,
        )
        logger.info("storage_adapter_built", **configuration.describe())
        return adapter

    if provider is StorageProviderName.CLOUDINARY:
        from ahia.integrations.storage.cloudinary_client import CloudinaryStorageAdapter

        assert isinstance(configuration, CloudinaryConfiguration)
        cloudinary_adapter = CloudinaryStorageAdapter(configuration, policy, logger=logger)
        logger.info("storage_adapter_built", **configuration.describe())
        return cloudinary_adapter

    # Unreachable through configuration, because the provider is an enum. Kept so a
    # future enum member cannot silently fall through to no adapter at all.
    raise ConfigurationError(  # pragma: no cover
        operation="build_storage_adapter",
        entity="storage_provider",
        detail=f"no adapter is implemented for provider {provider!r}",
    )
