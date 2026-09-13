"""Where provider names are allowed to exist.

The storage architecture is only real if the boundary is mechanical. This test
walks the source tree and asserts where a provider identifier may appear, so a
service that grows a provider-specific branch fails the build rather than a
review.

Allowed:

* the adapter modules (`r2_client.py`, `cloudinary_client.py`), because that is
  what an adapter is for
* `storage_factory.py`, whose entire job is to select one
* `core/config.py`, which declares the provider enum and reads its credentials
* the environment template, the documentation and the tests

Forbidden everywhere else: a provider name, a vendor SDK import, a bucket name,
or any of the vendor's vocabulary.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ahia.core.database import Base
from ahia.crud.table_registry import import_all_record_modules

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "ahia"

#: Provider vocabulary that must not appear outside the boundary.
PROVIDER_IDENTIFIERS = (
    "cloudinary",
    "boto3",
    "botocore",
    "cloudflarestorage",
    "public_id",
    "s3_client",
)

#: Modules permitted to contain provider vocabulary, with the reason.
BOUNDARY_MODULES = frozenset(
    {
        "integrations/storage/r2_client.py",
        "integrations/storage/cloudinary_client.py",
        "integrations/storage/storage_factory.py",
        "core/config.py",
        # The redaction rules know provider credential URL shapes by name, which
        # is exactly what makes them able to redact one. This is a security rule
        # about vendors, not a dependency on one.
        "core/logging.py",
    }
)

#: Layers that must never learn a provider exists.
PROVIDER_UNAWARE_LAYERS = ("services", "routers", "models", "schemas", "crud", "middleware")


def relative_source_paths() -> list[Path]:
    return sorted(path for path in SOURCE_ROOT.rglob("*.py") if "__pycache__" not in path.parts)


def relative_name(path: Path) -> str:
    return path.relative_to(SOURCE_ROOT).as_posix()


@pytest.mark.architecture
def test_provider_vocabulary_confined_to_the_boundary() -> None:
    offenders: list[str] = []

    for path in relative_source_paths():
        name = relative_name(path)
        if name in BOUNDARY_MODULES:
            continue
        content = path.read_text(encoding="utf-8").lower()
        for identifier in PROVIDER_IDENTIFIERS:
            if identifier in content:
                offenders.append(f"{name} contains {identifier!r}")

    assert not offenders, "a provider identifier escaped the storage boundary:\n  " + "\n  ".join(
        offenders
    )


@pytest.mark.architecture
def test_ports_are_provider_neutral() -> None:
    """The contract a service depends on must not name a vendor."""
    for path in sorted((SOURCE_ROOT / "core" / "ports").glob("*.py")):
        content = path.read_text(encoding="utf-8").lower()
        for identifier in PROVIDER_IDENTIFIERS:
            assert identifier not in content, f"{path.name} names the provider {identifier!r}"


@pytest.mark.architecture
def test_provider_unaware_layers_do_not_import_adapters() -> None:
    """A service may depend on the port; it may not reach for an adapter."""
    offenders: list[str] = []

    for layer in PROVIDER_UNAWARE_LAYERS:
        layer_directory = SOURCE_ROOT / layer
        if not layer_directory.is_dir():
            continue
        for path in sorted(layer_directory.rglob("*.py")):
            content = path.read_text(encoding="utf-8")
            for forbidden in (
                "ahia.integrations.storage.r2_client",
                "ahia.integrations.storage.cloudinary_client",
                "ahia.integrations.storage.storage_factory",
            ):
                if forbidden in content:
                    offenders.append(f"{relative_name(path)} imports {forbidden}")

    assert not offenders, (
        "a layer imported a storage adapter instead of the port:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.architecture
def test_storage_factory_is_the_only_selector() -> None:
    """One place branching on the provider keeps switching a configuration change."""
    selector_occurrences: list[str] = []

    for path in relative_source_paths():
        name = relative_name(path)
        if name in {"integrations/storage/storage_factory.py", "core/config.py"}:
            continue
        content = path.read_text(encoding="utf-8")
        if "StorageProviderName.R2" in content or "StorageProviderName.CLOUDINARY" in content:
            selector_occurrences.append(name)

    assert not selector_occurrences, (
        "provider selection leaked outside the factory and the configuration: "
        + ", ".join(selector_occurrences)
    )


@pytest.mark.architecture
def test_no_database_column_is_named_after_a_provider() -> None:
    """The schema records where bytes live without recording who is storing them.

    A column named `r2_key` would make a provider change a migration, and every row
    written before it would describe its location in terms of a provider that may no
    longer be the one holding it. `storage_provider` and `storage_key` are the neutral
    pair; this test is what stops the vendor's name reappearing in a column.
    """
    import_all_record_modules()

    forbidden = ("r2", "cloudinary", "s3", "bucket")
    offenders: list[str] = []

    for table_name, table in sorted(Base.metadata.tables.items()):
        for column in table.columns:
            for term in forbidden:
                if term in column.name.lower():
                    offenders.append(f"{table_name}.{column.name}")

    assert not offenders, (
        "a database column is named after a storage provider or a vendor concept:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.architecture
def test_boundary_modules_exist() -> None:
    """A boundary test over missing files would pass while enforcing nothing."""
    for relative in BOUNDARY_MODULES:
        assert (SOURCE_ROOT / relative).is_file(), f"missing boundary module: {relative}"
