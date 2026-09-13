"""Tests for the error hierarchy, correlation ID and external envelope.

The error boundary is a security boundary. These tests assert both halves of
it: the internal view carries enough context to find the cause, and the external
view carries nothing that helps an attacker.
"""

from __future__ import annotations

import pytest

from ahia.core import errors
from ahia.core.errors import (
    EXTERNAL_ERROR_CATALOGUE,
    AhiaError,
    AuthenticationError,
    AuthorizationError,
    ConfigurationError,
    ConflictError,
    DependencyCircuitOpenError,
    DependencyTimeoutError,
    DomainError,
    EntityInvariantError,
    ErrorLayer,
    ExternalError,
    IntegrationError,
    InvalidInputError,
    InvalidMediaError,
    NotFoundError,
    PersistenceError,
    RateLimitExceededError,
    ResourceLimitExceededError,
    StorageOperationError,
    StorageQuotaExceededError,
    StorageUnavailableError,
    TenantIsolationError,
    UnauthenticatedError,
    correlation_context,
    generate_correlation_id,
    get_correlation_id,
    internal_error_envelope,
    require_correlation_id,
    sanitize_correlation_id,
    set_correlation_id,
)

# ---------------------------------------------------------------------------
# Correlation ID
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_generated_correlation_id_is_opaque_and_bounded() -> None:
    correlation_id = generate_correlation_id()

    assert len(correlation_id) == 32
    assert correlation_id.isalnum()
    # Two calls never collide in practice, which is what makes the ID usable as
    # a log search key.
    assert correlation_id != generate_correlation_id()


@pytest.mark.unit
@pytest.mark.parametrize(
    "candidate",
    [
        "abc12345",
        "0123456789abcdef0123456789abcdef",
        "req-8f3a.4b2c_trace:1",
        "A" * 128,
    ],
)
def test_valid_inbound_correlation_id_is_accepted(candidate: str) -> None:
    assert sanitize_correlation_id(candidate) == candidate


@pytest.mark.unit
@pytest.mark.parametrize(
    "candidate",
    [
        None,
        "",
        "short",
        "A" * 129,
        "bad value with spaces",
        "newline\ninjected",
        "semi;colon",
        "quote'value",
        "unicode-\u00e9",
    ],
)
def test_unusable_inbound_correlation_id_is_rejected(candidate: str | None) -> None:
    """An inbound ID is attacker-controlled and must not reach a log line raw."""
    assert sanitize_correlation_id(candidate) is None


@pytest.mark.unit
def test_correlation_context_binds_and_restores() -> None:
    assert get_correlation_id() is None

    with correlation_context("bound-value-1234") as bound:
        assert bound == "bound-value-1234"
        assert get_correlation_id() == "bound-value-1234"

        with correlation_context("inner-value-5678"):
            assert get_correlation_id() == "inner-value-5678"

        assert get_correlation_id() == "bound-value-1234"

    assert get_correlation_id() is None


@pytest.mark.unit
def test_correlation_context_generates_when_not_supplied() -> None:
    with correlation_context() as bound:
        assert bound
        assert len(bound) == 32


@pytest.mark.unit
def test_require_correlation_id_generates_outside_a_request() -> None:
    assert get_correlation_id() is None

    generated = require_correlation_id()

    assert generated
    assert get_correlation_id() == generated


@pytest.mark.unit
def test_set_correlation_id_is_visible_to_readers() -> None:
    set_correlation_id("explicitly-set-1")

    assert get_correlation_id() == "explicitly-set-1"


# ---------------------------------------------------------------------------
# Internal view
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_internal_view_names_operation_layer_and_identifier() -> None:
    error = NotFoundError(
        operation="fetch_product",
        entity="product",
        identifier="8f3a-4b2c",
        detail="no row matched (tenant_id, product_id)",
    )

    description = str(error)

    assert "operation=fetch_product" in description
    assert "layer=persistence" in description
    assert "entity=product" in description
    assert "identifier=8f3a-4b2c" in description
    assert "detail=no row matched" in description
    assert "correlation_id=" in description


@pytest.mark.unit
def test_internal_view_never_says_something_went_wrong() -> None:
    """A generic internal message is a defect, not a style preference."""
    error = DomainError(operation="complete_sale", detail="inventory would go negative")

    assert "something went wrong" not in str(error).lower()
    assert "operation failed" not in str(error).lower()


