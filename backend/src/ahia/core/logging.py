"""Structured logging and redaction.

Two rules shape this module.

1. Redaction belongs to the logging infrastructure, not to call sites. A
   developer who has to remember to blank a field before logging it will
   eventually forget. Here, a sensitive key is redacted because of its name, and
   a sensitive value is redacted because of its shape, whatever the caller does.

2. A log line is structured data. Every record carries the correlation ID, and
   the fields a reader needs to reconstruct what happened: operation, layer,
   tenant, actor, entity. "Operation failed" is not a log line; it is a puzzle.

The logger never writes a password, a password hash, a token, a cookie, an API
key, a private key or a connection string, and it never writes a full request
body.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Mapping, MutableMapping
from datetime import UTC, datetime
from typing import Any, Final

from ahia.core.config import LogFormat, Settings
from ahia.core.errors import get_correlation_id

REDACTED_PLACEHOLDER: Final[str] = "[REDACTED]"

#: A key is sensitive when its lowercase name contains one of these fragments.
#: Fragments rather than exact names, because `db_password`, `password_hash`,
#: `X-Api-Key` and `refresh_token` must all be caught.
#: A digest in a log line is either a credential digest, which must not be
#: published, or a content checksum, which is already named `checksum` or
#: `checksum_sha256` and is not redacted by this rule.
SENSITIVE_KEY_FRAGMENTS: Final[tuple[str, ...]] = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "private_key",
    "privatekey",
    "credential",
    "session_id",
    "pepper",
    "signature",
    "access_key",
    "connection_string",
    "hash",
    "dsn",
    "otp",
    "pin",
)

#: Value shapes that are redacted wherever they appear, including inside a free
#: text message.
_SENSITIVE_VALUE_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-+/=]{8,}"), r"\1 " + REDACTED_PLACEHOLDER),
    (
        re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^:/\s]+):([^@/\s]+)@"),
        r"\1:" + REDACTED_PLACEHOLDER + "@",
    ),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED_PLACEHOLDER),
    (
        re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
        REDACTED_PLACEHOLDER,
    ),
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
        REDACTED_PLACEHOLDER,
    ),
    (re.compile(r"(?i)\b(cloudinary://)[^@\s]+@"), r"\1" + REDACTED_PLACEHOLDER + "@"),
)

#: Standard record attributes. Anything outside this set was supplied by the
#: caller through `extra=` and is emitted as a structured field.
_RESERVED_RECORD_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

_EXCEPTION_SUMMARY_MAXIMUM_LENGTH: Final[int] = 500


def is_sensitive_key(key: str) -> bool:
    """Return True when a field name indicates sensitive content.

    Hyphens and spaces are normalised to underscores first, because the same
    concept arrives as `api_key` in configuration, `X-Api-Key` in a header and
    `api key` in prose, and a redaction rule that only catches one spelling is
    decoration.
    """
    lowered = key.lower().replace("-", "_").replace(" ", "_")
    return any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS)


def redact_text(value: str) -> str:
    """Replace sensitive value shapes inside a free-text string.

    Applied to the rendered message as well as to field values, because a
    credential often arrives inside a URL or a header line that a developer
    logged as prose.
    """
    redacted = value
    for pattern, replacement in _SENSITIVE_VALUE_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_fields(value: Any, *, depth: int = 0) -> Any:
    """Return a copy of a mapping with sensitive keys and values redacted.

    Recurses through mappings and sequences so a nested configuration object or
    a dependency payload cannot smuggle a secret past a top-level check. Depth is
    bounded so a self-referential structure cannot hang a request thread.
    """
    if depth > 6:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED_PLACEHOLDER
            if is_sensitive_key(str(key))
            else redact_fields(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, list | tuple | set | frozenset):
        return [redact_fields(item, depth=depth + 1) for item in value]
    return value


class JsonLogFormatter(logging.Formatter):
    """Render one log record as one JSON object.

    Field order is stable so log lines diff cleanly when comparing two requests.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }

        correlation_id = get_correlation_id() or getattr(record, "correlation_id", None)
        if correlation_id:
            payload["correlation_id"] = correlation_id

        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRIBUTES or key.startswith("_"):
                continue
            if key == "correlation_id":
                continue
            payload[key] = REDACTED_PLACEHOLDER if is_sensitive_key(key) else redact_fields(value)

        if record.exc_info and record.exc_info[0] is not None:
            # Only the exception type is recorded by default. A provider
            # exception message can contain a URL with a credential, a signed
            # query string or a connection string.
            payload["exception_type"] = record.exc_info[0].__name__
            summary = str(record.exc_info[1]) if record.exc_info[1] is not None else ""
            if summary:
                payload["exception_summary"] = redact_text(
                    summary[:_EXCEPTION_SUMMARY_MAXIMUM_LENGTH]
                )

        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleLogFormatter(logging.Formatter):
    """Human-readable output for interactive development only.

    Redaction is identical to the JSON formatter; the difference is layout.
    """

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="seconds")
        correlation_id = get_correlation_id() or "no-correlation-id"
        parts = [
            timestamp,
            record.levelname,
            f"[{correlation_id[:12]}]",
            redact_text(record.getMessage()),
        ]

        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRIBUTES or key.startswith("_") or key == "correlation_id":
                continue
            rendered = REDACTED_PLACEHOLDER if is_sensitive_key(key) else redact_fields(value)
            parts.append(f"{key}={rendered}")

        line = " ".join(str(part) for part in parts)
        if record.exc_info and record.exc_info[0] is not None:
            line = f"{line} exception={record.exc_info[0].__name__}"
        return line


