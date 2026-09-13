"""Architecture contracts as tests.

The five-layer model is enforced by `backend/import-linter.ini`. Running that
file through a separate tool means an architecture violation only fails a build
if someone remembers to run the tool; this module runs the contracts inside the
ordinary test command, so `pytest` fails the same way `make arch` does.

Two kinds of assertion live here:

1. The real repository keeps every contract.
2. The contracts are not vacuous: a generated package with a deliberate
   outward import is reported as broken. A contract file that silently stopped
   matching anything would be worse than no contract, because the team would
   believe the architecture was protected.
"""

from __future__ import annotations

import configparser
import contextlib
import io
import sys
from pathlib import Path

import pytest
from importlinter.cli import lint_imports

CONTRACT_NAMES = (
    "layer-direction",
    "entities-are-framework-free",
    "schemas-are-wire-contracts",
    "crud-is-persistence-only",
    "services-own-no-transport",
    "routers-stay-thin",
    "core-is-self-contained",
    "middleware-is-self-contained",
    "integrations-are-adapters",
)

LAYER_PACKAGES = (
    "src/ahia/models/entities",
    "src/ahia/schemas",
    "src/ahia/crud",
    "src/ahia/services",
    "src/ahia/routers",
    "src/ahia/core",
    "src/ahia/middleware",
    "src/ahia/integrations",
)


def run_contracts(config_path: Path) -> tuple[int, str]:
    """Run the contracts in-process and return the exit status and the report.

    Caching is disabled and the banner is suppressed so the report is stable and
    the test leaves no cache directory behind in the working tree.
    """
    captured_output = io.StringIO()
    with contextlib.redirect_stdout(captured_output):
        exit_code = lint_imports(
            config_filename=str(config_path),
            no_cache=True,
            no_logo=True,
        )
    return exit_code, captured_output.getvalue()


@pytest.fixture(scope="session")
def contract_config(backend_directory: Path) -> Path:
    return backend_directory / "import-linter.ini"


@pytest.mark.architecture
def test_every_contract_is_defined(contract_config: Path) -> None:
    parser = configparser.ConfigParser()
    parser.read(contract_config)

    defined = {
        section.split(":", maxsplit=2)[2]
        for section in parser.sections()
        if section.startswith("importlinter:contract:")
    }

    assert defined == set(CONTRACT_NAMES)


@pytest.mark.architecture
@pytest.mark.parametrize("relative_path", LAYER_PACKAGES)
def test_layer_package_exists(backend_directory: Path, relative_path: str) -> None:
    """A contract over a missing package would pass while enforcing nothing."""
    package_directory = backend_directory / relative_path

    assert package_directory.is_dir(), f"missing layer package: {relative_path}"
    assert (package_directory / "__init__.py").is_file()


@pytest.mark.architecture
def test_repository_keeps_every_contract(contract_config: Path) -> None:
    exit_code, output = run_contracts(contract_config)

    assert exit_code == 0, output
    assert "Contracts: 9 kept, 0 broken." in output


@pytest.mark.architecture
def test_contracts_detect_a_deliberate_violation(tmp_path: Path) -> None:
    """Prove the contracts are not vacuous.

    A throwaway package is created outside the repository with a persistence
    module importing the service layer, which the real contract forbids. The
    command must report the contract as broken.
    """
    package_root = tmp_path / "packages"
    source_root = package_root / "violationpkg"
    (source_root / "crud").mkdir(parents=True)
    (source_root / "services").mkdir(parents=True)
    (source_root / "__init__.py").write_text('"""Throwaway package."""\n', encoding="utf-8")
    (source_root / "crud" / "__init__.py").write_text(
        '"""Persistence layer that reaches outward on purpose."""\n'
        "from violationpkg.services import complete_sale\n"
        "\n"
        "__all__ = ['complete_sale']\n",
        encoding="utf-8",
    )
    (source_root / "services" / "__init__.py").write_text(
        '"""Service layer."""\n\n\ndef complete_sale() -> None:\n    """Business operation."""\n',
        encoding="utf-8",
    )

    config_path = tmp_path / "import-linter.ini"
    config_path.write_text(
        "[importlinter]\n"
        "root_package = violationpkg\n"
        "\n"
        "[importlinter:contract:crud-is-persistence-only]\n"
        "name = Persistence does not import logic\n"
        "type = forbidden\n"
        "source_modules =\n"
        "    violationpkg.crud\n"
        "forbidden_modules =\n"
        "    violationpkg.services\n",
        encoding="utf-8",
    )

    import_path = str(package_root)
    sys.path.insert(0, import_path)
    try:
        exit_code, output = run_contracts(config_path)
    finally:
        sys.path.remove(import_path)
        for module_name in list(sys.modules):
            if module_name.startswith("violationpkg"):
                del sys.modules[module_name]

    assert exit_code != 0, output
    assert "Persistence does not import logic" in output
    assert "violationpkg.crud is not allowed to import violationpkg.services" in output
