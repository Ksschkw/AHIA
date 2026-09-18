"""Typed configuration and the feature flag registry.

This is the only module in the codebase permitted to read the environment.
Everything else receives configuration through dependency injection from the
composition root, so a setting has exactly one definition, one default and one
place to look when a deployed environment behaves differently than expected.

Rules this module enforces:

1. A missing required value fails at startup with the variable named, never at
   the first request. `ConfigurationError` deliberately names the variable and
   never its value, because the value may be a secret.
2. Production defaults are the safe ones. Console logging, disabled TLS and a
   short signing secret are rejected outright in production rather than warned
   about.
3. Credentials for an inactive storage provider are neither required nor
   validated, so a deployment that uses one provider does not need the other's
   secrets to boot.
4. Feature flags are declared here, with their type, default, purpose, date
   added and removal condition. No security control is ever flag-gated.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ahia.core.errors import ConfigurationError

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class AppEnvironment(StrEnum):
    """The deployment profile. It selects behaviour; nothing branches on it inline."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogFormat(StrEnum):
    """Log rendering. JSON everywhere except interactive local development."""

    JSON = "json"
    CONSOLE = "console"


class StorageProviderName(StrEnum):
    """The supported object storage providers.

    Adding a provider means adding one enum member, one adapter and one factory
    branch. No service changes.
    """

    R2 = "r2"
    CLOUDINARY = "cloudinary"


class MediaTargetFormat(StrEnum):
    """The stored image format.

    WebP is the default: widely supported, efficient, and encodable by the
    runtime image library without an extra system codec. AVIF is offered because
    it is more efficient still, and is validated for availability at startup
    rather than assumed.
    """

    WEBP = "webp"
    JPEG = "jpeg"
    PNG = "png"
    AVIF = "avif"


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FeatureFlag:
    """One runtime toggle.

    A flag is a temporary deploy/release decoupling tool, not configuration.
    Booleans only: a value with a range is configuration, not a flag.
    """

    environment_variable: str
    setting_attribute: str
    default: bool
    description: str
    date_added: str
    removal_condition: str

    def as_log_fields(self, enabled: bool) -> dict[str, str]:
        """Return the fields logged once per flag at startup."""
        return {
            "flag": self.environment_variable,
            "enabled": "true" if enabled else "false",
            "added": self.date_added,
        }


#: The complete flag register. Order is stable so startup logs can be diffed.
FEATURE_FLAGS: Final[tuple[FeatureFlag, ...]] = (
    FeatureFlag(
        environment_variable="FEATURE_OFFLINE_SYNC",
        setting_attribute="feature_offline_sync",
        default=False,
        description="server-side sync push and pull endpoints",
        date_added="2025-09-13",
        removal_condition="when the mobile sync engine ships to every tenant",
    ),
    FeatureFlag(
        # The attribute name must match the variable: pydantic-settings maps one to the other, and
        # a setting whose name is misspelled never receives its value - the flag then sits at its
        # default for ever, and the environment variable looks like it does nothing.
        environment_variable="FEATURE_STOREFRONT_PUBLIC_PUBLISHING",
        setting_attribute="feature_storefront_public_publishing",
        default=False,
        description="whether a tenant may publish a public storefront",
        date_added="2025-09-13",
        removal_condition="when public storefronts are generally available",
    ),
    FeatureFlag(
        environment_variable="FEATURE_MEDIA_UPLOAD",
        setting_attribute="feature_media_upload",
        default=False,
        description="whether tenants may upload product images and storefront media",
        date_added="2025-09-13",
        removal_condition="when media upload is enabled for every tenant",
    ),
    FeatureFlag(
        environment_variable="FEATURE_WHATSAPP_CLICK_TO_CHAT",
        setting_attribute="feature_whatsapp_click_to_chat",
        default=False,
        description="WhatsApp inquiry link generation",
        date_added="2025-09-13",
        removal_condition="when verified in production on both clients",
    ),
    FeatureFlag(
        environment_variable="FEATURE_AI_INSIGHTS",
        setting_attribute="feature_ai_insights",
        default=False,
        description="AI-generated insights and forecasts",
        date_added="2025-09-13",
        removal_condition="when AI insights are either adopted or dropped",
    ),
    FeatureFlag(
        environment_variable="FEATURE_SUPPLIER_MODULE",
        setting_attribute="feature_supplier_module",
        default=False,
        description="supplier and procurement endpoints",
        date_added="2025-09-13",
        removal_condition="when procurement reaches general availability",
    ),
    FeatureFlag(
        environment_variable="FEATURE_TRACKING_MODULE",
        setting_attribute="feature_tracking_module",
        default=False,
        description="shipment and tracking endpoints",
        date_added="2025-09-13",
        removal_condition="when logistics reaches general availability",
    ),
    FeatureFlag(
        environment_variable="FEATURE_NETWORK_MODULE",
        setting_attribute="feature_network_module",
        default=False,
        description="community and classifieds endpoints",
        date_added="2025-09-13",
        removal_condition="when the network module is adopted or dropped",
    ),
)

