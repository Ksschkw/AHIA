"""Tests for the banned-name guard.

The preset bans names that mean the author has not yet decided what a thing is.
The guard is deliberately narrow: it rejects a banned word used as a standalone
module, class, function or module-level name, and it permits the same word as
part of a longer, descriptive name.
"""

from __future__ import annotations

from pathlib import Path

import check_banned_names
import pytest


def write_module(directory: Path, name: str, content: str) -> Path:
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


def scan(directory: Path) -> list[check_banned_names.BannedNameViolation]:
    violations: list[check_banned_names.BannedNameViolation] = []
    for path in check_banned_names.iter_python_files([directory]):
        violations.extend(check_banned_names.scan_module(path, directory))
    return violations


@pytest.mark.unit
@pytest.mark.parametrize(
    "banned_name",
    ["data", "info", "manager", "helper", "utils", "common", "misc", "temp", "process", "thing"],
)
def test_rejects_banned_module_file_name(tmp_path: Path, banned_name: str) -> None:
    write_module(tmp_path, f"{banned_name}.py", '"""Module."""\n')

    violations = scan(tmp_path)

    assert [violation.kind for violation in violations] == ["module"]
    assert violations[0].name == banned_name


@pytest.mark.unit
def test_rejects_banned_class_name(tmp_path: Path) -> None:
    write_module(tmp_path, "invoice.py", "class Manager:\n    pass\n")

    violations = scan(tmp_path)

    assert [(violation.kind, violation.name) for violation in violations] == [("class", "Manager")]


@pytest.mark.unit
def test_rejects_banned_function_name(tmp_path: Path) -> None:
    write_module(tmp_path, "invoice.py", "def handle():\n    return 1\n")

    violations = scan(tmp_path)

    assert [(violation.kind, violation.name) for violation in violations] == [
        ("function", "handle")
    ]


@pytest.mark.unit
def test_rejects_banned_async_function_name(tmp_path: Path) -> None:
    write_module(tmp_path, "invoice.py", "async def process():\n    return 1\n")

    violations = scan(tmp_path)

    assert [(violation.kind, violation.name) for violation in violations] == [
        ("function", "process")
    ]


@pytest.mark.unit
def test_rejects_banned_module_level_assignment(tmp_path: Path) -> None:
    write_module(tmp_path, "invoice.py", "data = {}\n")

    violations = scan(tmp_path)

    assert [(violation.kind, violation.name) for violation in violations] == [
        ("module-level assignment", "data")
    ]


@pytest.mark.unit
def test_permits_banned_word_inside_a_descriptive_name(tmp_path: Path) -> None:
    module_source = (
        "def process_sale() -> None:\n    return None\n\n\nclass InvoiceManagerService:\n    pass\n"
    )
    write_module(tmp_path, "sales_service.py", module_source)

    violations = scan(tmp_path)

    assert violations == []


@pytest.mark.unit
def test_permits_local_variable_inside_a_function(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "invoice_service.py",
        "def calculate_total(rows: list[int]) -> int:\n    data = sum(rows)\n    return data\n",
    )

    violations = scan(tmp_path)

    assert violations == []


@pytest.mark.unit
def test_permits_an_allowlisted_method_name(tmp_path: Path) -> None:
    """A logging facade legitimately exposes `info` as a level method.

    The standard library, and every logging library in every language, names it
    that way. The exception is scoped to methods only.
    """
    write_module(
        tmp_path,
        "structured_logger.py",
        "class StructuredLogger:\n    def info(self, event: str) -> None:\n        return None\n",
    )

    violations = scan(tmp_path)

    assert violations == []


@pytest.mark.unit
def test_module_level_function_with_an_allowlisted_method_name_is_still_rejected(
    tmp_path: Path,
) -> None:
    write_module(tmp_path, "reporting.py", "def info() -> None:\n    return None\n")

    violations = scan(tmp_path)

    assert [(violation.kind, violation.name) for violation in violations] == [("function", "info")]


@pytest.mark.unit
def test_method_named_with_a_banned_word_outside_the_allowlist_is_rejected(
    tmp_path: Path,
) -> None:
    write_module(
        tmp_path,
        "invoice_service.py",
        "class InvoiceService:\n    def handle(self) -> None:\n        return None\n",
    )

    violations = scan(tmp_path)

    assert [(violation.kind, violation.name) for violation in violations] == [
        ("function", "handle")
    ]


@pytest.mark.unit
def test_reports_syntax_errors_rather_than_passing_silently(tmp_path: Path) -> None:
    write_module(tmp_path, "broken.py", "def calculate(\n")

    violations = scan(tmp_path)

    assert len(violations) == 1
    assert violations[0].kind == "syntax-error"


@pytest.mark.architecture
def test_repository_tree_has_no_banned_names(repository_root: Path) -> None:
    """The real repository must pass its own guard."""
    exit_code = check_banned_names.main([])

    assert exit_code == 0
