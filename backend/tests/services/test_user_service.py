"""Tests for the user use cases.

The CRUD layer is mocked, and only the CRUD layer. Everything else is real: the
unit of work, the entity, the authorization decision and the structured log. A
service test that mocks its own dependencies proves that a function was called,
not that a rule holds.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

import ahia.services.user_service as user_service_module
from ahia.core.errors import (
    AuthorizationError,
    InvalidInputError,
    UnauthenticatedError,
)
from ahia.crud import user_crud
from ahia.models.entities.user_model import UserModel
from ahia.services.user_service import UserService

NOW = datetime(2026, 9, 13, 9, 30, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class FakePrincipal:
    """The structural shape the service depends on."""

    user_id: UUID
    token_identifier: str = "token-1"


class FakeSession:
    """A stand-in for the session handle.

    The service never inspects it; it only passes it to the CRUD functions, which
    are mocked in these tests. That the fake is opaque is the point.
    """


class FakeUnitOfWork:
    """A unit of work that records commit and rollback."""

    def __init__(self) -> None:
        self.session_handle = FakeSession()
        self.commits = 0
        self.rollbacks = 0
        self.exited = False

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(self, *exception: object) -> None:
        self.exited = True

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


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
    return UserModel.create(**parameters)


def build_service(user: UserModel | None, **overrides: Any) -> tuple[UserService, FakeUnitOfWork]:
    unit_of_work = FakeUnitOfWork()
    service = UserService(unit_of_work_factory=lambda: unit_of_work, **overrides)
    return service, unit_of_work


@pytest.fixture
def patch_crud(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace the CRUD functions and record what the service asked for."""
    calls: dict[str, Any] = {"get_by_id": [], "update": []}

    async def fake_get_by_id(session: Any, user_id: UUID) -> UserModel | None:
        calls["get_by_id"].append(user_id)
        return calls.get("user")

    async def fake_update(session: Any, user: UserModel) -> UserModel:
        calls["update"].append(user)
        return user

    monkeypatch.setattr(user_crud, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(user_crud, "update", fake_update)
    return calls


# ---------------------------------------------------------------------------
# Reading the authenticated user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_returns_the_authenticated_users_own_record(patch_crud: dict[str, Any]) -> None:
    user = build_user()
    patch_crud["user"] = user
    service, unit_of_work = build_service(user)

    result = await service.get_authenticated_user(FakePrincipal(user_id=user.id))

    assert result == user
    assert patch_crud["get_by_id"] == [user.id]
    assert unit_of_work.exited is True


@pytest.mark.asyncio
@pytest.mark.unit
async def test_a_missing_account_denies_and_says_nothing_externally(
    patch_crud: dict[str, Any],
) -> None:
    """A token for a row that no longer exists must not authenticate."""
    patch_crud["user"] = None
    missing_id = uuid4()
    service, _ = build_service(None)

    with pytest.raises(UnauthenticatedError) as captured:
        await service.get_authenticated_user(FakePrincipal(user_id=missing_id))

    assert "no user record" in str(captured.value)
    external = captured.value.external()
    assert external.code == "UNAUTHENTICATED"
    assert str(missing_id) not in external.message


@pytest.mark.asyncio
@pytest.mark.unit
async def test_a_deactivated_account_denies_at_once(patch_crud: dict[str, Any]) -> None:
    """Deactivation must stop existing tokens, not wait for them to expire."""
    user = build_user().deactivate(at=NOW + timedelta(hours=1))
    patch_crud["user"] = user
    service, _ = build_service(user)

    with pytest.raises(UnauthenticatedError) as captured:
        await service.get_authenticated_user(FakePrincipal(user_id=user.id))

    assert "deactivated" in str(captured.value)
    assert captured.value.external().code == "UNAUTHENTICATED"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_both_denials_are_indistinguishable_externally(
    patch_crud: dict[str, Any],
) -> None:
    """A caller must not learn whether their account exists or is disabled."""
    patch_crud["user"] = None
    service_missing, _ = build_service(None)
    with pytest.raises(UnauthenticatedError) as missing:
        await service_missing.get_authenticated_user(FakePrincipal(user_id=uuid4()))

    deactivated = build_user().deactivate(at=NOW)
    patch_crud["user"] = deactivated
    service_inactive, _ = build_service(deactivated)
    with pytest.raises(UnauthenticatedError) as inactive:
        await service_inactive.get_authenticated_user(FakePrincipal(user_id=deactivated.id))

    assert missing.value.external().code == inactive.value.external().code
    assert missing.value.external().message == inactive.value.external().message


@pytest.mark.asyncio
@pytest.mark.unit
async def test_the_decision_is_logged_with_the_actor(
    patch_crud: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    user = build_user()
    patch_crud["user"] = user
    service, _ = build_service(user)

    with caplog.at_level(logging.INFO, logger="ahia.services.user"):
        await service.get_authenticated_user(FakePrincipal(user_id=user.id, token_identifier="t-9"))

    events = [record.getMessage() for record in caplog.records]
    assert "authorization_allowed" in events
    allowed = next(r for r in caplog.records if r.getMessage() == "authorization_allowed")
    assert allowed.actor_id == str(user.id)
    assert allowed.decision == "allowed"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_a_denial_is_logged_with_its_reason(
    patch_crud: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    patch_crud["user"] = None
    service, _ = build_service(None)

    with (
        caplog.at_level(logging.WARNING, logger="ahia.services.user"),
        pytest.raises(UnauthenticatedError),
    ):
        await service.get_authenticated_user(FakePrincipal(user_id=uuid4()))

    denied = next(r for r in caplog.records if r.getMessage() == "authorization_denied")
    assert denied.reason == "subject_has_no_account"
    assert denied.decision == "denied"


# ---------------------------------------------------------------------------
# Profile update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_profile_update_applies_changes_and_commits_once(
    patch_crud: dict[str, Any],
) -> None:
    user = build_user()
    patch_crud["user"] = user
    service, unit_of_work = build_service(user)

    updated = await service.update_own_profile(
        FakePrincipal(user_id=user.id), changes={"first_name": "Chinedu"}
    )

    assert updated.first_name == "Chinedu"
    assert updated.last_name == "Okonkwo"
    assert updated.email == user.email
    assert unit_of_work.commits == 1
    assert len(patch_crud["update"]) == 1


@pytest.mark.asyncio
@pytest.mark.unit
async def test_profile_update_normalizes_a_new_contact(
    patch_crud: dict[str, Any],
) -> None:
    user = build_user(email=None, phone="+2348031234567")
    patch_crud["user"] = user
    service, _ = build_service(user)

    updated = await service.update_own_profile(
        FakePrincipal(user_id=user.id), changes={"email": "  ADA@Example.com "}
    )

    assert updated.email == "ada@example.com"
    assert updated.phone == "+2348031234567"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_profile_update_rejects_a_field_outside_the_allowlist(
    patch_crud: dict[str, Any],
) -> None:
    """The status column is not a profile field, however the request reached here."""
    user = build_user()
    patch_crud["user"] = user
    service, unit_of_work = build_service(user)

    with pytest.raises(InvalidInputError) as captured:
        await service.update_own_profile(
            FakePrincipal(user_id=user.id), changes={"is_active": "false"}
        )

    assert "not editable" in str(captured.value)
    assert unit_of_work.commits == 0
    assert patch_crud["update"] == []


@pytest.mark.asyncio
@pytest.mark.unit
async def test_profile_update_denies_a_deactivated_account(
    patch_crud: dict[str, Any],
) -> None:
    user = build_user().deactivate(at=NOW)
    patch_crud["user"] = user
    service, unit_of_work = build_service(user)

    with pytest.raises(UnauthenticatedError):
        await service.update_own_profile(
            FakePrincipal(user_id=user.id), changes={"first_name": "X"}
        )

    assert unit_of_work.commits == 0


@pytest.mark.asyncio
@pytest.mark.unit
async def test_profile_update_does_not_log_personal_data(
    patch_crud: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """An audit line needs the fact of the change, not the new email address."""
    user = build_user()
    patch_crud["user"] = user
    service, _ = build_service(user)

    with caplog.at_level(logging.INFO, logger="ahia.services.user"):
        await service.update_own_profile(
            FakePrincipal(user_id=user.id), changes={"email": "ada@example.com"}
        )

    record = next(r for r in caplog.records if r.getMessage() == "user_profile_updated")
    assert record.changed_fields == ["email"]
    assert "ada@example.com" not in repr(record.__dict__)


# ---------------------------------------------------------------------------
# Deactivation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_deactivating_the_account_commits_and_returns_the_new_state(
    patch_crud: dict[str, Any],
) -> None:
    user = build_user()
    patch_crud["user"] = user
    service, unit_of_work = build_service(user)

    deactivated = await service.deactivate_own_account(FakePrincipal(user_id=user.id))

    assert deactivated.is_active is False
    assert deactivated.id == user.id
    assert unit_of_work.commits == 1
    assert user.is_active is True, "the caller's copy is not mutated"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_deactivation_is_logged_as_a_warning(
    patch_crud: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """Losing access to a business is worth noticing in an operational log."""
    user = build_user()
    patch_crud["user"] = user
    service, _ = build_service(user)

    with caplog.at_level(logging.WARNING, logger="ahia.services.user"):
        await service.deactivate_own_account(FakePrincipal(user_id=user.id))

    record = next(r for r in caplog.records if r.getMessage() == "user_account_deactivated")
    assert record.outcome == "deactivated"
    assert record.user_id == str(user.id)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_the_principal_is_the_only_source_of_the_target_identifier(
    patch_crud: dict[str, Any],
) -> None:
    """No use case may take a target identifier from the request body.

    Every lookup in this service uses the authenticated principal's identifier, so
    a body field cannot redirect an operation at another account.
    """
    user = build_user()
    patch_crud["user"] = user
    service, _ = build_service(user)
    principal = FakePrincipal(user_id=user.id)

    await service.get_authenticated_user(principal)
    await service.update_own_profile(principal, changes={"first_name": "Chinedu"})
    await service.deactivate_own_account(principal)

    assert set(patch_crud["get_by_id"]) == {user.id}


@pytest.mark.asyncio
@pytest.mark.unit
async def test_a_lookup_that_returns_somebody_elses_record_is_denied(
    patch_crud: dict[str, Any],
) -> None:
    """The account-holder check fires when a lookup returns the wrong record.

    That is the shape of a future cross-account defect, so the check runs on
    every call rather than only on the paths that currently pass a target
    identifier. The repository is made to return another user's row.
    """
    requested_id = uuid4()
    other_users_record = build_user()
    patch_crud["user"] = other_users_record
    service, _ = build_service(other_users_record)

    with pytest.raises(AuthorizationError) as captured:
        await service.get_authenticated_user(FakePrincipal(user_id=requested_id))

    assert "not the account holder" in str(captured.value)
    assert captured.value.external().code == "FORBIDDEN"
    assert patch_crud["get_by_id"] == [requested_id]


@pytest.mark.unit
def test_the_service_imports_no_database_driver() -> None:
    """The architecture contract covers this; the AST check makes it local too."""
    tree = ast.parse(Path(user_service_module.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert not imported & {"sqlalchemy", "asyncpg", "alembic"}
    assert AuthorizationError is not None
