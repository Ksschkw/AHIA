"""Tests for the typed configuration and the feature flag registry.

Configuration is security-relevant: a permissive default in production is a
vulnerability, and a secret printed in a validation error is a leak. These tests
assert the safe behaviour, not just the parsing.
"""

from __future__ import annotations

from typing import Any

import pytest

from ahia.core.config import (
    FEATURE_FLAGS,
    FORBIDDEN_FLAG_FRAGMENTS,
    AppEnvironment,
    CloudinaryConfiguration,
    LogFormat,
    MediaTargetFormat,
    R2Configuration,
    Settings,
    StorageProviderName,
    load_settings,
)
from ahia.core.errors import ConfigurationError

VALID_DATABASE_URL = "postgresql+asyncpg://ahia:secret@127.0.0.1:5432/ahia_test"
VALID_JWT_SECRET = "development-jwt-secret-value-0001"
VALID_REFRESH_PEPPER = "development-pepper-value-000001"


def build_settings(**overrides: Any) -> Settings:
    """Build settings with a valid development baseline.

    `_env_file=None` keeps a developer's local .env out of the test result, and
    explicit keyword arguments take precedence over the process environment so
    the suite behaves the same under `make check` as under a bare pytest run.
    """
    baseline: dict[str, Any] = {
        "_env_file": None,
        "app_env": AppEnvironment.TEST,
        "database_url": VALID_DATABASE_URL,
        "jwt_secret": VALID_JWT_SECRET,
        "refresh_token_pepper": VALID_REFRESH_PEPPER,
        "storage_provider": StorageProviderName.R2,
        "r2_endpoint": "https://account.r2.cloudflarestorage.com",
        "r2_access_key_id": "r2-access-key",
        "r2_secret_access_key": "r2-secret-key",
        "r2_bucket": "ahia-test",
    }
    baseline.update(overrides)
    return Settings(**baseline)


# ---------------------------------------------------------------------------
# Baseline and database
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_development_baseline_loads() -> None:
    settings = build_settings()

    assert settings.app_env is AppEnvironment.TEST
    assert settings.is_test
    assert not settings.is_production
    assert settings.storage_provider is StorageProviderName.R2


@pytest.mark.unit
def test_missing_database_url_names_the_variable_without_its_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in (
        "DATABASE_URL",
        "JWT_SECRET",
        "REFRESH_TOKEN_PEPPER",
        "R2_ENDPOINT",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET",
        "STORAGE_PROVIDER",
        "APP_ENV",
    ):
        monkeypatch.delenv(variable, raising=False)

    with pytest.raises(ConfigurationError) as captured:
        load_settings(_env_file=None)

    assert "database_url" in str(captured.value)
    assert VALID_DATABASE_URL not in str(captured.value)


@pytest.mark.unit
def test_sqlite_database_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="postgresql\\+asyncpg"):
        build_settings(database_url="sqlite+aiosqlite:///./ahia.db")


@pytest.mark.unit
def test_migration_url_falls_back_to_the_application_url() -> None:
    settings = build_settings()

    assert settings.migration_database_url == VALID_DATABASE_URL


@pytest.mark.unit
def test_migration_url_can_be_a_direct_connection() -> None:
    direct_url = "postgresql+asyncpg://ahia:secret@direct.neon.tech:5432/ahia"

    settings = build_settings(database_migration_url=direct_url)

    assert settings.migration_database_url == direct_url


# ---------------------------------------------------------------------------
# Production hardening
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("overrides", "expected_fragment"),
    [
        ({"log_format": LogFormat.CONSOLE}, "LOG_FORMAT"),
        ({"database_require_ssl": False}, "DATABASE_REQUIRE_SSL"),
        ({"log_level": "DEBUG"}, "LOG_LEVEL"),
        ({"cors_allowed_origins": "*"}, "CORS"),
    ],
)
def test_production_rejects_unsafe_settings(
    overrides: dict[str, Any], expected_fragment: str
) -> None:
    production_baseline: dict[str, Any] = {
        "app_env": AppEnvironment.PRODUCTION,
        "log_format": LogFormat.JSON,
        "database_require_ssl": True,
        "log_level": "INFO",
        "cors_allowed_origins": "https://app.ahia.app",
        "jwt_secret": "p" * 48,
        "refresh_token_pepper": "q" * 48,
    }
    production_baseline.update(overrides)

    with pytest.raises(ValueError, match=expected_fragment):
        build_settings(**production_baseline)


@pytest.mark.unit
def test_production_accepts_a_hardened_configuration() -> None:
    settings = build_settings(
        app_env=AppEnvironment.PRODUCTION,
        log_format=LogFormat.JSON,
        database_require_ssl=True,
        cors_allowed_origins="https://app.ahia.app,https://ahia.app",
        jwt_secret="p" * 48,
        refresh_token_pepper="q" * 48,
    )

    assert settings.is_production
    assert settings.cors_allowed_origin_list == ("https://app.ahia.app", "https://ahia.app")