#: Names that must never appear as a flag. A flag that can disable a security
#: control is a backdoor with a nice name. The test suite asserts that no
#: declared flag matches these fragments.
FORBIDDEN_FLAG_FRAGMENTS: Final[tuple[str, ...]] = (
    "AUTH",
    "AUTHORIZATION",
    "PERMISSION",
    "VALIDATION",
    "RATE_LIMIT",
    "LOGGING",
    "TLS",
    "CSRF",
    "CORS",
)


# ---------------------------------------------------------------------------
# Derived configuration objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StorageLimits:
    """Provider-neutral upload and quota limits.

    Every value is configuration. Nothing in the media pipeline hard-codes a
    limit, because a limit that cannot be changed without a deploy is a limit
    that will be changed by a code hotfix at an inconvenient hour.
    """

    max_upload_bytes: int
    max_product_image_bytes: int
    max_image_width: int
    max_image_height: int
    max_images_per_product: int
    max_tenant_storage_bytes: int
    target_format: MediaTargetFormat
    image_quality: int
    strip_metadata: bool
    allowed_content_types: tuple[str, ...]

    def as_log_fields(self) -> dict[str, str]:
        """Return the limits for startup logging. No secrets are involved."""
        return {
            "max_upload_bytes": str(self.max_upload_bytes),
            "max_product_image_bytes": str(self.max_product_image_bytes),
            "max_image_width": str(self.max_image_width),
            "max_image_height": str(self.max_image_height),
            "max_images_per_product": str(self.max_images_per_product),
            "max_tenant_storage_bytes": str(self.max_tenant_storage_bytes),
            "target_format": self.target_format.value,
            "image_quality": str(self.image_quality),
        }


@dataclass(frozen=True, slots=True)
class R2Configuration:
    """Cloudflare R2 credentials and behaviour. Only the R2 adapter sees this."""

    endpoint: str
    access_key_id: SecretStr
    secret_access_key: SecretStr
    bucket: str
    region: str
    public_base_url: str | None
    request_timeout_seconds: float

    def describe(self) -> dict[str, str]:
        """Return non-secret fields for logs and diagnostics."""
        return {
            "provider": StorageProviderName.R2.value,
            "bucket": self.bucket,
            "region": self.region,
            "endpoint_host": _host_of(self.endpoint),
            "request_timeout_seconds": str(self.request_timeout_seconds),
        }


@dataclass(frozen=True, slots=True)
class CloudinaryConfiguration:
    """Cloudinary credentials and behaviour. Only the Cloudinary adapter sees this."""

    cloud_name: str
    api_key: SecretStr
    api_secret: SecretStr
    upload_folder: str
    secure_delivery: bool
    request_timeout_seconds: float

    def describe(self) -> dict[str, str]:
        """Return non-secret fields for logs and diagnostics."""
        return {
            "provider": StorageProviderName.CLOUDINARY.value,
            "cloud_name": self.cloud_name,
            "upload_folder": self.upload_folder,
            "secure_delivery": "true" if self.secure_delivery else "false",
        }


