"""Tests for the composition root.

The container is where a wiring mistake becomes a production incident, so the
tests assert the properties that a mistake would break: that both providers can
be selected, that a configuration the runtime cannot honour stops startup, that
two containers are independent, and that the startup log answers "what was
configured" without printing a secret.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from ahia import bootstrap as bootstrap_module
from ahia.bootstrap import (
    ApplicationContainer,
    build_application_container,
    dispose_application_container,
    log_startup_configuration,
)
from ahia.core.config import (
    AppEnvironment,
    MediaTargetFormat,
    Settings,
    StorageProviderName,
)
from ahia.core.errors import ConfigurationError
from ahia.core.logging import JsonLogFormatter
from ahia.core.permissions import permissions_registry
from ahia.integrations.media import image_processor
from ahia.integrations.storage.cloudinary_client import CloudinaryStorageAdapter
from ahia.integrations.storage.r2_client import R2StorageAdapter

TEST_R2_ACCESS_KEY = "r2-access-key-for-tests"
TEST_R2_SECRET_KEY = "r2-secret-key-for-tests"
TEST_CLOUDINARY_API_KEY = "cloudinary-api-key-for-tests"
TEST_CLOUDINARY_API_SECRET = "cloudinary-api-secret-for-tests"


class RecordingHandler(logging.Handler):
    """Capture records from one logger, independently of the root configuration.

    The container calls configure_logging, which installs its own root handler
    and removes any other. A test that relied on the root handler would
    therefore see nothing, so the assertions read from a handler attached to the
    logger under test.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def capture_records(logger_name: str) -> Iterator[list[logging.LogRecord]]:
    logger = logging.getLogger(logger_name)
    handler = RecordingHandler()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def build_settings(**overrides: Any) -> Settings:
    baseline: dict[str, Any] = {
        "_env_file": None,
        "app_env": AppEnvironment.TEST,
        "database_url": "postgresql+asyncpg://ahia:secret@127.0.0.1:5432/ahia_test",
        "jwt_secret": "test-signing-secret-value-0000000001",
        "refresh_token_pepper": "test-refresh-pepper-value-00000000011",
        "storage_provider": StorageProviderName.R2,
        "r2_endpoint": "https://account.r2.cloudflarestorage.com",
        "r2_access_key_id": TEST_R2_ACCESS_KEY,
        "r2_secret_access_key": TEST_R2_SECRET_KEY,
        "r2_bucket": "ahia-test",
    }
    baseline.update(overrides)
    return Settings(**baseline)


def build_cloudinary_settings() -> Settings:
    return build_settings(
        storage_provider=StorageProviderName.CLOUDINARY,
        r2_endpoint=None,
        r2_access_key_id=None,
        r2_secret_access_key=None,
        r2_bucket=None,
        cloudinary_cloud_name="ahia-test-cloud",
        cloudinary_api_key=TEST_CLOUDINARY_API_KEY,
        cloudinary_api_secret=TEST_CLOUDINARY_API_SECRET,
    )


@pytest.mark.unit
def test_container_builds_every_dependency() -> None:
    container = build_application_container(build_settings())

    assert isinstance(container, ApplicationContainer)
    assert container.storage.provider_name == "r2"
    assert isinstance(container.storage, R2StorageAdapter)
    assert container.media.target_format == "webp"
    assert container.storage_quota_service.quota_bytes > 0
    assert container.token_service is not None
    assert container.password_hasher.minimum_length >= 8


@pytest.mark.unit
def test_switching_the_provider_changes_only_the_adapter() -> None:
    r2_container = build_application_container(build_settings())
    cloudinary_container = build_application_container(build_cloudinary_settings())

    assert isinstance(r2_container.storage, R2StorageAdapter)
    assert isinstance(cloudinary_container.storage, CloudinaryStorageAdapter)
    # Everything else is identical, which is what makes the switch a
    # configuration change rather than a code change.
    assert r2_container.media.target_format == cloudinary_container.media.target_format
    assert (
        r2_container.storage_quota_service.quota_bytes
        == cloudinary_container.storage_quota_service.quota_bytes
    )