@pytest.mark.unit
def test_short_signing_secret_is_rejected_in_production() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        build_settings(
            app_env=AppEnvironment.PRODUCTION,
            log_format=LogFormat.JSON,
            database_require_ssl=True,
            jwt_secret="too-short",
            refresh_token_pepper="q" * 48,
        )


@pytest.mark.unit
def test_short_signing_secret_is_rejected_in_development_too() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        build_settings(jwt_secret="tiny")


@pytest.mark.unit
@pytest.mark.parametrize("algorithm", ["none", "RS256", "ES256", "HS255"])
def test_jwt_algorithm_allowlist(algorithm: str) -> None:
    with pytest.raises(ValueError, match="jwt algorithm"):
        build_settings(jwt_algorithm=algorithm)


# ---------------------------------------------------------------------------
# Storage provider selection
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_r2_is_the_default_provider() -> None:
    settings = build_settings()

    assert settings.storage_provider is StorageProviderName.R2


@pytest.mark.unit
def test_cloudinary_selectable_without_any_r2_credentials() -> None:
    """The inactive provider's credentials must not be required to boot."""
    settings = build_settings(
        storage_provider=StorageProviderName.CLOUDINARY,
        cloudinary_cloud_name="ahia-test-cloud",
        cloudinary_api_key="cloudinary-key",
        cloudinary_api_secret="cloudinary-secret",
        r2_endpoint=None,
        r2_access_key_id=None,
        r2_secret_access_key=None,
        r2_bucket=None,
    )

    assert settings.storage_provider is StorageProviderName.CLOUDINARY
    configuration = settings.cloudinary_configuration()
    assert isinstance(configuration, CloudinaryConfiguration)
    assert configuration.cloud_name == "ahia-test-cloud"
    assert configuration.secure_delivery is True


@pytest.mark.unit
def test_r2_selectable_without_any_cloudinary_credentials() -> None:
    settings = build_settings(
        storage_provider=StorageProviderName.R2,
        cloudinary_cloud_name=None,
        cloudinary_api_key=None,
        cloudinary_api_secret=None,
    )

    configuration = settings.r2_configuration()
    assert isinstance(configuration, R2Configuration)
    assert configuration.bucket == "ahia-test"


@pytest.mark.unit
def test_active_provider_with_missing_credentials_fails_loudly() -> None:
    with pytest.raises(ValueError, match="CLOUDINARY_API_SECRET"):
        build_settings(
            storage_provider=StorageProviderName.CLOUDINARY,
            cloudinary_cloud_name="ahia-test-cloud",
            cloudinary_api_key="cloudinary-key",
            cloudinary_api_secret=None,
        )


@pytest.mark.unit
def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="storage_provider"):
        build_settings(storage_provider="s3-bucket-on-a-laptop")


@pytest.mark.unit
def test_r2_endpoint_must_use_tls() -> None:
    with pytest.raises(ValueError, match="https"):
        build_settings(r2_endpoint="http://account.r2.cloudflarestorage.com")


@pytest.mark.unit
def test_requesting_the_inactive_provider_configuration_is_a_defect() -> None:
    settings = build_settings(storage_provider=StorageProviderName.R2)

    with pytest.raises(ConfigurationError) as captured:
        settings.cloudinary_configuration()

    assert "cloudinary" in str(captured.value).lower() or "provider" in str(captured.value)


@pytest.mark.unit
def test_provider_descriptions_never_contain_secrets() -> None:
    r2_configuration = build_settings().r2_configuration()
    cloudinary_configuration = build_settings(
        storage_provider=StorageProviderName.CLOUDINARY,
        cloudinary_cloud_name="ahia-cloud",
        cloudinary_api_key="cloudinary-key-value",
        cloudinary_api_secret="cloudinary-secret-value",
    ).cloudinary_configuration()

    r2_description = repr(r2_configuration.describe())
    cloudinary_description = repr(cloudinary_configuration.describe())

    assert "r2-secret-key" not in r2_description
    assert "r2-access-key" not in r2_description
    assert "cloudinary-secret-value" not in cloudinary_description
    assert "cloudinary-key-value" not in cloudinary_description
    # The endpoint host is useful operationally; the full URL with its path is not
    # logged.
    assert r2_description.count("account.r2.cloudflarestorage.com") == 1


@pytest.mark.unit
def test_settings_repr_hides_secret_values() -> None:
    settings = build_settings()

    rendered = repr(settings)

    assert "r2-secret-key" not in rendered
    assert VALID_JWT_SECRET not in rendered
    assert VALID_REFRESH_PEPPER not in rendered