def _host_of(url: str) -> str:
    """Return the host of a URL without its path or query.

    A signed URL carries a credential in its query string, so only the host is
    ever kept for diagnostics.
    """
    without_scheme = url.split("://", maxsplit=1)[-1]
    return without_scheme.split("/", maxsplit=1)[0]


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

_DEVELOPMENT_JWT_SECRET_MINIMUM_LENGTH: Final[int] = 16
_PRODUCTION_JWT_SECRET_MINIMUM_LENGTH: Final[int] = 32


class Settings(BaseSettings):
    """Every environment variable the backend reads, in one place.

    Field names are the lowercase form of the environment variable. Aliases are
    not used: pydantic-settings matches `APP_ENV` to `app_env` case-insensitively,
    which keeps the mapping obvious to a reader.
    """

    model_config = SettingsConfigDict(
        env_file=os.environ.get("AHIA_ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Application --------------------------------------------------------
    app_env: AppEnvironment = AppEnvironment.DEVELOPMENT
    app_name: str = "AHIA"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.JSON
    correlation_id_header: str = "X-Correlation-ID"
    trusted_proxy_count: int = Field(default=0, ge=0, le=10)

    # -- Database -----------------------------------------------------------
    database_url: str
    database_migration_url: str | None = None
    database_require_ssl: bool = False
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_max_overflow: int = Field(default=5, ge=0, le=100)
    database_pool_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    database_statement_timeout_ms: int = Field(default=15_000, ge=1_000, le=600_000)
    test_database_url: str | None = None

    # -- Authentication -----------------------------------------------------
    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "ahia-api"
    jwt_audience: str = "ahia-clients"
    access_token_ttl_minutes: int = Field(default=15, ge=1, le=1_440)
    #: A year by default. A trader should not have to sign in again on a phone he owns, and the
    #: refresh token is revocable, rotatable and useless without the cookie it travels in - which is
    #: what makes a long life safe here in a way it would not be for a bearer token.
    refresh_token_ttl_days: int = Field(default=365, ge=1, le=365)
    refresh_token_pepper: SecretStr
    argon2_time_cost: int = Field(default=3, ge=1, le=10)
    argon2_memory_cost_kib: int = Field(default=65_536, ge=8_192, le=1_048_576)
    argon2_parallelism: int = Field(default=2, ge=1, le=16)
    password_min_length: int = Field(default=8, ge=8, le=128)

    # -- Transport security -------------------------------------------------
    cors_allowed_origins: str = ""
    cors_allow_credentials: bool = True
    hsts_max_age_seconds: int = Field(default=31_536_000, ge=0)
    content_security_policy: str = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    security_headers_enabled: bool = True

    # -- Rate limiting (always on; configuration only, never a flag) --------
    rate_limit_auth_per_minute: int = Field(default=10, ge=1, le=1_000)
    # One budget for every endpoint that sends a message: a password reset link, an invitation.
    # The name predates the invitation route; the value is what an operator tunes, and a second
    # number for the same cost would drift from this one.
    rate_limit_password_reset_per_hour: int = Field(default=5, ge=1, le=1_000)
    rate_limit_write_per_minute: int = Field(default=120, ge=1, le=10_000)
    rate_limit_global_per_minute: int = Field(default=600, ge=1, le=100_000)
    # The public storefront is the one surface an anonymous caller reaches, so it carries its own
    # limit rather than sharing the global one. Tighter than the global default because a shop
    # page is cheap to serve and easy to scrape, and a burst of one address is what the limit is
    # for. It is a security control: never behind a feature flag, and it fails closed.
    rate_limit_public_read_per_minute: int = Field(default=120, ge=1, le=100_000)

    # -- Operations ---------------------------------------------------------
    # The bearer token a scraper must present to read `/metrics`. Unset means the endpoint answers
    # as if it did not exist, which is the safe default: a deployment that has not decided who may
    # scrape has not decided to be scraped. It is a secret, so it is a `SecretStr` and never logged.
    metrics_auth_token: SecretStr | None = None

    # -- Storage selection --------------------------------------------------
    storage_provider: StorageProviderName = StorageProviderName.R2
    storage_signed_url_ttl_seconds: int = Field(default=900, ge=30, le=86_400)

    # -- Media and quota limits --------------------------------------------
    max_upload_size_mb: int = Field(default=5, ge=1, le=100)
    max_product_image_size_mb: int = Field(default=5, ge=1, le=100)
    max_product_image_width: int = Field(default=2_000, ge=64, le=10_000)
    max_product_image_height: int = Field(default=2_000, ge=64, le=10_000)
    max_product_images_per_product: int = Field(default=10, ge=1, le=100)
    max_tenant_storage_mb: int = Field(default=500, ge=1, le=1_000_000)
    media_target_format: MediaTargetFormat = MediaTargetFormat.WEBP
    media_image_quality: int = Field(default=82, ge=1, le=100)
    media_strip_metadata: bool = True
    media_allowed_content_types: str = "image/jpeg,image/png,image/webp,image/avif"

    # -- Cloudflare R2 (required only when it is the active provider) ------
    r2_endpoint: str | None = None
    r2_access_key_id: SecretStr | None = None
    r2_secret_access_key: SecretStr | None = None
    r2_bucket: str | None = None
    r2_region: str = "auto"
    r2_public_base_url: str | None = None
    r2_request_timeout_seconds: float = Field(default=10.0, gt=0, le=120)

    # -- Storage resilience policy (one set, applied per provider) ---------
    #
    # These belong to the dependency, not to a provider: a breaker is per
    # dependency, and swapping the active provider must not silently change how
    # forgiving the boundary is.
    storage_max_concurrent_calls: int = Field(default=8, ge=1, le=200)
    storage_retry_max_attempts: int = Field(default=3, ge=1, le=10)
    storage_circuit_failure_threshold: int = Field(default=5, ge=1, le=100)
    storage_circuit_reset_seconds: float = Field(default=60.0, gt=0, le=3_600)

    # -- Cloudinary (required only when it is the active provider) ---------
    cloudinary_cloud_name: str | None = None
    cloudinary_api_key: SecretStr | None = None
    cloudinary_api_secret: SecretStr | None = None
    cloudinary_upload_folder: str = "ahia"
    cloudinary_secure_delivery: bool = True
    cloudinary_request_timeout_seconds: float = Field(default=15.0, gt=0, le=120)

    # -- Public sharing and messaging --------------------------------------
    # Phone numbers are identity here: a trader types 0803..., an international
    # form is +234803..., and both must resolve to one account. Country-code
    # completion needs a default, and a default is configuration.
    default_phone_country_code: str = "234"
    public_web_base_url: str = "http://localhost:3000"
    whatsapp_click_to_chat_base_url: str = "https://wa.me"
    whatsapp_default_country_code: str = "234"
    public_token_bytes: int = Field(default=24, ge=16, le=64)

    # -- Feature flags ------------------------------------------------------
    feature_offline_sync: bool = False
    feature_storefront_public_publishing: bool = False
    feature_media_upload: bool = False
    feature_whatsapp_click_to_chat: bool = False
    feature_ai_insights: bool = False
    feature_supplier_module: bool = False
    feature_tracking_module: bool = False
    feature_network_module: bool = False

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        normalised = value.upper()
        if normalised not in allowed:
            raise ValueError(f"log level must be one of {sorted(allowed)}")
        return normalised

    @field_validator("default_phone_country_code")
    @classmethod
    def _validate_country_code(cls, value: str) -> str:
        """Return the calling code in its one canonical form, with the plus.

        **This used to strip the plus**, and five services worked around that locally with
        `f"+{code.lstrip('+')}"` - except the newest one, which passed the setting straight to the
        phone canonicaliser. That turned `08029876543` into `2348029876543`: a number with no way to
        tell a country code from a national prefix, stored against a customer who could never be
        matched to their own history. The workaround was in five places and the bug was in one.
        """
        digits = value.strip().lstrip("+")
        if not digits.isdigit() or not 1 <= len(digits) <= 4:
            raise ValueError("default phone country code must be 1 to 4 digits")
        return f"+{digits}"

    @field_validator("jwt_algorithm")
    @classmethod
    def _validate_jwt_algorithm(cls, value: str) -> str:
        # An allowlist. `none` is not an algorithm, and public-key algorithms
        # would let a client that knows the public key mint tokens.
        allowed = {"HS256", "HS384", "HS512"}
        if value not in allowed:
            raise ValueError(f"jwt algorithm must be one of {sorted(allowed)}")
        return value

    @model_validator(mode="after")
    def _validate_environment_consistency(self) -> Settings:
        if self.app_env is AppEnvironment.PRODUCTION:
            if self.log_format is not LogFormat.JSON:
                raise ValueError("production requires LOG_FORMAT=json")
            if not self.database_require_ssl:
                raise ValueError("production requires DATABASE_REQUIRE_SSL=true")
            if self.log_level == "DEBUG":
                raise ValueError("production rejects LOG_LEVEL=DEBUG")
            if self.cors_allow_credentials and "*" in self.cors_allowed_origin_list:
                raise ValueError("CORS may not allow '*' while credentials are enabled")

        minimum_secret_length = (
            _PRODUCTION_JWT_SECRET_MINIMUM_LENGTH
            if self.app_env is AppEnvironment.PRODUCTION
            else _DEVELOPMENT_JWT_SECRET_MINIMUM_LENGTH
        )
        if len(self.jwt_secret.get_secret_value()) < minimum_secret_length:
            raise ValueError(
                f"JWT_SECRET must be at least {minimum_secret_length} characters "
                f"in the {self.app_env.value} environment"
            )
        if len(self.refresh_token_pepper.get_secret_value()) < minimum_secret_length:
            raise ValueError(
                f"REFRESH_TOKEN_PEPPER must be at least {minimum_secret_length} characters "
                f"in the {self.app_env.value} environment"
            )

        if self.max_product_image_size_mb > self.max_upload_size_mb:
            raise ValueError("MAX_PRODUCT_IMAGE_SIZE_MB may not exceed MAX_UPLOAD_SIZE_MB")
        if self.max_tenant_storage_mb < self.max_product_image_size_mb:
            raise ValueError("MAX_TENANT_STORAGE_MB may not be smaller than one product image")
        if not self.allowed_media_content_types:
            raise ValueError("MEDIA_ALLOWED_CONTENT_TYPES must list at least one type")
        if not all(
            content_type.startswith("image/") for content_type in self.allowed_media_content_types
        ):
            raise ValueError("MEDIA_ALLOWED_CONTENT_TYPES accepts image types only")

        self._validate_database_url()
        self._validate_active_storage_provider()
        return self

    def _validate_database_url(self) -> None:
        if not self.database_url.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must use the postgresql+asyncpg:// driver; "
                "the server database is PostgreSQL and SQLite is not a substitute"
            )

    def _validate_active_storage_provider(self) -> None:
        """Require credentials only for the provider that is actually in use.

        A deployment that stores files on R2 must not need Cloudinary secrets to
        boot, and vice versa. This is the only place the two providers are
        treated differently, and it is configuration, not business logic.
        """
        if self.storage_provider is StorageProviderName.R2:
            missing = [
                name
                for name, value in (
                    ("R2_ENDPOINT", self.r2_endpoint),
                    ("R2_ACCESS_KEY_ID", self.r2_access_key_id),
                    ("R2_SECRET_ACCESS_KEY", self.r2_secret_access_key),
                    ("R2_BUCKET", self.r2_bucket),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"STORAGE_PROVIDER=r2 requires {', '.join(missing)}")
            # Non-empty is already guaranteed above; the local keeps the type
            # checker satisfied without an assert, which would vanish under -O.
            r2_endpoint = self.r2_endpoint or ""
            if not r2_endpoint.startswith("https://"):
                raise ValueError("R2_ENDPOINT must use https://")
            if self.r2_public_base_url and not self.r2_public_base_url.startswith("https://"):
                raise ValueError("R2_PUBLIC_BASE_URL must use https://")
        else:
            missing = [
                name
                for name, value in (
                    ("CLOUDINARY_CLOUD_NAME", self.cloudinary_cloud_name),
                    ("CLOUDINARY_API_KEY", self.cloudinary_api_key),
                    ("CLOUDINARY_API_SECRET", self.cloudinary_api_secret),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"STORAGE_PROVIDER=cloudinary requires {', '.join(missing)}")

    # ------------------------------------------------------------------
    # Derived values
    # ------------------------------------------------------------------

    @property
    def cors_allowed_origin_list(self) -> tuple[str, ...]:
        """Return the CORS allowlist as a tuple. Empty means no cross-origin access."""
        return tuple(
            origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()
        )

    @property
    def allowed_media_content_types(self) -> tuple[str, ...]:
        """Return the upload content-type allowlist."""
        return tuple(
            content_type.strip()
            for content_type in self.media_allowed_content_types.split(",")
            if content_type.strip()
        )

    @property
    def is_production(self) -> bool:
        return self.app_env is AppEnvironment.PRODUCTION

    @property
    def is_test(self) -> bool:
        return self.app_env is AppEnvironment.TEST

    @property
    def migration_database_url(self) -> str:
        """Return the URL Alembic uses.

        A pooled connection is wrong for migrations: a transaction that alters
        many objects can be routed to different backends mid-way. A direct URL is
        used when one is configured.
        """
        return self.database_migration_url or self.database_url

    def storage_limits(self) -> StorageLimits:
        """Return the provider-neutral media and quota limits."""
        mebibyte = 1024 * 1024
        return StorageLimits(
            max_upload_bytes=self.max_upload_size_mb * mebibyte,
            max_product_image_bytes=self.max_product_image_size_mb * mebibyte,
            max_image_width=self.max_product_image_width,
            max_image_height=self.max_product_image_height,
            max_images_per_product=self.max_product_images_per_product,
            max_tenant_storage_bytes=self.max_tenant_storage_mb * mebibyte,
            target_format=self.media_target_format,
            image_quality=self.media_image_quality,
            strip_metadata=self.media_strip_metadata,
            allowed_content_types=self.allowed_media_content_types,
        )

    def storage_configuration_for(
        self, provider: StorageProviderName
    ) -> R2Configuration | CloudinaryConfiguration | None:
        """Return a provider's configuration, or None when it is incomplete.

        Used by the composition root to build an adapter for *every* provider whose
        credentials are present, not only the active one: an object written before a
        provider switch stays resolvable to the provider that holds it, and answering
        that request needs that provider's adapter.

        Returning None rather than raising is deliberate. A deployment that has always
        used one provider has no credentials for the other, and that is a normal
        configuration rather than a fault; while a *missing* configuration for the
        active provider is a fault, and the caller that selects the active adapter
        raises for it.
        """
        if provider is StorageProviderName.R2:
            return self._r2_configuration() if self._r2_credentials_are_present() else None
        return (
            self._cloudinary_configuration() if self._cloudinary_credentials_are_present() else None
        )

    def _r2_credentials_are_present(self) -> bool:
        """Return True when every value an R2 adapter needs is configured."""
        return bool(
            self.r2_endpoint
            and self.r2_access_key_id
            and self.r2_secret_access_key
            and self.r2_bucket
        )

    def _cloudinary_credentials_are_present(self) -> bool:
        """Return True when every value a Cloudinary adapter needs is configured."""
        return bool(
            self.cloudinary_cloud_name and self.cloudinary_api_key and self.cloudinary_api_secret
        )

    def r2_configuration(self) -> R2Configuration:
        """Return the R2 configuration for the active provider.

        Raises when called while R2 is not the active provider, because that is a
        composition-root defect rather than a runtime condition.
        """
        if self.storage_provider is not StorageProviderName.R2:
            raise ConfigurationError(
                operation="build_storage_adapter",
                entity="storage_provider",
                detail="requested the R2 configuration while another provider is active",
            )
        if not self._r2_credentials_are_present():
            raise ConfigurationError(
                operation="build_storage_adapter",
                entity="storage_provider",
                detail="R2 configuration is incomplete",
            )
        return self._r2_configuration()

    def _r2_configuration(self) -> R2Configuration:
        """Build the R2 configuration.

        Narrows the optional fields with a local guard rather than trusting the caller's
        check: a builder that assumed its inputs were present would raise a bare
        TypeError the day somebody called it directly, and that failure names no
        setting.
        """
        endpoint = self.r2_endpoint
        access_key_id = self.r2_access_key_id
        secret_access_key = self.r2_secret_access_key
        bucket = self.r2_bucket
        if not (endpoint and access_key_id and secret_access_key and bucket):
            raise ConfigurationError(
                operation="build_storage_adapter",
                entity="storage_provider",
                detail="R2 configuration is incomplete",
            )
        return R2Configuration(
            endpoint=endpoint,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            bucket=bucket,
            region=self.r2_region,
            public_base_url=self.r2_public_base_url or None,
            request_timeout_seconds=self.r2_request_timeout_seconds,
        )

    def cloudinary_configuration(self) -> CloudinaryConfiguration:
        """Return the Cloudinary configuration for the active provider.

        Raises when it is not active, or when its credentials are missing.
        """
        if self.storage_provider is not StorageProviderName.CLOUDINARY:
            raise ConfigurationError(
                operation="build_storage_adapter",
                entity="storage_provider",
                detail="requested the Cloudinary configuration while another provider is active",
            )
        if not self._cloudinary_credentials_are_present():
            raise ConfigurationError(
                operation="build_storage_adapter",
                entity="storage_provider",
                detail="Cloudinary configuration is incomplete",
            )
        return self._cloudinary_configuration()

    def _cloudinary_configuration(self) -> CloudinaryConfiguration:
        """Build the Cloudinary configuration, narrowing the optional fields locally."""
        cloud_name = self.cloudinary_cloud_name
        api_key = self.cloudinary_api_key
        api_secret = self.cloudinary_api_secret
        if not (cloud_name and api_key and api_secret):
            raise ConfigurationError(
                operation="build_storage_adapter",
                entity="storage_provider",
                detail="Cloudinary configuration is incomplete",
            )
        return CloudinaryConfiguration(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            upload_folder=self.cloudinary_upload_folder,
            secure_delivery=self.cloudinary_secure_delivery,
            request_timeout_seconds=self.cloudinary_request_timeout_seconds,
        )

    def is_feature_enabled(self, setting_attribute: str) -> bool:
        """Return the state of one flag by its setting attribute name."""
        return bool(getattr(self, setting_attribute))

    def feature_flag_states(self) -> tuple[tuple[FeatureFlag, bool], ...]:
        """Return every declared flag with its current state, for startup logging."""
        return tuple(
            (flag, self.is_feature_enabled(flag.setting_attribute)) for flag in FEATURE_FLAGS
        )


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_settings(**overrides: Any) -> Settings:
    """Build the settings object from the environment.

    Raises `ConfigurationError` naming the offending variables when validation
    fails. Values are never echoed, because a validation failure on JWT_SECRET or
    a provider secret must not put that secret into a log line, a crash report or
    a container start message.

    Overrides exist for tests and for the composition root; in production the
    environment is the only source.
    """
    try:
        return Settings(**overrides)
    except ValidationError as validation_error:
        offending = sorted(
            {
                ".".join(str(part) for part in error["loc"]) or "unknown"
                for error in validation_error.errors()
            }
        )
        raise ConfigurationError(
            operation="load_settings",
            entity="configuration",
            detail=f"invalid or missing settings: {', '.join(offending)}",
            cause=validation_error,
        ) from validation_error
