"""Tests for structured logging and redaction.

Redaction is a security control, so the tests are written the way an attacker
would probe it: nested structures, unusual key casing, secrets embedded in free
text, and secrets arriving inside an exception message.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from ahia.core.config import AppEnvironment, LogFormat, Settings, StorageProviderName
from ahia.core.errors import AhiaError, correlation_context
from ahia.core.logging import (
    REDACTED_PLACEHOLDER,
    ConsoleLogFormatter,
    JsonLogFormatter,
    StructuredLogger,
    configure_logging,
    get_logger,
    is_sensitive_key,
    redact_fields,
    redact_text,
)

SECRET_VALUE = "super-secret-value-that-must-never-appear"


def build_settings(**overrides: Any) -> Settings:
    baseline: dict[str, Any] = {
        "_env_file": None,
        "app_env": AppEnvironment.TEST,
        "database_url": "postgresql+asyncpg://ahia:secret@127.0.0.1:5432/ahia_test",
        "jwt_secret": "development-jwt-secret-value-0001",
        "refresh_token_pepper": "development-pepper-value-000001",
        "storage_provider": StorageProviderName.R2,
        "r2_endpoint": "https://account.r2.cloudflarestorage.com",
        "r2_access_key_id": "r2-access-key",
        "r2_secret_access_key": "r2-secret-key",
        "r2_bucket": "ahia-test",
    }
    baseline.update(overrides)
    return Settings(**baseline)


# ---------------------------------------------------------------------------
# Key-based redaction
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "key",
    [
        "password",
        "password_hash",
        "PASSWORD",
        "db_password",
        "api_key",
        "X-Api-Key",
        "authorization",
        "refresh_token",
        "access_token",
        "session_id",
        "client_secret",
        "refresh_token_pepper",
        "private_key",
        "aws_access_key_id",
        "dsn",
        "connection_string",
        "otp",
    ],
)
def test_sensitive_keys_are_detected(key: str) -> None:
    assert is_sensitive_key(key)


@pytest.mark.unit
@pytest.mark.parametrize("key", ["tenant_id", "actor_id", "entity", "product_id", "size_bytes"])
def test_ordinary_keys_are_not_redacted(key: str) -> None:
    assert not is_sensitive_key(key)


@pytest.mark.unit
def test_sensitive_values_are_redacted_by_key() -> None:
    redacted = redact_fields({"password": SECRET_VALUE, "tenant_id": "abc"})

    assert redacted == {"password": REDACTED_PLACEHOLDER, "tenant_id": "abc"}


@pytest.mark.unit
def test_nested_structures_are_redacted() -> None:
    payload = {
        "storage": {
            "provider": "r2",
            "access_key_id": SECRET_VALUE,
            "region": "auto",
        },
        "attempts": [{"refresh_token": SECRET_VALUE}],
    }

    redacted = redact_fields(payload)

    assert redacted["storage"]["access_key_id"] == REDACTED_PLACEHOLDER
    assert redacted["storage"]["region"] == "auto"
    assert redacted["attempts"][0]["refresh_token"] == REDACTED_PLACEHOLDER
    assert SECRET_VALUE not in json.dumps(redacted)


@pytest.mark.unit
def test_a_mapping_whose_name_is_sensitive_is_redacted_as_a_whole() -> None:
    """When the container is named `credentials`, nothing inside it is emitted."""
    redacted = redact_fields({"provider": "cloudinary", "credentials": {"cloud_name": "ahia"}})

    assert redacted["credentials"] == REDACTED_PLACEHOLDER
    assert redacted["provider"] == "cloudinary"


@pytest.mark.unit
def test_deeply_nested_structure_is_truncated_rather_than_followed_forever() -> None:
    payload: dict[str, Any] = {}
    current = payload
    for _ in range(20):
        nested: dict[str, Any] = {}
        current["child"] = nested
        current = nested

    redacted = redact_fields(payload)

    assert "TRUNCATED" in json.dumps(redacted)


# ---------------------------------------------------------------------------
# Value-based redaction
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "text",
    [
        "Authorization: Bearer abcdefghijklmnop",
        "bearer abcdefghijklmnopqrst",
        "postgresql+asyncpg://ahia:sup3rsecret@db.internal:5432/ahia",
        "redis://default:sup3rsecret@cache.internal:6379/0",
        "AKIAIOSFODNN7EXAMPLE1",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        "cloudinary://123456789:abcdefghijklmnop@ahia-cloud",
    ],
)
def test_sensitive_value_shapes_are_redacted_in_free_text(text: str) -> None:
    assert SECRET_VALUE not in redact_text(text)
    assert "sup3rsecret" not in redact_text(text)
    assert "abcdefghijklmnop" not in redact_text(text)


@pytest.mark.unit
def test_private_key_block_is_redacted() -> None:
    block = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----"

    assert "MIIEowIBAAKCAQEA" not in redact_text(block)


@pytest.mark.unit
def test_ordinary_text_is_untouched() -> None:
    message = "sale_completed tenant_id=8f3a product_id=4b2c total=45000 NGN"

    assert redact_text(message) == message


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def emit_record(
    formatter: logging.Formatter,
    message: str,
    fields: dict[str, Any] | None = None,
    exc_info: BaseException | None = None,
) -> str:
    record = logging.LogRecord(
        name="ahia.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    for key, value in (fields or {}).items():
        setattr(record, key, value)
    if exc_info is not None:
        record.exc_info = (type(exc_info), exc_info, exc_info.__traceback__)
    return formatter.format(record)


@pytest.mark.unit
def test_json_record_is_parseable_and_carries_the_correlation_id() -> None:
    with correlation_context("correlation-abc-123"):
        rendered = emit_record(JsonLogFormatter(), "sale_completed", {"sale_id": "8f3a"})

    payload = json.loads(rendered)

    assert payload["level"] == "INFO"
    assert payload["message"] == "sale_completed"
    assert payload["correlation_id"] == "correlation-abc-123"
    assert payload["sale_id"] == "8f3a"
    assert payload["timestamp"].endswith("+00:00")


@pytest.mark.unit
def test_json_record_redacts_sensitive_fields() -> None:
    rendered = emit_record(
        JsonLogFormatter(),
        "login_attempt",
        {"password": SECRET_VALUE, "tenant_id": "abc"},
    )

    payload = json.loads(rendered)

    assert payload["password"] == REDACTED_PLACEHOLDER
    assert payload["tenant_id"] == "abc"
    assert SECRET_VALUE not in rendered


@pytest.mark.unit
def test_json_record_redacts_a_secret_inside_the_message() -> None:
    rendered = emit_record(
        JsonLogFormatter(),
        "storage_failed url=postgresql://user:sup3rsecret@db.internal/ahia",
    )

    assert "sup3rsecret" not in rendered


@pytest.mark.unit
def test_exception_records_only_the_type_and_a_redacted_summary() -> None:
    error = RuntimeError("upload failed for https://key:sup3rsecret@r2.example.com/bucket")

    rendered = emit_record(JsonLogFormatter(), "upload_failed", exc_info=error)
    payload = json.loads(rendered)

    assert payload["exception_type"] == "RuntimeError"
    assert "sup3rsecret" not in rendered


@pytest.mark.unit
def test_console_formatter_redacts_the_same_way() -> None:
    rendered = emit_record(
        ConsoleLogFormatter(),
        "login_attempt",
        {"password": SECRET_VALUE, "tenant_id": "abc"},
    )

    assert SECRET_VALUE not in rendered
    assert REDACTED_PLACEHOLDER in rendered
    assert "tenant_id=abc" in rendered


@pytest.mark.unit
def test_large_binary_value_is_summarised_not_dumped() -> None:
    rendered = emit_record(JsonLogFormatter(), "upload", {"payload": b"\x00" * 4096})
    payload = json.loads(rendered)

    assert payload["payload"] == "<4096 bytes>"


# ---------------------------------------------------------------------------
# Structured logger
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_logger_binds_context_and_emits_fields(caplog: pytest.LogCaptureFixture) -> None:
    logger = get_logger("ahia.test").bind(operation="complete_sale", layer="service")

    with caplog.at_level(logging.INFO):
        logger.info("sale_completed", sale_id="8f3a")

    record = caplog.records[0]
    assert record.operation == "complete_sale"
    assert record.layer == "service"
    assert record.sale_id == "8f3a"
    assert record.getMessage() == "sale_completed"


@pytest.mark.unit
def test_bind_returns_a_new_logger_and_does_not_mutate_the_parent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    parent = get_logger("ahia.test").bind(operation="list_products")
    child = parent.bind(tenant_id="tenant-1")

    with caplog.at_level(logging.INFO):
        parent.info("parent_event")
        child.info("child_event")

    assert not hasattr(caplog.records[0], "tenant_id")
    assert caplog.records[1].tenant_id == "tenant-1"


@pytest.mark.unit
def test_logger_attaches_the_ambient_correlation_id(caplog: pytest.LogCaptureFixture) -> None:
    logger = get_logger("ahia.test")

    with correlation_context("ambient-correlation"), caplog.at_level(logging.INFO):
        logger.info("event")

    assert caplog.records[0].correlation_id == "ambient-correlation"


@pytest.mark.unit
def test_explicit_correlation_id_overrides_the_ambient_one(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = get_logger("ahia.test")

    with correlation_context("ambient-correlation"), caplog.at_level(logging.INFO):
        logger.info("event", correlation_id="explicit-correlation")

    assert caplog.records[0].correlation_id == "explicit-correlation"


@pytest.mark.unit
def test_logger_exception_includes_the_error(caplog: pytest.LogCaptureFixture) -> None:
    logger = get_logger("ahia.test")
    error = AhiaError(operation="complete_sale")

    with caplog.at_level(logging.ERROR):
        logger.exception("sale_failed", error=error, sale_id="8f3a")

    assert caplog.records[0].exc_info is not None
    assert caplog.records[0].sale_id == "8f3a"


@pytest.mark.unit
def test_disabled_level_does_not_format(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = StructuredLogger(logging.getLogger("ahia.test"))

    with caplog.at_level(logging.WARNING):
        logger.debug("ignored_event")

    assert caplog.records == []


# ---------------------------------------------------------------------------
# Configuration of the root handler
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_configure_logging_installs_exactly_one_handler() -> None:
    root_logger = logging.getLogger()
    configure_logging(build_settings(log_format=LogFormat.JSON))
    configure_logging(build_settings(log_format=LogFormat.JSON))

    try:
        assert len(root_logger.handlers) == 1
        assert isinstance(root_logger.handlers[0].formatter, JsonLogFormatter)
    finally:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
        root_logger.setLevel(logging.WARNING)


@pytest.mark.unit
def test_configure_logging_honours_console_format_in_development() -> None:
    root_logger = logging.getLogger()
    configure_logging(build_settings(log_format=LogFormat.CONSOLE, log_level="DEBUG"))

    try:
        assert isinstance(root_logger.handlers[0].formatter, ConsoleLogFormatter)
        assert root_logger.level == logging.DEBUG
    finally:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
        root_logger.setLevel(logging.WARNING)
