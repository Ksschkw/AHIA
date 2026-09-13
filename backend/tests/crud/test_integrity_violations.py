"""Tests for translating database integrity failures into typed errors.

The database reports several different refusals through one exception class, and the
difference decides what an operator sees in a log and what a client is told. These
tests pin that mapping, including the part that matters most: whatever the database
said, the external message says nothing about the schema.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from ahia.core.errors import ConflictError, NotFoundError, PersistenceError
from ahia.crud.integrity_violations import (
    CHECK_VIOLATION,
    EXCLUSION_VIOLATION,
    FOREIGN_KEY_VIOLATION,
    NOT_NULL_VIOLATION,
    UNIQUE_VIOLATION,
    IntegrityViolation,
    classify,
    constraint_name,
    sqlstate_of,
    translate_integrity_violation,
)


class FakeDriverViolationError(Exception):
    """A stand-in for the driver's exception.

    Real driver errors carry a SQLSTATE and, for constraint failures, a diagnostic
    carrying the constraint name. Constructing one here keeps these tests independent
    of a database connection while still exercising the attribute paths the real
    errors use - including the nested case, where the driver's error is wrapped.
    """

    def __init__(self, sqlstate: str | None, constraint: str | None = None) -> None:
        super().__init__("driver violation")
        if sqlstate is not None:
            self.sqlstate = sqlstate
        if constraint is not None:
            self.constraint_name = constraint


class DriverDiagnostic:
    """The shape asyncpg uses: the name lives on a diagnostic object."""

    def __init__(self, constraint: str) -> None:
        self.constraint_name = constraint


class FakeDriverViolationWithDiagnosticError(FakeDriverViolationError):
    def __init__(self, sqlstate: str, constraint: str) -> None:
        super().__init__(sqlstate)
        self.diag = DriverDiagnostic(constraint)


def build_integrity_error(driver_error: BaseException | None) -> IntegrityError:
    """Build the exception SQLAlchemy raises around a driver error."""
    return IntegrityError("INSERT INTO things VALUES (:one)", {"one": 1}, driver_error)  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        (UNIQUE_VIOLATION, IntegrityViolation.UNIQUE),
        (FOREIGN_KEY_VIOLATION, IntegrityViolation.FOREIGN_KEY),
        (NOT_NULL_VIOLATION, IntegrityViolation.NOT_NULL),
        (CHECK_VIOLATION, IntegrityViolation.CHECK),
        (EXCLUSION_VIOLATION, IntegrityViolation.EXCLUSION),
        ("40001", IntegrityViolation.UNKNOWN),
        (None, IntegrityViolation.UNKNOWN),
    ],
)
def test_each_sqlstate_maps_to_its_own_kind(sqlstate: str | None, expected: Any) -> None:
    conflict = build_integrity_error(FakeDriverViolationError(sqlstate))

    assert classify(conflict) is expected


@pytest.mark.unit
def test_the_sqlstate_is_read_through_a_wrapped_driver_error() -> None:
    """The driver's exception can sit one level down; losing it means losing the kind."""
    inner = FakeDriverViolationError(UNIQUE_VIOLATION, constraint="uq_things_code")
    wrapped = build_integrity_error(RuntimeError("wrapper"))
    wrapped.orig = RuntimeError("outer")  # type: ignore[assignment]
    wrapped.orig.__cause__ = inner  # type: ignore[attr-defined]

    assert sqlstate_of(wrapped) == UNIQUE_VIOLATION
    assert classify(wrapped) is IntegrityViolation.UNIQUE
    assert constraint_name(wrapped) == "uq_things_code"


@pytest.mark.unit
def test_a_constraint_name_is_read_from_the_diagnostic_when_that_is_where_it_is() -> None:
    conflict = build_integrity_error(
        FakeDriverViolationWithDiagnosticError(CHECK_VIOLATION, "ck_price")
    )

    assert constraint_name(conflict) == "ck_price"


@pytest.mark.unit
def test_a_nameless_failure_still_reports_the_driver_exception_type() -> None:
    """An unknown constraint must not degrade into an empty internal detail."""
    conflict = build_integrity_error(FakeDriverViolationError(UNIQUE_VIOLATION))

    assert constraint_name(conflict) == "FakeDriverViolationError"


