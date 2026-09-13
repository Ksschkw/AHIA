"""Tests for the user transport layer.

The service is mocked and nothing else: the real application, the real
middleware stack, the real token service and the real schemas. That is what makes
these tests evidence that the wiring works, rather than evidence that a function
is called.
"""

from __future__ import annotations

import ast
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

import ahia.routers.user_router as user_router_module
from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.main import create_application
from ahia.models.entities.user_model import UserModel
from ahia.routers import user_router

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)


def build_settings(**overrides: Any) -> Settings:
    baseline: dict[str, Any] = {
        "_env_file": None,
        "app_env": AppEnvironment.TEST,
        "database_url": os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL),
        "jwt_secret": "test-signing-secret-value-0000000001",
        "refresh_token_pepper": "test-refresh-pepper-value-00000000011",
        "storage_provider": StorageProviderName.R2,
        "r2_endpoint": "https://account.r2.cloudflarestorage.com",
        "r2_access_key_id": "r2-access-key",
        "r2_secret_access_key": "r2-secret-key",
        "r2_bucket": "ahia-test",
        "rate_limit_global_per_minute": 1_000,
        "rate_limit_write_per_minute": 1_000,
        "rate_limit_auth_per_minute": 1_000,
    }
    baseline.update(overrides)
    return Settings(**baseline)


def build_user(**overrides: Any) -> UserModel:
    parameters: dict[str, Any] = {
        "user_id": uuid4(),
        "first_name": "Emeka",
        "now": NOW,
        "last_name": "Okonkwo",
        "email": "emeka@example.com",
        "phone": None,
    }
    parameters.update(overrides)
    return UserModel.create(**parameters)  # type: ignore[arg-type]


class FakeUserService:
    """A service double that records the calls it receives."""

    def __init__(self) -> None:
        self.user: UserModel | None = None
        self.calls: list[tuple[str, Any]] = []
        self.error: BaseException | None = None

    async def get_authenticated_user(self, principal: Any) -> UserModel:
        self.calls.append(("get_authenticated_user", principal.user_id))
        self._raise_if_configured()
        assert self.user is not None
        return self.user

    async def update_own_profile(self, principal: Any, *, changes: dict[str, Any]) -> UserModel:
        self.calls.append(("update_own_profile", changes))
        self._raise_if_configured()
        assert self.user is not None
        return self.user.with_profile(**changes, at=NOW)

    async def deactivate_own_account(self, principal: Any) -> UserModel:
        self.calls.append(("deactivate_own_account", principal.user_id))
        self._raise_if_configured()
        assert self.user is not None
        return self.user.deactivate(at=NOW)

    def _raise_if_configured(self) -> None:
        if self.error is not None:
            raise self.error


@asynccontextmanager
async def running_application(
    fake_service: FakeUserService,
    settings: Settings | None = None,
) -> AsyncIterator[tuple[AsyncClient, Any]]:
    """Yield a client and the application, with the service replaced.

    The lifespan runs for real, so the container, the token service and the
    middleware are the ones a deployment uses.
    """
    application = create_application(settings or build_settings())
    application.dependency_overrides[user_router.get_user_service] = lambda: fake_service

    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="https://testserver") as client:
            yield client, application


def issue_token(application: Any, user_id: UUID) -> str:
    token, _ = application.state.container.token_service.issue_access_token(subject=str(user_id))
    return token


