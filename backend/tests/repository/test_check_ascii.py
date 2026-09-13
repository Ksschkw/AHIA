"""Tests for the ASCII guard.

The guard is part of the build gate, so it is tested like production code: a
guard that stops detecting violations while reporting success is worse than no
guard at all.
"""

from __future__ import annotations

from pathlib import Path

import check_ascii
import pytest


def write_artifact(directory: Path, name: str, content: str) -> Path:
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


@pytest.mark.unit
def test_clean_ascii_tree_reports_no_violations(tmp_path: Path, repository_root: Path) -> None:
    write_artifact(tmp_path, "module.py", '"""Plain ASCII module."""\n\nVALUE = 1\n')

    violations = scan_tree(tmp_path, repository_root)

    assert violations == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("character", "expected_category"),
    [
        ("\u2705", "emoji-or-symbol"),
        ("\U0001f680", "emoji-or-symbol"),
        ("\u2500", "box-drawing"),
        ("\u2019", "typographic-punctuation"),
        ("\u00e9", "non-ascii"),
        ("\ufeff", "zero-width-or-bom"),
    ],
)
def test_detects_each_violation_category(
    tmp_path: Path,
    repository_root: Path,
    character: str,
    expected_category: str,
) -> None:
    write_artifact(tmp_path, "module.py", f'STATUS = "ok {character}"\n')

    violations = scan_tree(tmp_path, repository_root)

    assert len(violations) == 1
    assert violations[0].category == expected_category
    assert violations[0].line_number == 1


@pytest.mark.unit
def test_reports_path_line_and_column(tmp_path: Path, repository_root: Path) -> None:
    write_artifact(tmp_path, "module.py", "first = 1\nsecond = 'caf\u00e9'\n")

    violations = scan_tree(tmp_path, repository_root)

    assert len(violations) == 1
    assert violations[0].line_number == 2
    assert violations[0].column_number == 14


@pytest.mark.unit
def test_ignores_files_that_are_not_engineering_artifacts(
    tmp_path: Path, repository_root: Path
) -> None:
    write_artifact(tmp_path, "logo.png", "not really a png \U0001f680")

    violations = scan_tree(tmp_path, repository_root)

    assert violations == []


@pytest.mark.unit
def test_ignores_skipped_directories(tmp_path: Path, repository_root: Path) -> None:
    node_modules = tmp_path / "node_modules" / "package"
    node_modules.mkdir(parents=True)
    write_artifact(node_modules, "index.js", "const emoji = '\U0001f680';\n")

    violations = scan_tree(tmp_path, repository_root)

    assert violations == []


@pytest.mark.unit
def test_declared_unicode_fixture_prefix_is_skipped(tmp_path: Path, repository_root: Path) -> None:
    fixture_directory = tmp_path / "backend" / "tests" / "fixtures" / "unicode_data"
    fixture_directory.mkdir(parents=True)
    write_artifact(fixture_directory, "customer_notes.txt", "Ngozi says \U0001f64f\n")

    violations = scan_tree(tmp_path, repository_root)

    assert violations == []


@pytest.mark.unit
def test_undeclared_unicode_path_is_still_reported(tmp_path: Path, repository_root: Path) -> None:
    other_fixture_directory = tmp_path / "backend" / "tests" / "fixtures" / "other"
    other_fixture_directory.mkdir(parents=True)
    write_artifact(other_fixture_directory, "notes.txt", "Ngozi says \U0001f64f\n")

    violations = scan_tree(tmp_path, repository_root)

    assert len(violations) == 1


@pytest.mark.architecture
def test_repository_tree_is_ascii_clean(repository_root: Path) -> None:
    """The real repository must pass its own guard."""
    exit_code = check_ascii.main([])

    assert exit_code == 0


def scan_tree(root: Path, repository_root: Path) -> list[check_ascii.AsciiViolation]:
    """Scan a tree using the guard's own file-selection rules.

    The temporary directory is scanned as if it were the repository, so the
    allowlist behaviour is exercised without writing into the real tree.
    """
    violations: list[check_ascii.AsciiViolation] = []
    for path in check_ascii.iter_candidate_files([root]):
        violations.extend(check_ascii.scan_file(path, root))
    return violations