@pytest.mark.unit
def test_internal_view_includes_chained_cause_types() -> None:
    root_cause = OSError("connection reset by peer at host db.internal")
    middle = RuntimeError("driver raised")
    middle.__cause__ = root_cause

    error = PersistenceError(
        operation="create_user",
        entity="user",
        cause=middle,
    )

    description = str(error)

    assert "causes=[RuntimeError <- OSError]" in description
    # The cause message may contain a hostname, a URL or a credential, so only
    # the exception type is retained.
    assert "connection reset" not in description
    assert "db.internal" not in description
    assert error.__cause__ is middle


@pytest.mark.unit
def test_with_context_preserves_type_and_merges_overrides() -> None:
    original = NotFoundError(operation="fetch_product", entity="product", identifier="abc")
    outer = original.with_context(operation="publish_storefront", detail="image lookup failed")

    assert isinstance(outer, NotFoundError)
    assert outer.context.operation == "publish_storefront"
    assert outer.context.entity == "product"
    assert outer.context.identifier == "abc"
    assert outer.context.detail == "image lookup failed"


@pytest.mark.unit
def test_correlation_id_is_captured_at_construction() -> None:
    with correlation_context("request-scoped-01"):
        error = DomainError(operation="complete_sale")

    assert error.context.correlation_id == "request-scoped-01"
    assert error.external().correlation_id == "request-scoped-01"


# ---------------------------------------------------------------------------
# External view
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("error_class", sorted(set(EXTERNAL_ERROR_CATALOGUE), key=str))
def test_every_external_code_has_a_declared_status(error_class: str) -> None:
    assert isinstance(EXTERNAL_ERROR_CATALOGUE[error_class], int)


@pytest.mark.unit
def test_external_payload_contains_exactly_three_fields() -> None:
    error = NotFoundError(operation="fetch_product", entity="product", identifier="abc")
    payload = error.external().to_payload()

    assert set(payload) == {"error"}
    assert set(payload["error"]) == {"code", "message", "correlation_id"}


@pytest.mark.unit
def test_external_view_leaks_no_internal_detail() -> None:
    """The leak test: this is the assertion the whole split exists for."""
    error = PersistenceError(
        operation="create_user",
        entity="user",
        identifier="8f3a-4b2c",
        detail="INSERT INTO users ... violated users_email_key",
        cause=ValueError("/srv/ahia/src/ahia/crud/user_crud.py line 42"),
    )

    rendered = repr(error.external().to_payload()).lower()

    for forbidden in (
        "insert into",
        "users_email_key",
        "postgres",
        "sqlalchemy",
        "/srv/",
        "file",
        "line 42",
        "traceback",
        "valueerror",
        "operation=",
        "identifier=",
    ):
        assert forbidden not in rendered, f"external payload leaked: {forbidden}"


@pytest.mark.unit
def test_unhandled_failure_envelope_is_uniform() -> None:
    envelope = internal_error_envelope()

    assert isinstance(envelope, ExternalError)
    assert envelope.code == "INTERNAL_ERROR"
    assert "unexpected" in envelope.message.lower()
    assert envelope.correlation_id


@pytest.mark.unit
def test_authentication_failures_are_indistinguishable() -> None:
    """Unknown account, wrong password and disabled account must look the same."""
    unknown_account = AuthenticationError(operation="authenticate_user", detail="no user row")
    wrong_password = AuthenticationError(operation="authenticate_user", detail="hash mismatch")
    disabled_account = AuthenticationError(operation="authenticate_user", detail="is_active false")

    payloads = [
        error.external().to_payload()["error"]
        for error in (
            unknown_account,
            wrong_password,
            disabled_account,
        )
    ]

    codes = {payload["code"] for payload in payloads}
    messages = {payload["message"] for payload in payloads}

    assert codes == {"INVALID_CREDENTIALS"}
    assert messages == {"Invalid credentials."}
    assert all("user" not in payload["message"].lower() for payload in payloads)