def authorization_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# GET /users/me
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_read_own_profile_returns_the_caller() -> None:
    fake_service = FakeUserService()
    fake_service.user = build_user()

    async with running_application(fake_service) as (client, application):
        token = issue_token(application, fake_service.user.id)
        response = await client.get("/api/v1/users/me", headers=authorization_header(token))

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(fake_service.user.id)
    assert payload["first_name"] == "Emeka"
    assert payload["email"] == "emeka@example.com"
    assert fake_service.calls == [("get_authenticated_user", fake_service.user.id)]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_read_own_profile_never_exposes_a_credential() -> None:
    fake_service = FakeUserService()
    fake_service.user = build_user(password_hash="$argon2id$v=19$m=65536,t=3,p=2$c2FsdA$aGFzaA")

    async with running_application(fake_service) as (client, application):
        token = issue_token(application, fake_service.user.id)
        response = await client.get("/api/v1/users/me", headers=authorization_header(token))

    assert "argon2" not in response.text
    assert "password" not in response.text.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_missing_authorization_header_is_unauthenticated() -> None:
    fake_service = FakeUserService()
    fake_service.user = build_user()

    async with running_application(fake_service) as (client, _application):
        response = await client.get("/api/v1/users/me")

    payload = response.json()

    assert response.status_code == 401
    assert payload["error"]["code"] == "UNAUTHENTICATED"
    assert payload["error"]["correlation_id"]
    assert fake_service.calls == [], "the service must not be reached without a credential"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "header",
    [
        "NotBearer abc",
        "Bearer ",
        "Bearer not-a-token",
        "Bearer a.b.c",
        "",
    ],
)
async def test_malformed_authorization_is_unauthenticated_with_one_answer(header: str) -> None:
    fake_service = FakeUserService()
    fake_service.user = build_user()

    async with running_application(fake_service) as (client, _application):
        response = await client.get("/api/v1/users/me", headers={"Authorization": header})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert response.json()["error"]["message"] == "Authentication is required."


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_token_for_another_issuer_is_rejected() -> None:
    """The application validates the issuer, so a token from elsewhere is a stranger."""
    fake_service = FakeUserService()
    fake_service.user = build_user()
    foreign_settings = build_settings(jwt_issuer="another-service")

    async with running_application(fake_service) as (client, application):
        token = issue_token(application, fake_service.user.id)

    async with running_application(fake_service, foreign_settings) as (client, _application):
        response = await client.get("/api/v1/users/me", headers=authorization_header(token))

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /users/me
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_own_profile_passes_only_the_supplied_fields() -> None:
    fake_service = FakeUserService()
    fake_service.user = build_user()

    async with running_application(fake_service) as (client, application):
        token = issue_token(application, fake_service.user.id)
        response = await client.patch(
            "/api/v1/users/me",
            headers=authorization_header(token),
            json={"first_name": "Chinedu"},
        )

    assert response.status_code == 200
    assert fake_service.calls == [("update_own_profile", {"first_name": "Chinedu"})]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_rejects_an_unknown_field_with_the_standard_envelope() -> None:
    fake_service = FakeUserService()
    fake_service.user = build_user()

    async with running_application(fake_service) as (client, application):
        token = issue_token(application, fake_service.user.id)
        response = await client.patch(
            "/api/v1/users/me",
            headers=authorization_header(token),
            json={"firstname": "Chinedu"},
        )

    payload = response.json()

    assert response.status_code == 422
    assert set(payload["error"]) == {"code", "message", "correlation_id"}
    assert payload["error"]["code"] == "INVALID_REQUEST"
    assert fake_service.calls == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_validation_failure_does_not_echo_the_submitted_value() -> None:
    """A response that quotes the input is a response that can be reflected."""
    fake_service = FakeUserService()
    fake_service.user = build_user()

    async with running_application(fake_service) as (client, application):
        token = issue_token(application, fake_service.user.id)
        response = await client.patch(
            "/api/v1/users/me",
            headers=authorization_header(token),
            json={"email": "definitely-not-an-email"},
        )

    assert response.status_code == 422
    assert "definitely-not-an-email" not in response.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_rejects_an_attempt_to_change_protected_state() -> None:
    fake_service = FakeUserService()
    fake_service.user = build_user()

    async with running_application(fake_service) as (client, application):
        token = issue_token(application, fake_service.user.id)
        response = await client.patch(
            "/api/v1/users/me",
            headers=authorization_header(token),
            json={"is_active": False},
        )

    assert response.status_code == 422
    assert fake_service.calls == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_empty_update_is_accepted_and_changes_nothing() -> None:
    fake_service = FakeUserService()
    fake_service.user = build_user()

    async with running_application(fake_service) as (client, application):
        token = issue_token(application, fake_service.user.id)
        response = await client.patch(
            "/api/v1/users/me", headers=authorization_header(token), json={}
        )

    assert response.status_code == 200
    assert fake_service.calls == [("update_own_profile", {})]


