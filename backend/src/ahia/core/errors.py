"""Error hierarchy, correlation ID and the external response envelope.

Two views of every failure, joined by a correlation ID.

Internal view (logs, traces, error objects)
    Full context: the operation, the entity and identifier where applicable, the
    layer that raised it, the correlation ID and the chained root cause. It is
    never generic. "Something went wrong" is forbidden here.

External view (HTTP response)
    An error code, a safe human-readable message and the correlation ID. It is
    never specific. No stack trace, no SQL, no file path, no hostname, no
    framework or dependency name, and never a statement about whether a user,
    email or record exists.

The bridge is the correlation ID: generated at the transport boundary, attached
to the request context, written into every log line and returned to the client.

Usage:

    raise NotFoundError(
        operation="fetch_product",
        entity="product",
        identifier=str(product_id),
        detail="no row matched (tenant_id, product_id)",
    )

The error classes are the only place HTTP status codes and external messages are
decided, and `error_handler_middleware` is the only place they become a
response.
"""

from __future__ import annotations

import contextvars
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar, Final

# ---------------------------------------------------------------------------
# Correlation ID
# ---------------------------------------------------------------------------

CORRELATION_ID_HEADER_NAME: Final[str] = "X-Correlation-ID"
CORRELATION_ID_MINIMUM_LENGTH: Final[int] = 8
CORRELATION_ID_MAXIMUM_LENGTH: Final[int] = 128
_CORRELATION_ID_ALLOWED_CHARACTERS: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._:-]+$")

_correlation_id_context: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "ahia_correlation_id",
    default=None,
)


def generate_correlation_id() -> str:
    """Return a new opaque correlation ID.

    A UUID4 without separators: 32 characters, no meaning, nothing derived from
    the request. The ID must never encode tenant, user or client information,
    because it is returned to the caller and written to logs.
    """
    return uuid.uuid4().hex


def sanitize_correlation_id(candidate: str | None) -> str | None:
    """Return a validated inbound correlation ID, or None when it is unusable.

    An inbound ID is accepted only when it matches the allowed character set and
    length bounds. Anything else is discarded and replaced, so a caller cannot
    inject control characters, newlines or an enormous value into every log line
    written for that request.
    """
    if candidate is None:
        return None
    trimmed = candidate.strip()
    if not CORRELATION_ID_MINIMUM_LENGTH <= len(trimmed) <= CORRELATION_ID_MAXIMUM_LENGTH:
        return None
    if not _CORRELATION_ID_ALLOWED_CHARACTERS.match(trimmed):
        return None
    return trimmed


def set_correlation_id(correlation_id: str) -> None:
    """Bind a correlation ID to the current context."""
    _correlation_id_context.set(correlation_id)


def clear_correlation_id() -> None:
    """Unbind the correlation ID from the current context.

    Used by worker wrappers and by test isolation. A stale identifier is worse
    than no identifier, because it makes two unrelated events look related in
    the logs.
    """
    _correlation_id_context.set(None)


def get_correlation_id() -> str | None:
    """Return the correlation ID bound to the current context, if any."""
    return _correlation_id_context.get()


def require_correlation_id() -> str:
    """Return the bound correlation ID, generating one when none is bound.

    Used by layers that may run outside a request, such as a scheduled job or a
    CLI entry point, where the correlation ID is still required for traceability.
    """
    existing = get_correlation_id()
    if existing is not None:
        return existing
    generated = generate_correlation_id()
    set_correlation_id(generated)
    return generated


@contextmanager
def correlation_context(correlation_id: str | None = None) -> Iterator[str]:
    """Bind a correlation ID for the duration of the block.

    Restores the previous value on exit, including on exception, so a worker
    reusing a thread cannot inherit a stale identifier.
    """
    token = _correlation_id_context.set(correlation_id or generate_correlation_id())
    try:
        yield _correlation_id_context.get() or ""
    finally:
        _correlation_id_context.reset(token)


# ---------------------------------------------------------------------------
# Error taxonomy
# ---------------------------------------------------------------------------


class ErrorLayer(StrEnum):
    """The layer that raised the error. Always present in the internal view."""

    ENTITY = "entity"
    SCHEMA = "schema"
    PERSISTENCE = "persistence"
    DOMAIN = "domain"
    TRANSPORT = "transport"
    INTEGRATION = "integration"
    SECURITY = "security"
    CONFIGURATION = "configuration"


