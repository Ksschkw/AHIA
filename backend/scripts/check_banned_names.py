#!/usr/bin/env python3
"""Reject banned standalone names.

The preset bans a specific set of names because each one is a decision the
author has not made yet: `data`, `info`, `manager`, `helper`, `util`, `utils`,
`common`, `misc`, `temp`, `tmp`, `process`, `handle`, `do`, `thing`.

The ban applies to *standalone* names: a module file stem, a class name, a
function or method name, and a module-level assignment. It does not apply to a
longer name that happens to contain the word (`process_sale` is a verb phrase
and is good; `process` alone is not). Local variables inside a function are out
of scope, because a loop body naming a temporary `row` or `entry` is ordinary
Python and policing it produces noise rather than clarity.

Usage:
    python scripts/check_banned_names.py [paths...]

Exit codes:
    0  no violations
    1  violations found
    2  usage error
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

BANNED_NAMES: frozenset[str] = frozenset(
    {
        "data",
        "info",
        "manager",
        "helper",
        "util",
        "utils",
        "common",
        "misc",
        "temp",
        "tmp",
        "process",
        "handle",
        "do",
        "thing",
    }
)

SKIPPED_DIRECTORY_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".tools",
        "dist",
        "build",
        ".next",
        ".expo",
        "htmlcov",
    }
)

# Files that are allowed to contain banned words because their subject matter is
# the ban itself, or because they are generated. Each entry needs a reason.
ALLOWED_PATHS: frozenset[str] = frozenset(
    {
        "backend/scripts/check_banned_names.py",
    }
)


@dataclass(frozen=True)
class BannedNameViolation:
    """One banned standalone name found in one artifact."""

    path: str
    line_number: int
    name: str
    kind: str

    def describe(self) -> str:
        return f"{self.path}:{self.line_number}: banned {self.kind} name: {self.name}"


def iter_python_files(roots: list[Path]) -> list[Path]:
    candidates: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            candidates.append(root)
            continue
        for path in sorted(root.rglob("*.py")):
            if not path.is_file():
                continue
            if any(part in SKIPPED_DIRECTORY_NAMES for part in path.parts):
                continue
            candidates.append(path)
    return candidates


def build_violation(
    relative_path: str,
    name: str,
    kind: str,
    line_number: int,
) -> BannedNameViolation:
    """Build a violation record for one offending name."""
    return BannedNameViolation(
        path=relative_path,
        line_number=line_number,
        name=name,
        kind=kind,
    )


def find_banned_definition_name(node: ast.AST) -> tuple[str, str] | None:
    """Return (name, kind) when a class or function definition is banned."""
    if isinstance(node, ast.ClassDef):
        kind = "class"
    elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        kind = "function"
    else:
        return None
    if node.name.lower() not in BANNED_NAMES:
        return None
    return node.name, kind


def find_banned_assignment_name(node: ast.AST) -> tuple[str, str] | None:
    """Return (name, kind) when a module-level assignment target is banned.

    Only module-level names are inspected. A local variable inside a function is
    ordinary Python and policing it produces noise rather than clarity.
    """
    if getattr(node, "col_offset", None) != 0:
        return None
    if isinstance(node, ast.Assign):
        targets: list[ast.expr] = list(node.targets)
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
    else:
        return None
    for target in targets:
        if isinstance(target, ast.Name) and target.id.lower() in BANNED_NAMES:
            return target.id, "module-level assignment"
    return None


def scan_parsed_module(module: ast.Module, relative_path: str) -> list[BannedNameViolation]:
    """Collect banned names from a parsed module."""
    violations: list[BannedNameViolation] = []
    for node in ast.walk(module):
        definition = find_banned_definition_name(node)
        if definition is not None:
            name, kind = definition
            violations.append(build_violation(relative_path, name, kind, node.lineno))
            continue
        assignment = find_banned_assignment_name(node)
        if assignment is not None:
            name, kind = assignment
            violations.append(build_violation(relative_path, name, kind, node.lineno))
    return violations


def scan_module(path: Path, repository_root: Path) -> list[BannedNameViolation]:
    try:
        relative_path = path.relative_to(repository_root).as_posix()
    except ValueError:
        relative_path = path.as_posix()

    if relative_path in ALLOWED_PATHS:
        return []

    violations: list[BannedNameViolation] = []

    # The module file stem is a standalone name.
    if path.stem.lower() in BANNED_NAMES:
        violations.append(build_violation(relative_path, path.stem, "module", 1))

    try:
        source = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as error:
        print(f"[WARN] could not read {relative_path}: {error}", file=sys.stderr)
        return violations

    try:
        module = ast.parse(source, filename=relative_path)
    except SyntaxError as error:
        violations.append(
            build_violation(relative_path, str(error.msg), "syntax-error", error.lineno or 1)
        )
        return violations

    violations.extend(scan_parsed_module(module, relative_path))
    return violations


def determine_repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: list[str]) -> int:
    repository_root = determine_repository_root()

    if argv:
        roots = [Path(argument).resolve() for argument in argv]
        for root in roots:
            if not root.exists():
                print(f"[FAIL] path does not exist: {root}", file=sys.stderr)
                return 2
    else:
        roots = [repository_root / "backend", repository_root / "web", repository_root / "mobile"]
        roots = [root for root in roots if root.exists()]

    violations: list[BannedNameViolation] = []
    checked_count = 0
    for path in iter_python_files(roots):
        checked_count += 1
        violations.extend(scan_module(path, repository_root))

    if violations:
        print(f"[FAIL] {len(violations)} banned standalone name(s) found")
        for violation in violations:
            print(f"  {violation.describe()}")
        print()
        print("A banned name means the author has not decided what the thing is.")
        print("Name the responsibility: calculate_invoice_total, not handle_data.")
        print("If a longer name contains the word as part of a verb phrase it is")
        print("fine (process_sale); only the standalone name is rejected.")
        return 1

    print(f"[OK] banned-name guard: {checked_count} module(s) checked, no violations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