@pytest.mark.unit
def test_cross_tenant_denial_is_indistinguishable_from_absence() -> None:
    missing = NotFoundError(operation="fetch_product", entity="product", identifier="abc")
    cross_tenant = TenantIsolationError(
        operation="fetch_product",
        entity="product",
        identifier="abc",
        detail="membership does not cover the owning tenant",
    )

    assert missing.external().code == cross_tenant.external().code
    assert missing.external().message == cross_tenant.external().message
    assert missing.http_status == cross_tenant.http_status == 404


@pytest.mark.unit
def test_storage_quota_error_is_specific_without_revealing_numbers() -> None:
    error = StorageQuotaExceededError(
        operation="attach_product_image",
        entity="product_image",
        detail="used=524288000 limit=524288000 incoming=1048576",
    )

    external = error.external()

    assert external.code == "STORAGE_QUOTA_EXCEEDED"
    assert external.message == "This workspace has reached its storage limit."
    assert "524288000" not in external.message


@pytest.mark.unit
def test_integration_errors_never_names_the_provider() -> None:
    error = StorageUnavailableError(
        operation="upload_object",
        entity="product_image",
        detail="provider=cloudflare-r2 bucket=ahia-dev status=503",
    )

    external = error.external()

    assert "cloudflare" not in external.message.lower()
    assert "bucket" not in external.message.lower()
    assert "503" not in external.message


# ---------------------------------------------------------------------------
# Layer attribution
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error_class", "expected_layer", "expected_status"),
    [
        (ConfigurationError, ErrorLayer.CONFIGURATION, 500),
        (EntityInvariantError, ErrorLayer.ENTITY, 422),
        (InvalidInputError, ErrorLayer.SCHEMA, 422),
        (InvalidMediaError, ErrorLayer.SCHEMA, 422),
        (PersistenceError, ErrorLayer.PERSISTENCE, 500),
        (NotFoundError, ErrorLayer.PERSISTENCE, 404),
        (ConflictError, ErrorLayer.PERSISTENCE, 409),
        (DomainError, ErrorLayer.DOMAIN, 422),
        (StorageQuotaExceededError, ErrorLayer.DOMAIN, 413),
        (ResourceLimitExceededError, ErrorLayer.DOMAIN, 422),
        (UnauthenticatedError, ErrorLayer.SECURITY, 401),
        (AuthenticationError, ErrorLayer.SECURITY, 401),
        (AuthorizationError, ErrorLayer.SECURITY, 403),
        (TenantIsolationError, ErrorLayer.SECURITY, 404),
        (RateLimitExceededError, ErrorLayer.TRANSPORT, 429),
        (IntegrationError, ErrorLayer.INTEGRATION, 503),
        (DependencyTimeoutError, ErrorLayer.INTEGRATION, 504),
        (DependencyCircuitOpenError, ErrorLayer.INTEGRATION, 503),
        (StorageUnavailableError, ErrorLayer.INTEGRATION, 503),
        (StorageOperationError, ErrorLayer.INTEGRATION, 502),
    ],
)
def test_error_classes_declare_layer_and_status(
    error_class: type[AhiaError],
    expected_layer: ErrorLayer,
    expected_status: int,
) -> None:
    error = error_class(operation="test_operation")

    assert error.context.layer == expected_layer
    assert error.http_status == expected_status
    # The published catalogue must agree with the class, or the handler and the
    # documented external surface have drifted apart.
    assert EXTERNAL_ERROR_CATALOGUE[error.error_code] == expected_status


@pytest.mark.unit
def test_every_typed_error_declares_a_non_generic_safe_message() -> None:
    for error_class in errors._ERROR_CLASSES:
        assert error_class.safe_message, f"{error_class.__name__} has no safe message"
        assert error_class.safe_message.endswith("."), (
            f"{error_class.__name__} message is not a sentence"
        )
        assert error_class.error_code == error_class.error_code.upper()


@pytest.mark.unit
def test_every_typed_error_accepts_the_standard_context() -> None:
    """No error may require a bespoke constructor, or the handler cannot map it."""
    for error_class in errors._ERROR_CLASSES:
        error = error_class(
            operation="catalogue_check",
            entity="product",
            identifier="abc",
            detail="checked by the error catalogue test",
        )

        assert isinstance(error, AhiaError)
        assert error.external().correlation_id