@dataclass(frozen=True)
class ErrorContext:
    """Internal context attached to every error.

    Everything here is safe to log. Callers pass identifiers, never secrets, and
    never a raw request body.
    """

    operation: str
    layer: ErrorLayer
    entity: str | None = None
    identifier: str | None = None
    detail: str | None = None
    correlation_id: str | None = None
    causes: tuple[str, ...] = field(default=())

    def describe(self) -> str:
        """Render the internal view as a single structured line."""
        parts = [
            f"operation={self.operation}",
            f"layer={self.layer.value}",
        ]
        if self.entity is not None:
            parts.append(f"entity={self.entity}")
        if self.identifier is not None:
            parts.append(f"identifier={self.identifier}")
        if self.detail is not None:
            parts.append(f"detail={self.detail}")
        parts.append(f"correlation_id={self.correlation_id or require_correlation_id()}")
        if self.causes:
            parts.append("causes=[" + " <- ".join(self.causes) + "]")
        return " ".join(parts)


class AhiaError(Exception):
    """Root of every application error.

    Subclasses declare their external identity with class attributes:

    ``error_code``
        Stable, machine-readable, safe to publish.
    ``http_status``
        The HTTP status the transport layer returns.
    ``safe_message``
        The only human-readable text a client ever sees.

    A subclass never overrides the external view based on runtime values,
    because that is how internal detail leaks.
    """

    error_code: ClassVar[str] = "INTERNAL_ERROR"
    http_status: ClassVar[int] = 500
    safe_message: ClassVar[str] = "An unexpected error occurred."
    default_layer: ClassVar[ErrorLayer] = ErrorLayer.DOMAIN

    def __init__(
        self,
        *,
        operation: str,
        layer: ErrorLayer | None = None,
        entity: str | None = None,
        identifier: str | None = None,
        detail: str | None = None,
        correlation_id: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        self.context = ErrorContext(
            operation=operation,
            layer=layer or self.default_layer,
            entity=entity,
            identifier=identifier,
            detail=detail,
            correlation_id=correlation_id or get_correlation_id(),
            causes=_describe_cause_chain(cause),
        )
        super().__init__(self.context.describe())
        if cause is not None:
            self.__cause__ = cause

    def external(self) -> ExternalError:
        """Return the external view. Nothing internal crosses this boundary."""
        return ExternalError(
            code=self.error_code,
            message=self.safe_message,
            correlation_id=self.context.correlation_id or require_correlation_id(),
        )

    def with_context(
        self,
        *,
        operation: str | None = None,
        layer: ErrorLayer | None = None,
        entity: str | None = None,
        identifier: str | None = None,
        detail: str | None = None,
        correlation_id: str | None = None,
    ) -> AhiaError:
        """Return a copy carrying additional internal context.

        Used when an error crosses a layer boundary and the outer layer knows
        something the inner one did not, such as which use case was running. The
        exception type is preserved, so the transport mapping is unchanged.
        """
        return type(self)(
            operation=operation or self.context.operation,
            layer=layer or self.context.layer,
            entity=entity if entity is not None else self.context.entity,
            identifier=identifier if identifier is not None else self.context.identifier,
            detail=detail if detail is not None else self.context.detail,
            correlation_id=correlation_id or self.context.correlation_id,
        )


def _describe_cause_chain(cause: BaseException | None) -> tuple[str, ...]:
    """Render the cause chain as type names only.

    Only the exception type is kept. A provider exception message may contain a
    request URL with a credential, a signed query string or a database
    connection string, so it is never copied into the chain.
    """
    chain: list[str] = []
    current = cause
    while current is not None and len(chain) < 8:
        chain.append(type(current).__name__)
        current = current.__cause__ or (
            current.__context__ if not current.__suppress_context__ else None
        )
    return tuple(chain)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class ConfigurationError(AhiaError):
    """Configuration is missing, malformed or internally inconsistent.

    Raised at startup so a misconfigured process fails loudly instead of serving
    requests with an unsafe default.
    """

    error_code = "CONFIGURATION_ERROR"
    http_status = 500
    safe_message = "The service is not configured correctly."
    default_layer = ErrorLayer.CONFIGURATION


# ---------------------------------------------------------------------------
# Entity and schema
# ---------------------------------------------------------------------------


class EntityInvariantError(AhiaError):
    """A domain invariant was violated while constructing or mutating an entity."""

    error_code = "INVALID_REQUEST"
    http_status = 422
    safe_message = "The request contained an invalid value."
    default_layer = ErrorLayer.ENTITY


class InvalidInputError(AhiaError):
    """Request input failed validation at the transport boundary."""

    error_code = "INVALID_REQUEST"
    http_status = 422
    safe_message = "The request contained an invalid value."
    default_layer = ErrorLayer.SCHEMA


class InvalidMediaError(AhiaError):
    """An uploaded file failed media validation.

    The external message states that the file is not acceptable and nothing
    about why, because the reason is only useful to an attacker probing the
    validator.
    """

    error_code = "INVALID_MEDIA"
    http_status = 422
    safe_message = "The uploaded file is not acceptable."
    default_layer = ErrorLayer.SCHEMA


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class PersistenceError(AhiaError):
    """The persistence layer failed for a reason that is not a business outcome."""

    error_code = "INTERNAL_ERROR"
    http_status = 500
    safe_message = "An unexpected error occurred."
    default_layer = ErrorLayer.PERSISTENCE


class NotFoundError(AhiaError):
    """No matching record exists.

    Also the correct error for a cross-tenant access attempt. A caller who
    requests another tenant's record by identifier receives exactly the response
    they would receive for an identifier that does not exist, so the API never
    confirms the existence of another tenant's data.
    """

    error_code = "NOT_FOUND"
    http_status = 404
    safe_message = "The requested resource was not found."
    default_layer = ErrorLayer.PERSISTENCE


class ConflictError(AhiaError):
    """A uniqueness or state conflict prevented the write."""

    error_code = "CONFLICT"
    http_status = 409
    safe_message = "The request conflicts with the current state of the resource."
    default_layer = ErrorLayer.PERSISTENCE


# ---------------------------------------------------------------------------
# Domain
# ---------------------------------------------------------------------------


class DomainError(AhiaError):
    """A business rule rejected the operation.

    The external message is generic on purpose. The rule that was violated is
    internal context, because naming it helps an attacker map the system.
    """

    error_code = "BUSINESS_RULE_VIOLATION"
    http_status = 422
    safe_message = "The operation is not allowed in the current state."
    default_layer = ErrorLayer.DOMAIN


class StorageQuotaExceededError(AhiaError):
    """The tenant's storage quota would be exceeded by this upload.

    This one is deliberately specific externally: the caller needs to know the
    operation failed because of storage, and being told does not reveal anything
    about another tenant. The numbers stay internal.
    """

    error_code = "STORAGE_QUOTA_EXCEEDED"
    http_status = 413
    safe_message = "This workspace has reached its storage limit."
    default_layer = ErrorLayer.DOMAIN


class ResourceLimitExceededError(AhiaError):
    """A per-resource limit was reached, such as images per product."""

    error_code = "RESOURCE_LIMIT_EXCEEDED"
    http_status = 422
    safe_message = "A limit for this resource has been reached."
    default_layer = ErrorLayer.DOMAIN


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


class UnauthenticatedError(AhiaError):
    """No usable credential was presented."""

    error_code = "UNAUTHENTICATED"
    http_status = 401
    safe_message = "Authentication is required."
    default_layer = ErrorLayer.SECURITY


class AuthenticationError(AhiaError):
    """Credentials were presented and rejected.

    One code and one message for an unknown account, a wrong password and a
    disabled account. The response must not distinguish them, and the timing
    must not either, or the endpoint becomes a user-enumeration oracle.
    """

    error_code = "INVALID_CREDENTIALS"
    http_status = 401
    safe_message = "Invalid credentials."
    default_layer = ErrorLayer.SECURITY


class AuthorizationError(AhiaError):
    """The principal is authenticated but not permitted to perform the action."""

    error_code = "FORBIDDEN"
    http_status = 403
    safe_message = "You do not have permission to perform this action."
    default_layer = ErrorLayer.SECURITY


class TenantIsolationError(AhiaError):
    """A request attempted to reach another tenant's data.

    Externally indistinguishable from a missing record. Internally it is a
    security event and is always logged with the principal, the requested tenant
    and the resource.
    """

    error_code = "NOT_FOUND"
    http_status = 404
    safe_message = "The requested resource was not found."
    default_layer = ErrorLayer.SECURITY


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class RateLimitExceededError(AhiaError):
    """A rate limit was exceeded."""

    error_code = "RATE_LIMITED"
    http_status = 429
    safe_message = "Too many requests. Try again shortly."
    default_layer = ErrorLayer.TRANSPORT


# ---------------------------------------------------------------------------
# Integrations
# ---------------------------------------------------------------------------


class IntegrationError(AhiaError):
    """An external provider failed. The provider name is never published."""

    error_code = "DEPENDENCY_UNAVAILABLE"
    http_status = 503
    safe_message = "A dependent service is temporarily unavailable."
    default_layer = ErrorLayer.INTEGRATION


class DependencyTimeoutError(IntegrationError):
    """An outbound call exceeded its explicit timeout."""

    error_code = "DEPENDENCY_TIMEOUT"
    http_status = 504
    safe_message = "A dependent service did not respond in time."


class DependencyCircuitOpenError(IntegrationError):
    """A circuit breaker is open, so the call was not attempted.

    Failing fast here is the point: the dependency is already known to be
    unhealthy and piling on requests makes recovery slower.
    """

    error_code = "DEPENDENCY_UNAVAILABLE"
    http_status = 503


class StorageUnavailableError(IntegrationError):
    """The active object storage provider is unavailable."""

    error_code = "STORAGE_UNAVAILABLE"
    http_status = 503
    safe_message = "File storage is temporarily unavailable."


class DependencyBusyError(IntegrationError):
    """A dependency's concurrency limit is full.

    A typed refusal rather than an unbounded queue: when one dependency slows
    down, the rest of the process must keep serving.
    """

    error_code = "DEPENDENCY_BUSY"
    http_status = 503
    safe_message = "A dependent service is busy. Try again shortly."


class StorageOperationError(IntegrationError):
    """An object storage operation failed for a reason other than availability."""

    error_code = "STORAGE_ERROR"
    http_status = 502
    safe_message = "The file could not be stored."


# ---------------------------------------------------------------------------
# External envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExternalError:
    """The only error shape a client ever receives."""

    code: str
    message: str
    correlation_id: str

    def to_payload(self) -> dict[str, dict[str, str]]:
        """Return the response body.

        Three fields, always. Adding a fourth is how an internal identifier,
        a field name or a validation detail reaches a client.
        """
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "correlation_id": self.correlation_id,
            }
        }