# ---------------------------------------------------------------------------
# DELETE /users/me
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_deactivate_returns_the_resulting_state() -> None:
    fake_service = FakeUserService()
    fake_service.user = build_user()

    async with running_application(fake_service) as (client, application):
        token = issue_token(application, fake_service.user.id)
        response = await client.delete("/api/v1/users/me", headers=authorization_header(token))

    payload = response.json()

    assert response.status_code == 200
    assert payload["is_active"] is False
    assert fake_service.calls == [("deactivate_own_account", fake_service.user.id)]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_deactivate_requires_authentication() -> None:
    fake_service = FakeUserService()
    fake_service.user = build_user()

    async with running_application(fake_service) as (client, _application):
        response = await client.delete("/api/v1/users/me")

    assert response.status_code == 401
    assert fake_service.calls == []


# ---------------------------------------------------------------------------
# Cross-cutting behaviour of these routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_every_response_carries_the_correlation_header() -> None:
    fake_service = FakeUserService()
    fake_service.user = build_user()

    async with running_application(fake_service) as (client, application):
        token = issue_token(application, fake_service.user.id)
        success = await client.get("/api/v1/users/me", headers=authorization_header(token))
        failure = await client.get(
            "/api/v1/users/me", headers={"X-Correlation-ID": "user-slice-trace-1"}
        )

    assert success.headers["x-correlation-id"]
    assert failure.headers["x-correlation-id"] == "user-slice-trace-1"
    assert failure.json()["error"]["correlation_id"] == "user-slice-trace-1"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_security_headers_are_present_on_this_route() -> None:
    fake_service = FakeUserService()
    fake_service.user = build_user()

    async with running_application(fake_service) as (client, application):
        token = issue_token(application, fake_service.user.id)
        response = await client.get("/api/v1/users/me", headers=authorization_header(token))

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_service_failure_becomes_the_standard_envelope() -> None:
    fake_service = FakeUserService()
    fake_service.user = build_user()
    fake_service.error = RuntimeError("connection to db.internal:5432 refused")

    async with running_application(fake_service) as (client, application):
        token = issue_token(application, fake_service.user.id)
        response = await client.get("/api/v1/users/me", headers=authorization_header(token))

    payload = response.json()

    assert response.status_code == 500
    assert payload["error"]["code"] == "INTERNAL_ERROR"
    assert "db.internal" not in response.text
    assert "RuntimeError" not in response.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_route_is_not_reachable_without_the_version_prefix() -> None:
    fake_service = FakeUserService()
    fake_service.user = build_user()

    async with running_application(fake_service) as (client, _application):
        response = await client.get("/users/me")

    assert response.status_code == 404
    assert json.loads(response.text)["error"]["code"] == "NOT_FOUND"


@pytest.mark.unit
def test_the_handler_contains_no_business_logic() -> None:
    """A handler that branches is a handler holding a rule the service also holds.

    The check is structural: the module may not contain a conditional, a loop or
    a direct persistence call outside the dependency functions.
    """
    tree = ast.parse(Path(user_router_module.__file__).read_text(encoding="utf-8"))
    handler_names = {"read_own_profile", "update_own_profile", "deactivate_own_account"}
    offences: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name in handler_names:
            for inner in ast.walk(node):
                if isinstance(inner, ast.If | ast.For | ast.While | ast.Try):
                    offences.append(f"{node.name} contains {type(inner).__name__}")

    assert offences == [], f"a handler holds logic: {offences}"


@pytest.mark.unit
def test_the_router_imports_no_persistence_layer() -> None:
    tree = ast.parse(Path(user_router_module.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not any(name.startswith("ahia.crud") for name in imported)
    assert not any(name.startswith("sqlalchemy") for name in imported)