@pytest.mark.unit
def test_a_duplicate_is_a_conflict() -> None:
    conflict = build_integrity_error(
        FakeDriverViolationError(UNIQUE_VIOLATION, constraint="uq_users_email")
    )

    error = translate_integrity_violation(
        conflict,
        operation="create_user",
        entity="user",
        identifier="8f3a",
        conflict_detail="a user with this email already exists",
    )

    assert isinstance(error, ConflictError)
    assert "a user with this email already exists" in (error.context.detail or "")
    assert "uq_users_email" in (error.context.detail or "")
    assert error.context.operation == "create_user"
    assert error.context.entity == "user"
    assert error.context.identifier == "8f3a"


@pytest.mark.unit
def test_a_missing_referenced_row_is_not_reported_as_a_duplicate() -> None:
    """The distinction this module exists for.

    A foreign-key failure used to be reported as "already exists", which sends an
    operator looking for a duplicate that was never there.
    """
    conflict = build_integrity_error(
        FakeDriverViolationError(FOREIGN_KEY_VIOLATION, constraint="fk_devices_tenant_id_tenants")
    )

    error = translate_integrity_violation(
        conflict,
        operation="create_device",
        entity="device",
        identifier="6e6f",
        conflict_detail="this installation is already registered",
        missing_detail="the business or person this device belongs to does not exist",
    )

    assert isinstance(error, NotFoundError)
    detail = error.context.detail or ""
    assert "does not exist" in detail
    assert "fk_devices_tenant_id_tenants" in detail
    assert "already registered" not in detail, "a missing parent is not a duplicate"


@pytest.mark.unit
def test_a_check_violation_is_reported_as_a_defect_not_as_a_conflict() -> None:
    """A check the code broke is a bug; calling it a conflict hides that."""
    conflict = build_integrity_error(
        FakeDriverViolationError(CHECK_VIOLATION, constraint="ck_price_sign")
    )

    error = translate_integrity_violation(
        conflict,
        operation="create_product",
        entity="product",
        identifier="9c1b",
        conflict_detail="a product with this slug already exists",
    )

    assert isinstance(error, PersistenceError)
    assert not isinstance(error, ConflictError)
    detail = error.context.detail or ""
    assert "ck_price_sign" in detail
    assert "already exists" not in detail


@pytest.mark.unit
def test_an_unknown_integrity_failure_stays_a_persistence_error() -> None:
    conflict = build_integrity_error(FakeDriverViolationError("40001"))

    error = translate_integrity_violation(
        conflict,
        operation="create_tenant",
        entity="tenant",
        conflict_detail="the slug is already taken",
    )

    assert isinstance(error, PersistenceError)
    assert not isinstance(error, ConflictError)


@pytest.mark.unit
def test_the_external_view_discloses_nothing_about_the_schema() -> None:
    """The constraint name is for the log; the client gets a safe sentence."""
    secret_constraint = "uq_users_email_address_tenant_scope"
    conflict = build_integrity_error(
        FakeDriverViolationError(UNIQUE_VIOLATION, constraint=secret_constraint)
    )

    error = translate_integrity_violation(
        conflict,
        operation="create_user",
        entity="user",
        identifier="8f3a",
        conflict_detail="a user with this email already exists",
    )
    external = error.external()

    assert secret_constraint not in external.message
    assert "uq_users_email" not in external.message
    assert "INSERT" not in external.message
    assert "create_user" not in external.message
    assert external.message == error.safe_message


@pytest.mark.unit
def test_the_cause_chain_is_preserved_for_the_engineer() -> None:
    driver_error = FakeDriverViolationError(UNIQUE_VIOLATION, constraint="uq_users_email")
    conflict = build_integrity_error(driver_error)

    error = translate_integrity_violation(
        conflict,
        operation="create_user",
        entity="user",
        conflict_detail="a user with this email already exists",
    )

    assert error.__cause__ is conflict
    assert error.context.causes, "the internal view must carry the chain"