def internal_error_envelope() -> ExternalError:
    """The response for an unhandled exception.

    Identical for every unexpected failure. A distinct code per internal failure
    mode would let a client map the internals of the system from the outside.
    """
    return ExternalError(
        code="INTERNAL_ERROR",
        message=AhiaError.safe_message,
        correlation_id=require_correlation_id(),
    )


# ---------------------------------------------------------------------------
# Error catalogue
# ---------------------------------------------------------------------------

_ERROR_CLASSES: Final[tuple[type[AhiaError], ...]] = (
    ConfigurationError,
    EntityInvariantError,
    InvalidInputError,
    InvalidMediaError,
    PersistenceError,
    NotFoundError,
    ConflictError,
    DomainError,
    StorageQuotaExceededError,
    ResourceLimitExceededError,
    UnauthenticatedError,
    AuthenticationError,
    AuthorizationError,
    TenantIsolationError,
    RateLimitExceededError,
    IntegrationError,
    DependencyTimeoutError,
    DependencyCircuitOpenError,
    DependencyBusyError,
    StorageUnavailableError,
    StorageOperationError,
)

#: Every external code the API can return, mapped to the status that carries it.
#: Used by tests to assert that no typed error is missing from the handler, and
#: by review to see the whole external surface at a glance.
EXTERNAL_ERROR_CATALOGUE: Final[MappingProxyType[str, int]] = MappingProxyType(
    {error_class.error_code: error_class.http_status for error_class in _ERROR_CLASSES}
)