class StructuredLogger:
    """A logger that binds request context once and emits structured fields.

    Usage:

        logger = StructuredLogger(logging.getLogger("ahia.sales")).bind(
            operation="complete_sale",
            layer="service",
        )
        logger.info("sale_completed", sale_id=str(sale.identifier), item_count=3)

    Binding returns a new instance, so a bound logger can be passed down and a
    caller cannot mutate the parent's context.
    """

    __slots__ = ("_base_fields", "_logger")

    def __init__(
        self,
        logger: logging.Logger,
        base_fields: Mapping[str, Any] | None = None,
    ) -> None:
        self._logger = logger
        self._base_fields: Mapping[str, Any] = dict(base_fields or {})

    def bind(self, **fields: Any) -> StructuredLogger:
        """Return a logger carrying additional context."""
        merged = dict(self._base_fields)
        merged.update(fields)
        return StructuredLogger(self._logger, merged)

    @property
    def name(self) -> str:
        return self._logger.name

    def is_enabled_for(self, level: int) -> bool:
        return self._logger.isEnabledFor(level)

    def debug(self, event: str, **fields: Any) -> None:
        self._emit(logging.DEBUG, event, fields)

    def info(self, event: str, **fields: Any) -> None:
        self._emit(logging.INFO, event, fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._emit(logging.WARNING, event, fields)

    def error(self, event: str, **fields: Any) -> None:
        self._emit(logging.ERROR, event, fields)

    def critical(self, event: str, **fields: Any) -> None:
        self._emit(logging.CRITICAL, event, fields)

    def exception(self, event: str, error: BaseException, **fields: Any) -> None:
        """Log a failure with its exception type, at ERROR level.

        The exception summary is redacted by the formatter; the caller supplies
        the operation context that makes the line searchable.
        """
        self._emit(logging.ERROR, event, fields, exc_info=error)

    def _emit(
        self,
        level: int,
        event: str,
        fields: Mapping[str, Any],
        exc_info: BaseException | None = None,
    ) -> None:
        if not self._logger.isEnabledFor(level):
            return
        merged: MutableMapping[str, Any] = dict(self._base_fields)
        merged.update(fields)
        correlation_id = merged.pop("correlation_id", None) or get_correlation_id()
        if correlation_id:
            merged["correlation_id"] = correlation_id
        self._logger.log(level, event, extra=dict(merged), exc_info=exc_info)


def configure_logging(settings: Settings) -> None:
    """Install the root handler. Called once, from the application startup path.

    Idempotent: re-running replaces the handler rather than stacking a second
    one, which would duplicate every line.
    """
    root_logger = logging.getLogger()
    for existing_handler in list(root_logger.handlers):
        root_logger.removeHandler(existing_handler)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        JsonLogFormatter() if settings.log_format is LogFormat.JSON else ConsoleLogFormatter()
    )

    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level)

    # Access logs are emitted by the application in structured form; the default
    # uvicorn handler duplicates them in an unstructured format.
    logging.getLogger("uvicorn.access").propagate = False


def get_logger(name: str) -> StructuredLogger:
    """Return a structured logger for a module.

    `name` should be the fully qualified module name, so a log line can be traced
    back to the file that emitted it.
    """
    return StructuredLogger(logging.getLogger(name))
