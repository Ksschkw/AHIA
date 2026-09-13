"""Tests for the security primitives.

These tests assert the properties that matter when the code is wrong in a way
that still looks like it works: that a tampered token is rejected, that a
truncated valid token is rejected, that the algorithm cannot be chosen by the
attacker, that a refresh-token digest does not equal its plaintext, and that
nothing sensitive reaches a log line.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from ahia.core.errors import AuthenticationError, ConfigurationError, UnauthenticatedError
from ahia.core.logging import JsonLogFormatter
from ahia.core.security import (
    PasswordHasher,
    TokenService,
    constant_time_equals,
    current_correlation_id_for_security_event,
    fingerprint_for_log,
)

TEST_SIGNING_SECRET = "test-signing-secret-value-0000000001"
TEST_REFRESH_PEPPER = "test-refresh-pepper-value-00000000001"


def build_hasher(**overrides: int) -> PasswordHasher:
    parameters = {
        "time_cost": 1,
        "memory_cost_kib": 8_192,
        "parallelism": 1,
        "minimum_length": 8,
    }
    parameters.update(overrides)
    return PasswordHasher(**parameters)


def build_token_service(**overrides: object) -> TokenService:
    parameters: dict[str, object] = {
        "secret": TEST_SIGNING_SECRET,
        "algorithm": "HS256",
        "issuer": "ahia-api",
        "audience": "ahia-clients",
        "access_token_ttl_minutes": 15,
        "refresh_token_pepper": TEST_REFRESH_PEPPER,
        "public_token_bytes": 24,
    }
    parameters.update(overrides)
    return TokenService(**parameters)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_password_hash_verifies_and_is_not_the_plaintext() -> None:
    hasher = build_hasher()
    password = "correct horse battery staple"

    password_hash = hasher.hash_password(password)

    assert password not in password_hash
    assert password_hash.startswith("$argon2id$")
    assert hasher.verify_password(password, password_hash) is True


@pytest.mark.unit
def test_wrong_password_is_rejected() -> None:
    hasher = build_hasher()
    password_hash = hasher.hash_password("correct horse battery staple")

    assert hasher.verify_password("wrong horse battery staple", password_hash) is False


@pytest.mark.unit
def test_corrupt_hash_is_rejected_without_raising() -> None:
    """A malformed stored hash must not become a 500, and must not authenticate."""
    hasher = build_hasher()

    assert hasher.verify_password("anything", "not-a-valid-argon2-hash") is False
    assert hasher.verify_password("anything", "") is False


@pytest.mark.unit
def test_the_same_password_hashes_differently_every_time() -> None:
    hasher = build_hasher()
    password = "correct horse battery staple"

    first = hasher.hash_password(password)
    second = hasher.hash_password(password)

    assert first != second, "a shared salt would make one rainbow table worth it"


@pytest.mark.unit
def test_short_password_fails_the_strength_policy() -> None:
    hasher = build_hasher(minimum_length=12)

    with pytest.raises(AuthenticationError) as captured:
        hasher.validate_password_strength("short")

    assert "configured minimum of 12" in str(captured.value)
    # The external message never states the policy, which would turn the
    # endpoint into a rule oracle.
    assert "12" not in captured.value.external().message


@pytest.mark.unit
def test_rehash_is_reported_when_cost_parameters_rise() -> None:
    cheap_hasher = build_hasher(time_cost=1, memory_cost_kib=8_192)
    password_hash = cheap_hasher.hash_password("correct horse battery staple")

    strict_hasher = build_hasher(time_cost=2, memory_cost_kib=16_384)

    assert strict_hasher.needs_rehash(password_hash) is True
    assert cheap_hasher.needs_rehash(password_hash) is False


# ---------------------------------------------------------------------------
# Access tokens
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_access_token_round_trip() -> None:
    service = build_token_service()

    token, issued_claims = service.issue_access_token(subject="user-123")
    claims = service.decode_access_token(token)

    assert claims.subject == "user-123"
    assert claims.token_identifier == issued_claims.token_identifier
    assert claims.issuer == "ahia-api"
    assert claims.audience == "ahia-clients"
    assert claims.expires_at > claims.issued_at


@pytest.mark.unit
def test_tampered_token_is_rejected() -> None:
    service = build_token_service()
    token, _ = service.issue_access_token(subject="user-123")
    header, payload, signature = token.split(".")

    tampered = f"{header}.{payload[:-4]}AAAA.{signature}"

    with pytest.raises(UnauthenticatedError):
        service.decode_access_token(tampered)


@pytest.mark.unit
def test_token_signed_with_another_secret_is_rejected() -> None:
    issuer = build_token_service()
    verifier = build_token_service(secret="a-totally-different-secret-value-0002")
    token, _ = issuer.issue_access_token(subject="user-123")

    with pytest.raises(UnauthenticatedError):
        verifier.decode_access_token(token)


@pytest.mark.unit
def test_expired_token_is_rejected_with_an_internal_reason() -> None:
    service = build_token_service(access_token_ttl_minutes=1)
    token, _ = service.issue_access_token(
        subject="user-123",
        now=datetime.now(UTC) - timedelta(hours=2),
    )

    with pytest.raises(UnauthenticatedError) as captured:
        service.decode_access_token(token)

    assert "token expired" in str(captured.value)
    assert captured.value.external().code == "UNAUTHENTICATED"


@pytest.mark.unit
def test_token_for_another_audience_is_rejected() -> None:
    issuer = build_token_service(audience="another-service")
    verifier = build_token_service(audience="ahia-clients")
    token, _ = issuer.issue_access_token(subject="user-123")

    with pytest.raises(UnauthenticatedError) as captured:
        verifier.decode_access_token(token)

    assert "audience" in str(captured.value)


@pytest.mark.unit
def test_token_from_another_issuer_is_rejected() -> None:
    issuer = build_token_service(issuer="someone-else")
    verifier = build_token_service(issuer="ahia-api")
    token, _ = issuer.issue_access_token(subject="user-123")

    with pytest.raises(UnauthenticatedError) as captured:
        verifier.decode_access_token(token)

    assert "issuer" in str(captured.value)


@pytest.mark.unit
def test_alg_none_token_is_rejected() -> None:
    """The signature algorithm is chosen by us, never by the token header."""
    service = build_token_service()
    unsigned = jwt.encode(
        {
            "sub": "attacker",
            "iss": "ahia-api",
            "aud": "ahia-clients",
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
            "jti": "forged",
            "typ": "access",
        },
        key="",
        algorithm="none",
    )

    with pytest.raises(UnauthenticatedError):
        service.decode_access_token(unsigned)


@pytest.mark.unit
def test_token_of_the_wrong_type_is_rejected() -> None:
    """A refresh token must not be usable as an access token."""
    service = build_token_service()
    refresh_style = jwt.encode(
        {
            "sub": "user-123",
            "iss": "ahia-api",
            "aud": "ahia-clients",
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(days=30)).timestamp()),
            "jti": "refresh-1",
            "typ": "refresh",
        },
        TEST_SIGNING_SECRET,
        algorithm="HS256",
    )

    with pytest.raises(UnauthenticatedError) as captured:
        service.decode_access_token(refresh_style)

    assert "not an access token" in str(captured.value)


@pytest.mark.unit
@pytest.mark.parametrize("token", ["", "not-a-token", "a.b.c", "a.b", "eyJhbGciOiJIUzI1NiJ9"])
def test_malformed_tokens_are_rejected(token: str) -> None:
    service = build_token_service()

    with pytest.raises(UnauthenticatedError):
        service.decode_access_token(token)


@pytest.mark.unit
def test_short_signing_secret_is_refused_at_construction() -> None:
    with pytest.raises(ConfigurationError):
        build_token_service(secret="too-short")


@pytest.mark.unit
def test_token_value_never_appears_in_the_error_or_its_log_line() -> None:
    service = build_token_service()
    token, _ = service.issue_access_token(subject="user-123")

    with pytest.raises(UnauthenticatedError) as captured:
        service.decode_access_token(token[:-5] + "AAAAA")

    assert token not in str(captured.value)
    assert token not in repr(captured.value.external().to_payload())


# ---------------------------------------------------------------------------
# Refresh tokens
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_refresh_token_is_stored_only_as_a_peppered_digest() -> None:
    service = build_token_service()

    plaintext, stored_hash = service.generate_refresh_token()

    assert plaintext != stored_hash
    assert len(plaintext) >= 48
    assert len(stored_hash) == 64
    assert service.verify_refresh_token(plaintext, stored_hash) is True


@pytest.mark.unit
def test_refresh_token_from_another_pepper_does_not_verify() -> None:
    """The pepper lives in the environment, so a database leak alone is not enough."""
    issuer = build_token_service()
    other = build_token_service(refresh_token_pepper="another-pepper-value-00000000002")
    plaintext, stored_hash = issuer.generate_refresh_token()

    assert other.verify_refresh_token(plaintext, stored_hash) is False


@pytest.mark.unit
def test_two_refresh_tokens_never_collide() -> None:
    service = build_token_service()

    tokens = {service.generate_refresh_token()[0] for _ in range(50)}

    assert len(tokens) == 50


@pytest.mark.unit
def test_wrong_refresh_token_is_rejected() -> None:
    service = build_token_service()
    _, stored_hash = service.generate_refresh_token()

    assert service.verify_refresh_token("some-other-token", stored_hash) is False


# ---------------------------------------------------------------------------
# Public tokens and helpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_public_tokens_are_unpredictable_and_distinct() -> None:
    service = build_token_service()

    tokens = {service.generate_public_token() for _ in range(50)}

    assert len(tokens) == 50
    assert all(len(token) >= 24 for token in tokens)


@pytest.mark.unit
def test_fingerprint_is_stable_and_does_not_reveal_the_value() -> None:
    secret = "ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"

    first = fingerprint_for_log(secret)
    second = fingerprint_for_log(secret)

    assert first == second
    assert secret not in first
    assert len(first) < len(secret)
    assert fingerprint_for_log("") == "empty"


@pytest.mark.unit
def test_constant_time_equals_matches_on_equal_values() -> None:
    assert constant_time_equals("abc123", "abc123") is True
    assert constant_time_equals("abc123", "abc124") is False
    assert constant_time_equals("abc", "abcd") is False


@pytest.mark.unit
def test_security_event_helper_returns_a_correlation_id() -> None:
    assert current_correlation_id_for_security_event()


@pytest.mark.unit
def test_no_primitive_secret_reaches_a_rendered_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A regression guard: a caller logging the wrong object must stay harmless.

    The assertion is on the rendered line, not the raw record, because redaction
    is the formatter's responsibility. Asserting on the record would test the
    wrong layer and would fail for the right reason only by accident.
    """
    logging_module = logging

    service = build_token_service()
    password_hash = build_hasher().hash_password("correct horse battery staple")
    plaintext_refresh, stored_hash = service.generate_refresh_token()

    with caplog.at_level(logging_module.INFO, logger="ahia.core.security"):
        logging_module.getLogger("ahia.core.security").info(
            "security_event",
            extra={
                "password": "correct horse battery staple",
                "password_hash": password_hash,
                "refresh_token": plaintext_refresh,
                "stored_hash": stored_hash,
                "api_key": TEST_SIGNING_SECRET,
            },
        )

    rendered = JsonLogFormatter().format(caplog.records[0])

    assert "correct horse battery staple" not in rendered
    assert plaintext_refresh not in rendered
    assert password_hash not in rendered
    assert stored_hash not in rendered
    assert TEST_SIGNING_SECRET not in rendered
    assert "[REDACTED]" in rendered
