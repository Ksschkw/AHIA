"""Only the configuration module may read the environment.

This is the rule that makes a setting findable. A value read through `os.getenv`
in a service is invisible to the configuration module, undocumented in the
environment template, and impossible to change safely: two readers with two
different defaults disagree, and the disagreement only shows up in production.

The check is an AST scan rather than a text search, so a string that merely
mentions `os.getenv` in a docstring is not a violation while a real call is.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "ahia"

#: The single module permitted to read the environment.
CONFIGURATION_MODULE = "core/config.py"

#: Environment-reading calls, as (module, attribute) pairs.
FORBIDDEN_ENVIRONMENT_CALLS = {
    ("os", "getenv"),
    ("os", "environ"),
    ("os", "putenv"),
    ("dotenv", "load_dotenv"),
    ("dotenv", "dotenv_values"),
}


def source_modules() -> list[Path]:
    return sorted(path for path in SOURCE_ROOT.rglob("*.py") if "__pycache__" not in path.parts)


def relative_name(path: Path) -> str:
    return path.relative_to(SOURCE_ROOT).as_posix()


def environment_accesses(tree: ast.AST) -> list[str]:
    """Return every environment-reading expression found in a parsed module."""
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if (node.value.id, node.attr) in FORBIDDEN_ENVIRONMENT_CALLS:
                found.append(f"{node.value.id}.{node.attr}")
        elif isinstance(node, ast.ImportFrom) and node.module in {"dotenv"}:
            found.append(f"import from {node.module}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "dotenv":
                    found.append("import dotenv")
    return found


@pytest.mark.architecture
def test_environment_is_read_only_by_the_configuration_module() -> None:
    offenders: list[str] = []

    for path in source_modules():
        name = relative_name(path)
        if name == CONFIGURATION_MODULE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=name)
        for access in environment_accesses(tree):
            offenders.append(f"{name} uses {access}")

    assert not offenders, "the environment was read outside core/config.py:\n  " + "\n  ".join(
        offenders
    )


@pytest.mark.architecture
def test_the_configuration_module_exists_and_is_the_documented_one() -> None:
    assert (SOURCE_ROOT / CONFIGURATION_MODULE).is_file()


@pytest.mark.architecture
def test_configuration_is_injected_rather_than_imported_as_a_singleton() -> None:
    """No module may build its own settings object outside the root and tests.

    Construction is permitted in the composition root, which owns it, and in the
    application factory, which is handed settings or loads them once.
    """
    permitted = {"core/config.py", "bootstrap.py", "main.py"}
    offenders: list[str] = []

    for path in source_modules():
        name = relative_name(path)
        if name in permitted:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=name)
        for node in ast.walk(tree):
            is_settings_construction = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"Settings", "load_settings"}
            )
            if is_settings_construction:
                offenders.append(f"{name} constructs {node.func.id}")

    assert not offenders, (
        "a module built its own configuration instead of receiving it:\n  " + "\n  ".join(offenders)
    )
