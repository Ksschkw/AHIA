"""Shared pytest configuration.

Two jobs live here.

1. Make the developer-guard scripts importable so they can be unit tested.
   ``backend/scripts`` is a directory of executables rather than an installed
   package, so it is placed on ``sys.path`` explicitly. The guards are part of
   the build gate, which means they need the same test coverage as production
   code: a guard that silently stops detecting violations is worse than no
   guard, because the team believes it is protected.

2. Hold fixtures shared by more than one test package. Fixtures used by exactly
   one test module stay in that module.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ahia.core.errors import clear_correlation_id

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_DIRECTORY.parent
SCRIPTS_DIRECTORY = BACKEND_DIRECTORY / "scripts"
FIXTURES_DIRECTORY = Path(__file__).resolve().parent / "fixtures"

if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))


@pytest.fixture(autouse=True)
def isolate_correlation_context() -> None:
    """Clear the request correlation ID around every test.

    The correlation ID lives in a context variable, which is process-wide for
    the test thread. Without this, a test that binds an identifier leaks it into
    every later test in the same worker, which produces order-dependent
    failures that look like product defects.
    """
    clear_correlation_id()
    yield
    clear_correlation_id()


@pytest.fixture(scope="session")
def repository_root() -> Path:
    """Absolute path to the repository root."""
    return REPOSITORY_ROOT


@pytest.fixture(scope="session")
def backend_directory() -> Path:
    """Absolute path to the backend workspace."""
    return BACKEND_DIRECTORY


@pytest.fixture(scope="session")
def fixtures_directory() -> Path:
    """Absolute path to the shared test fixtures directory."""
    return FIXTURES_DIRECTORY