@pytest.mark.unit
def test_storage_policy_belongs_to_the_active_provider() -> None:
    container = build_application_container(build_cloudinary_settings())

    assert container.storage_policy.dependency_name == "cloudinary"


@pytest.mark.unit
def test_two_containers_are_independent() -> None:
    """No module-level singleton state: two containers never share an object."""
    first = build_application_container(build_settings())
    second = build_application_container(build_settings())

    assert first.database is not second.database
    assert first.storage is not second.storage
    assert first.storage_policy.breaker is not second.storage_policy.breaker


@pytest.mark.unit
def test_unencodable_target_format_stops_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configuration the runtime cannot honour must fail before it serves."""
    monkeypatch.setattr(image_processor, "_encoder_is_available", lambda feature: False)

    with pytest.raises(ConfigurationError) as captured:
        build_application_container(build_settings(media_target_format=MediaTargetFormat.AVIF))

    assert "MEDIA_TARGET_FORMAT" in str(captured.value)


@pytest.mark.unit
def test_invalid_permission_registry_stops_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_validate() -> None:
        raise ValueError("role references an unknown permission")

    monkeypatch.setattr(permissions_registry, "validate_registry", broken_validate)
    monkeypatch.setattr(bootstrap_module, "validate_registry", broken_validate)

    with pytest.raises(ValueError, match="unknown permission"):
        build_application_container(build_settings())


@pytest.mark.asyncio
@pytest.mark.unit
async def test_disposal_is_safe_and_idempotent() -> None:
    container = build_application_container(build_settings())

    await dispose_application_container(container)
    await dispose_application_container(container)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_disposal_continues_after_a_failing_resource() -> None:
    """A shutdown path that raises leaves the process worse than one that reports."""
    container = build_application_container(build_settings())

    class ExplodingStorage:
        provider_name = "exploding"

        async def close(self) -> None:
            raise RuntimeError("provider shutdown failed")

    container.storage = ExplodingStorage()  # type: ignore[assignment]

    await dispose_application_container(container)


@pytest.mark.unit
def test_startup_log_answers_what_was_configured() -> None:
    container = build_application_container(build_settings(feature_offline_sync=True))

    with capture_records("ahia.core.container") as records:
        log_startup_configuration(container.settings, container)

    events = [record.getMessage() for record in records]

    assert "application_starting" in events
    assert events.count("feature_flag") == len(container.settings.feature_flag_states())
    assert "storage_policy_configured" in events

    flag_states = {
        record.flag: record.enabled for record in records if record.getMessage() == "feature_flag"
    }
    assert flag_states["FEATURE_OFFLINE_SYNC"] == "true"
    assert flag_states["FEATURE_AI_INSIGHTS"] == "false"


@pytest.mark.unit
def test_startup_log_contains_no_credential() -> None:
    container = build_application_container(build_settings())

    with capture_records("ahia.core.container") as records:
        log_startup_configuration(container.settings, container)

    rendered = "\n".join(JsonLogFormatter().format(record) for record in records)

    assert TEST_R2_SECRET_KEY not in rendered
    assert TEST_R2_ACCESS_KEY not in rendered
    assert container.settings.jwt_secret.get_secret_value() not in rendered
    assert "ahia:secret@" not in rendered


@pytest.mark.unit
def test_cloudinary_startup_log_contains_no_credential() -> None:
    container = build_application_container(build_cloudinary_settings())

    with capture_records("ahia.core.container") as records:
        log_startup_configuration(container.settings, container)

    rendered = "\n".join(JsonLogFormatter().format(record) for record in records)

    assert TEST_CLOUDINARY_API_SECRET not in rendered
    assert TEST_CLOUDINARY_API_KEY not in rendered