# ---------------------------------------------------------------------------
# Media and quota limits
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_storage_limits_convert_megabytes_to_bytes() -> None:
    settings = build_settings(
        max_upload_size_mb=5,
        max_product_image_size_mb=5,
        max_tenant_storage_mb=500,
        max_product_image_width=2000,
        max_product_image_height=2000,
        media_target_format=MediaTargetFormat.WEBP,
    )

    limits = settings.storage_limits()

    assert limits.max_upload_bytes == 5 * 1024 * 1024
    assert limits.max_product_image_bytes == 5 * 1024 * 1024
    assert limits.max_tenant_storage_bytes == 500 * 1024 * 1024
    assert limits.max_image_width == 2000
    assert limits.target_format is MediaTargetFormat.WEBP


@pytest.mark.unit
def test_product_image_limit_may_not_exceed_the_absolute_upload_limit() -> None:
    with pytest.raises(ValueError, match="MAX_PRODUCT_IMAGE_SIZE_MB"):
        build_settings(max_upload_size_mb=2, max_product_image_size_mb=5)


@pytest.mark.unit
def test_tenant_quota_must_fit_at_least_one_image() -> None:
    with pytest.raises(ValueError, match="MAX_TENANT_STORAGE_MB"):
        build_settings(max_product_image_size_mb=5, max_tenant_storage_mb=1)


@pytest.mark.unit
def test_allowed_content_types_must_be_images() -> None:
    with pytest.raises(ValueError, match="image types only"):
        build_settings(media_allowed_content_types="image/png,application/pdf")


@pytest.mark.unit
def test_empty_allowed_content_types_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one type"):
        build_settings(media_allowed_content_types=" , ")


@pytest.mark.unit
def test_image_quality_bounds() -> None:
    with pytest.raises(ValueError):
        build_settings(media_image_quality=0)

    with pytest.raises(ValueError):
        build_settings(media_image_quality=101)


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_security_control_is_flag_gated() -> None:
    """The hard rule: a flag that can disable a security control is a backdoor."""
    for flag in FEATURE_FLAGS:
        for fragment in FORBIDDEN_FLAG_FRAGMENTS:
            assert fragment not in flag.environment_variable, (
                f"{flag.environment_variable} looks like a security control"
            )


@pytest.mark.unit
def test_every_flag_is_declared_with_metadata() -> None:
    for flag in FEATURE_FLAGS:
        assert flag.environment_variable.startswith("FEATURE_")
        assert flag.description
        assert flag.date_added
        assert flag.removal_condition
        assert isinstance(flag.default, bool)


@pytest.mark.unit
def test_every_declared_flag_exists_on_settings() -> None:
    settings = build_settings()

    for flag in FEATURE_FLAGS:
        assert hasattr(settings, flag.setting_attribute), (
            f"{flag.environment_variable} is declared but {flag.setting_attribute} is missing"
        )


@pytest.mark.unit
def test_flag_defaults_are_off_for_unstable_features() -> None:
    settings = build_settings()

    for flag, enabled in settings.feature_flag_states():
        assert enabled is flag.default
        assert enabled is False, f"{flag.environment_variable} should default off"


@pytest.mark.unit
def test_flag_states_reflect_the_environment() -> None:
    settings = build_settings(feature_offline_sync=True, feature_ai_insights=True)

    states = dict(settings.feature_flag_states())

    assert settings.is_feature_enabled("feature_offline_sync") is True
    assert settings.is_feature_enabled("feature_ai_insights") is True
    assert any(
        flag.environment_variable == "FEATURE_OFFLINE_SYNC" and enabled
        for flag, enabled in states.items()
    )


@pytest.mark.unit
def test_no_media_flag_replaces_provider_configuration() -> None:
    """The provider is configuration, not a flag: switching is not a release."""
    settings = build_settings(
        storage_provider=StorageProviderName.CLOUDINARY,
        cloudinary_cloud_name="c",
        cloudinary_api_key="k",
        cloudinary_api_secret="s",
    )

    assert settings.storage_provider is StorageProviderName.CLOUDINARY
    assert not hasattr(settings, "feature_use_cloudinary")


# ---------------------------------------------------------------------------
# The country code, which five services used to work around locally
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_country_code_carries_its_plus() -> None:
    """The canonicaliser requires a plus, so the setting must provide one.

    It did not, and every service except the newest prefixed it locally - which meant the bug lived
    in
    the one place nobody was working around. `08029876543` became `2348029876543`: a number with no
    way
    to tell a country code from a national prefix, and a customer who could never be matched to it.
    """
    for written in ("234", "+234", " 234 "):
        assert (
            build_settings(default_phone_country_code=written).default_phone_country_code == "+234"
        )
