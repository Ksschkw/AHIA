"""Translation of database integrity failures into typed errors.

The database raises one exception class for several different situations, and the
difference matters. A duplicate key means the caller asked for something that already
exists. A foreign-key failure means the row being referenced does not exist. A check
violation means this code wrote a value the schema forbids, which is a defect rather
than a caller mistake.

Reporting all three as "already exists" is how an operator spends an hour looking for
a duplicate that was never there. The distinction is made once, here, so every
repository reports the same failure the same way, and the internal detail always names
the violated constraint while the external message never does.

The classification uses SQLSTATE codes rather than driver exception classes: the codes
are part of the SQL standard, so this file stays correct if the driver is swapped, and
the persistence layer never imports a driver.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Final

from sqlalchemy.exc import IntegrityError

from ahia.core.errors import AhiaError, ConflictError, NotFoundError, PersistenceError

UNIQUE_VIOLATION: Final[str] = "23505"
FOREIGN_KEY_VIOLATION: Final[str] = "23503"
NOT_NULL_VIOLATION: Final[str] = "23502"
CHECK_VIOLATION: Final[str] = "23514"
EXCLUSION_VIOLATION: Final[str] = "23P01"

MISSING_REFERENCED_ROW: Final[str] = "a row this record references does not exist"


class IntegrityViolation(StrEnum):
    """What the database refused, in terms the application can act on."""

    UNIQUE = "unique"
    FOREIGN_KEY = "foreign_key"
    NOT_NULL = "not_null"
    CHECK = "check"
    EXCLUSION = "exclusion"
    UNKNOWN = "unknown"


_SQLSTATE_TO_VIOLATION: Final[dict[str, IntegrityViolation]] = {
    UNIQUE_VIOLATION: IntegrityViolation.UNIQUE,
    FOREIGN_KEY_VIOLATION: IntegrityViolation.FOREIGN_KEY,
    NOT_NULL_VIOLATION: IntegrityViolation.NOT_NULL,
    CHECK_VIOLATION: IntegrityViolation.CHECK,
    EXCLUSION_VIOLATION: IntegrityViolation.EXCLUSION,
}


def _driver_exception_candidates(conflict: IntegrityError) -> list[Any]:
    """Return the driver exception and its wrapped causes, nearest first.

    SQLAlchemy wraps the driver's exception, and the driver may in turn wrap it. Every
    known position is inspected rather than one, because a translation that silently
    loses the cause would report "unknown" for a failure the database named exactly.
    """
    original = getattr(conflict, "orig", None)
    candidates: list[Any] = [original, getattr(original, "__cause__", None)]
    candidates.append(getattr(original, "__context__", None))
    return [candidate for candidate in candidates if candidate is not None]


def sqlstate_of(conflict: IntegrityError) -> str | None:
    """Return the SQLSTATE the database reported, or None if the driver withheld it."""
    for candidate in _driver_exception_candidates(conflict):
        sqlstate = getattr(candidate, "sqlstate", None)
        if sqlstate:
            return str(sqlstate)
    return None


def classify(conflict: IntegrityError) -> IntegrityViolation:
    """Return what the database refused."""
    sqlstate = sqlstate_of(conflict)
    if sqlstate is None:
        return IntegrityViolation.UNKNOWN
    return _SQLSTATE_TO_VIOLATION.get(sqlstate, IntegrityViolation.UNKNOWN)


def constraint_name(conflict: IntegrityError) -> str:
    """Return the violated constraint's name, for the internal error detail.

    The name is for logs and traces. It is never returned to a client: a constraint
    name describes the schema.
    """
    for candidate in _driver_exception_candidates(conflict):
        direct = getattr(candidate, "constraint_name", None)
        if direct:
            return str(direct)
        diagnostic = getattr(candidate, "diag", None)
        named = getattr(diagnostic, "constraint_name", None)
        if named:
            return str(named)
    original = getattr(conflict, "orig", None)
    return type(original).__name__ if original is not None else "unknown-constraint"


def translate_integrity_violation(
    conflict: IntegrityError,
    *,
    operation: str,
    entity: str,
    identifier: str | None = None,
    conflict_detail: str,
    missing_detail: str = MISSING_REFERENCED_ROW,
) -> AhiaError:
    """Return the typed error that describes what the database refused.

    ``conflict_detail`` describes the uniqueness rule the caller broke. It is used
    only when the failure really was a duplicate: a foreign-key failure gets
    ``missing_detail`` instead, and a check or NOT NULL failure is reported as what it
    is - the application writing a value the schema forbids, which is a defect.

    The return type is the shared base because the caller raises whatever kind the
    database indicated; the specific type is what the transport layer maps.
    """
    violation = classify(conflict)
    constraint = constraint_name(conflict)
    if violation is IntegrityViolation.FOREIGN_KEY:
        return NotFoundError(
            operation=operation,
            entity=entity,
            identifier=identifier,
            detail=f"{missing_detail}: {constraint}",
            cause=conflict,
        )
    if violation in (IntegrityViolation.UNIQUE, IntegrityViolation.EXCLUSION):
        return ConflictError(
            operation=operation,
            entity=entity,
            identifier=identifier,
            detail=f"{conflict_detail}: {constraint}",
            cause=conflict,
        )
    return PersistenceError(
        operation=operation,
        entity=entity,
        identifier=identifier,
        detail=f"the database refused this write ({violation}): {constraint}",
        cause=conflict,
    )
