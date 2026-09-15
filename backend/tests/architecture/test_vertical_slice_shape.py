"""Structural checks on how the vertical slices are named and assembled.

The five-layer model is only useful if every slice looks the same. A reader who
has understood one entity must be able to find the same five files for the next
one, and a new contributor must be able to infer the layout instead of asking.

These tests enforce the naming rule and the presence of the entity behind each
outer file. They do not check behaviour; behaviour is checked at the layer it
belongs to.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "ahia"

#: The layer file suffixes, in dependency order. A slice without its entity has no
#: source of truth, which is the failure this test exists to catch.
LAYER_DIRECTORIES: dict[str, str] = {
    "schemas": "_schema.py",
    "crud": "_crud.py",
    "services": "_service.py",
    "routers": "_router.py",
}

#: Files named after a use case rather than an entity. The preset allows this
#: deliberately: an operation that spans entities is named after the operation, and
#: forcing it to borrow an entity name would either invent a table or mislead a
#: reader about what the file owns.
USE_CASE_MODULES: frozenset[str] = frozenset(
    {
        # Spans the user, the session and their credentials.
        "schemas/auth_schema.py",
        "services/auth_service.py",
        "routers/auth_router.py",
        # Coordinates quota accounting across the product-image use case; there is
        # no `storage_quota` table and there should not be one.
        "services/storage_quota_service.py",
        # Provisions the declared permission registry into the database. It spans
        # permissions, roles and grants, and it is named after what it does.
        "services/iam_seed_service.py",
        # Offline synchronization spans the operation record, the device cursor and the change
        # feed, and coordinates use cases rather than owning a table of its own. Forcing one of
        # the three names onto it would mislead the reader about what the file owns.
        "schemas/sync_schema.py",
        "services/sync_service.py",
        "routers/sync_router.py",
        # Reports read the sales, the lines, the catalogue and the stock projection and answer a
        # question. They own no table, and naming the file after one of the tables they read would
        # tell a reader it owns that table.
        "schemas/report_schema.py",
        "services/report_service.py",
        "routers/report_router.py",
    }
)

#: Files that belong to the process rather than to the domain.
OPERATIONAL_MODULES: frozenset[str] = frozenset(
    {
        # Liveness and readiness are properties of the running process, not of a
        # business entity. Giving them a model would invent a domain concept to
        # satisfy a naming rule.
        "routers/health_router.py",
    }
)

FILES_WITHOUT_AN_ENTITY: frozenset[str] = USE_CASE_MODULES | OPERATIONAL_MODULES


def layer_files(layer: str, suffix: str) -> list[Path]:
    directory = SOURCE_ROOT / layer
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.glob(f"*{suffix}")
        if "__pycache__" not in path.parts and path.name != "__init__.py"
    )


def entity_files() -> set[str]:
    return {
        path.stem.removesuffix("_model") for path in layer_files("models/entities", "_model.py")
    }


@pytest.mark.architecture
def test_every_layer_file_names_the_entity_it_belongs_to() -> None:
    """An outer layer file must have an entity, or it has no source of truth."""
    available_entities = entity_files()
    offenders: list[str] = []

    for layer, suffix in LAYER_DIRECTORIES.items():
        for path in layer_files(layer, suffix):
            relative = f"{layer}/{path.name}"
            if relative in FILES_WITHOUT_AN_ENTITY:
                continue
            entity_name = path.stem.removesuffix(suffix.removesuffix(".py"))
            if entity_name not in available_entities:
                offenders.append(f"{relative} has no models/entities/{entity_name}_model.py")

    assert not offenders, "an outer layer file has no entity behind it:\n  " + "\n  ".join(
        offenders
    )


@pytest.mark.architecture
def test_the_documented_exceptions_still_exist() -> None:
    """An exemption list that outlives its files is a list that hides a real gap."""
    for relative in FILES_WITHOUT_AN_ENTITY:
        assert (SOURCE_ROOT / relative).is_file(), f"stale exemption: {relative}"


@pytest.mark.architecture
def test_the_user_slice_has_all_five_layers() -> None:
    """The template every future entity copies must itself be complete."""
    expected = {
        "models/entities/user_model.py",
        "schemas/user_schema.py",
        "crud/user_crud.py",
        "services/user_service.py",
        "routers/user_router.py",
    }

    present = {relative for relative in expected if (SOURCE_ROOT / relative).is_file()}

    assert present == expected, f"missing from the user slice: {sorted(expected - present)}"


@pytest.mark.architecture
def test_no_layer_uses_a_banned_file_name() -> None:
    """A file named for a layer rather than a responsibility is a dumping ground.

    The names checked here are the ones the preset rejects outright. The
    repository-wide guard already covers the whole tree; this test states the rule
    for the source tree specifically, so a violation fails the architecture suite
    as well as the hygiene gate.
    """
    banned_names = {
        "utils.py",
        "helpers.py",
        "common.py",
        "misc.py",
        "manager.py",
        "helper.py",
        "data.py",
        "info.py",
    }

    offenders = [
        path.relative_to(SOURCE_ROOT).as_posix()
        for path in SOURCE_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts and path.name in banned_names
    ]

    assert offenders == []


@pytest.mark.architecture
def test_migrations_and_models_are_separate_concerns() -> None:
    """No entity module may contain an ORM class.

    The domain is framework-free and the persistence representation lives in CRUD.
    A declarative class in the entity layer would end that separation, and it is a
    mistake that is easy to make and hard to notice.
    """
    offenders: list[str] = []

    for path in layer_files("models/entities", "_model.py"):
        source = path.read_text(encoding="utf-8")
        if "DeclarativeBase" in source or "mapped_column" in source:
            offenders.append(path.name)

    assert offenders == [], f"an entity module contains persistence code: {offenders}"
