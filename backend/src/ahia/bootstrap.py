"""The composition root.

Placement note: this module lives at the package root rather than inside `core`.
A composition root must import every layer, and the architecture contracts forbid
`core` from importing application layers. Keeping the root outside `core` lets
that rule stay absolute instead of acquiring a carve-out. See ADR-0011.

Every dependency the application uses is constructed here, once, at startup, and
injected where it is needed. Nothing constructs its own client, reads the
environment for itself, or keeps a module-level singleton.

Why this matters beyond tidiness:

* a module-level singleton holding a connection or a client is untestable and
  leaks between tests, and its lifetime is whatever the import order happens to
  be
* provider selection has to happen somewhere; keeping it here means exactly one
  module knows whether the bytes go to one storage provider or another
* fail-loud startup: a configuration the runtime cannot honour - an image
  encoder that is absent, a permission registry that references a permission
  which does not exist - stops the process before it serves a request, rather
  than at the first upload
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ahia.core.config import FEATURE_FLAGS, Settings
from ahia.core.database import Database, configure_sqlalchemy_logging
from ahia.core.logging import StructuredLogger, configure_logging, get_logger
from ahia.core.permissions.permissions_registry import (
    ALL_PERMISSIONS,
    SYSTEM_ROLES,
    validate_registry,
)
from ahia.core.ports.media_port import MediaProcessingPort
from ahia.core.ports.storage_port import StoragePort
from ahia.core.resilience import ResiliencePolicy
from ahia.core.security import PasswordHasher, TokenService
from ahia.integrations.media.image_processor import PillowImageProcessor
from ahia.integrations.storage.storage_factory import (
    build_storage_adapter,
    build_storage_policy,
)
from ahia.services.auth_service import AuthService
from ahia.services.category_service import CategoryService
from ahia.services.device_service import DeviceService
from ahia.services.permission_service import PermissionService
from ahia.services.product_image_service import ProductImageService
from ahia.services.product_service import ProductService
from ahia.services.storage_quota_service import StorageQuotaService
from ahia.services.tenant_membership_service import TenantMembershipService
from ahia.services.tenant_service import TenantService
from ahia.services.user_service import UserService

_CONTAINER_LOGGER_NAME: Final[str] = "ahia.core.container"


@dataclass(slots=True)
class ApplicationContainer:
    """Every constructed dependency, in one object.

    Passed to the transport layer through the application state, and to tests
    directly. It holds no module-level state, so two containers in one process
    are fully independent.
    """

    settings: Settings
    database: Database
    storage: StoragePort
    media: MediaProcessingPort
    storage_policy: ResiliencePolicy
    storage_quota_service: StorageQuotaService
    user_service: UserService
    auth_service: AuthService
    tenant_service: TenantService
    membership_service: TenantMembershipService
    permission_service: PermissionService
    device_service: DeviceService
    category_service: CategoryService
    product_service: ProductService
    product_image_service: ProductImageService
    token_service: TokenService
    password_hasher: PasswordHasher
    logger: StructuredLogger


def build_application_container(settings: Settings) -> ApplicationContainer:
    """Construct every dependency and validate what can be validated up front.

    Synchronous on purpose: construction performs no I/O. The database engine is
    created lazily by the driver, and the storage adapter is only constructed,
    not contacted, so a dependency that happens to be down does not prevent the
    process from starting and answering a liveness probe.
    """
    configure_logging(settings)
    configure_sqlalchemy_logging(settings)
    logger = get_logger(_CONTAINER_LOGGER_NAME).bind(component="container")

    # A registry that references a permission which does not exist is a check
    # that can never pass. Catching it here means it is a startup failure.
    validate_registry()

    database = Database(settings, logger=logger)

    storage_policy = build_storage_policy(settings, logger=logger)
    storage = build_storage_adapter(settings, logger=logger)

    media = PillowImageProcessor(settings.storage_limits(), logger=logger)
    # A target format this runtime cannot encode is a misconfiguration, not a
    # runtime condition: the stored mime type is part of the persisted metadata
    # and of the delivery contract.
    media.ensure_target_format_is_available()

    token_service = TokenService(
        secret=settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        access_token_ttl_minutes=settings.access_token_ttl_minutes,
        refresh_token_pepper=settings.refresh_token_pepper.get_secret_value(),
        public_token_bytes=settings.public_token_bytes,
    )

    password_hasher = PasswordHasher(
        time_cost=settings.argon2_time_cost,
        memory_cost_kib=settings.argon2_memory_cost_kib,
        parallelism=settings.argon2_parallelism,
        minimum_length=settings.password_min_length,
    )

    storage_quota_service = StorageQuotaService(
        unit_of_work_factory=database.unit_of_work_factory(),
        quota_bytes=settings.storage_limits().max_tenant_storage_bytes,
        logger=logger,
    )

    user_service = UserService(
        unit_of_work_factory=database.unit_of_work_factory(),
        logger=logger,
    )

    auth_service = AuthService(
        unit_of_work_factory=database.unit_of_work_factory(),
        token_service=token_service,
        password_hasher=password_hasher,
        refresh_token_ttl_days=settings.refresh_token_ttl_days,
        access_token_ttl_minutes=settings.access_token_ttl_minutes,
        default_phone_country_code=settings.default_phone_country_code,
        logger=logger,
    )

    tenant_service = TenantService(
        unit_of_work_factory=database.unit_of_work_factory(),
        logger=logger,
    )

    membership_service = TenantMembershipService(
        unit_of_work_factory=database.unit_of_work_factory(),
        token_service=token_service,
        logger=logger,
    )

    permission_service = PermissionService(
        unit_of_work_factory=database.unit_of_work_factory(),
        logger=logger,
    )

    device_service = DeviceService(
        unit_of_work_factory=database.unit_of_work_factory(),
        logger=logger,
    )

    category_service = CategoryService(
        unit_of_work_factory=database.unit_of_work_factory(),
        logger=logger,
    )

    product_service = ProductService(
        unit_of_work_factory=database.unit_of_work_factory(),
        token_service=token_service,
        logger=logger,
    )

    product_image_service = ProductImageService(
        unit_of_work_factory=database.unit_of_work_factory(),
        storage=storage,
        media=media,
        storage_quota_service=storage_quota_service,
        limits=settings.storage_limits(),
        logger=logger,
    )

    container = ApplicationContainer(
        settings=settings,
        database=database,
        storage=storage,
        media=media,
        storage_policy=storage_policy,
        storage_quota_service=storage_quota_service,
        user_service=user_service,
        auth_service=auth_service,
        tenant_service=tenant_service,
        membership_service=membership_service,
        permission_service=permission_service,
        device_service=device_service,
        category_service=category_service,
        product_service=product_service,
        product_image_service=product_image_service,
        token_service=token_service,
        password_hasher=password_hasher,
        logger=logger,
    )

    log_startup_configuration(settings, container, logger=logger)
    return container


async def dispose_application_container(container: ApplicationContainer) -> None:
    """Release every managed resource.

    Called from application shutdown. Failures are logged and swallowed: a
    shutdown path that raises leaves the process in a worse state than one that
    reports and continues closing.
    """
    logger = container.logger

    try:
        await container.storage.close()
    except Exception as error:  # noqa: BLE001 - shutdown must not raise
        logger.error("storage_shutdown_failed", error_type=type(error).__name__)

    try:
        await container.database.dispose()
    except Exception as error:  # noqa: BLE001 - shutdown must not raise
        logger.error("database_shutdown_failed", error_type=type(error).__name__)

    logger.info("application_container_disposed")


def log_startup_configuration(
    settings: Settings,
    container: ApplicationContainer,
    *,
    logger: StructuredLogger | None = None,
) -> None:
    """Write the startup summary: one line per feature flag, plus the shape.

    The first question when behaviour differs from expectation is "what was
    configured", and this answers it without a redeploy or a shell into the
    container. Nothing secret is logged: storage configuration describes itself
    without credentials, and the signing secret is never read here.
    """
    startup_logger = logger or container.logger

    startup_logger.info(
        "application_starting",
        app_name=settings.app_name,
        app_version=settings.app_version,
        environment=settings.app_env.value,
        storage_provider=settings.storage_provider.value,
        media_target_format=settings.media_target_format.value,
        permission_count=len(ALL_PERMISSIONS),
        system_role_count=len(SYSTEM_ROLES),
    )

    startup_logger.info("storage_policy_configured", **container.storage_policy.describe())
    startup_logger.info("storage_limits_configured", **settings.storage_limits().as_log_fields())

    # One line per flag, at INFO, so "the system behaved differently" has an
    # answer in the first line of output rather than in a configuration audit.
    for flag, enabled in settings.feature_flag_states():
        startup_logger.info("feature_flag", **flag.as_log_fields(enabled))

    if not FEATURE_FLAGS:  # pragma: no cover - a registry with no flags is a smell
        startup_logger.warning("feature_flag_registry_empty")
