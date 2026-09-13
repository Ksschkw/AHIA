"""Purity of the two core modules the entity layer is allowed to import.

ADR-0010 permits entities to import `core.errors` and `core.permissions`. That
permission is conditional: both must stay pure - standard library only, no
configuration, no I/O - or an entity that imports them stops being a domain object
and starts being an application object.

The condition is checked here rather than trusted, because an allowance that
quietly widens is how a layered architecture erodes.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "ahia"

#: The modules an entity may import from core, and the only ones.
PERMITTED_CORE_IMPORTS = ("core/errors.py", "core/permissions")

#: Standard-library modules these files may use. Anything else is a dependency the
#: domain layer did not agree to.
PERMITTED_STANDARD_LIBRARY = frozenset(
    {
        "__future__",
        "collections",
        "contextlib",
        "contextvars",
        "dataclasses",
        "datetime",
        "enum",
        "re",
        "types",
        "typing",
        "uuid",
    }
)


def permitted_files() -> list[Path]:
    files = [SOURCE_ROOT / "core" / "errors.py"]
    files.extend(sorted((SOURCE_ROOT / "core" / "permissions").glob("*.py")))
    return [path for path in files if path.is_file() and "__pycache__" not in path.parts]


def imported_top_level_modules(path: Path) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    return imported


@pytest.mark.architecture
def test_permitted_core_modules_import_standard_library_only() -> None:
    offenders: list[str] = []

    for path in permitted_files():
        for module in imported_top_level_modules(path):
            if module in PERMITTED_STANDARD_LIBRARY or module == "ahia":
                continue
            offenders.append(f"{path.name} imports {module}")

    assert not offenders, (
        "a module the entity layer depends on acquired a dependency:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.architecture
def test_permitted_core_modules_import_no_application_layer() -> None:
    offenders: list[str] = []

    for path in permitted_files():
        source = path.read_text(encoding="utf-8")
        for forbidden in (
            "ahia.models",
            "ahia.schemas",
            "ahia.crud",
            "ahia.services",
            "ahia.routers",
            "ahia.middleware",
            "ahia.integrations",
            "ahia.bootstrap",
            "ahia.core.config",
            "ahia.core.database",
            "ahia.core.logging",
            "ahia.core.resilience",
            "ahia.core.security",
            "ahia.core.tenant_context",
            "ahia.core.ports",
        ):
            if forbidden in source:
                offenders.append(f"{path.name} references {forbidden}")

    assert not offenders, "a permitted core module reached outside the domain:\n  " + "\n  ".join(
        offenders
    )


@pytest.mark.architecture
def test_the_permitted_list_matches_what_entities_actually_import() -> None:
    """The allowance and the contract file must agree, or one of them is stale."""
    contract = (Path(__file__).resolve().parents[2] / "import-linter.ini").read_text(
        encoding="utf-8"
    )
    entity_contract = contract.split("[importlinter:contract:entities-are-framework-free]")[1]
    entity_contract = entity_contract.split("[importlinter:contract:", maxsplit=1)[0]

    # Only the module list matters: the surrounding comment names both permitted
    # modules, and a text search over the whole section would match the comment.
    forbidden_block = entity_contract.split("forbidden_modules =", maxsplit=1)[1]
    forbidden_entries = {
        line.strip() for line in forbidden_block.splitlines() if line.strip().startswith("ahia")
    }

    assert "ahia.core.errors" not in forbidden_entries
    assert "ahia.core.permissions" not in forbidden_entries
    for forbidden in ("ahia.core.config", "ahia.core.database", "ahia.core.logging"):
        assert forbidden in forbidden_entries
