"""Verification of the migration baseline.

Three questions, all of which a migration must answer before anybody trusts it.

Does a fresh database reach the schema the models describe?
Does the migration come back down, so a rollout can be reversed?
Does an autogenerate run afterwards find nothing, meaning the migration and the
models agree?

The third is the one that catches drift in the months between releases: if the
models change and the migration does not, the answer stops being "nothing" and
this test says so.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.crud.table_registry import import_all_record_modules

BACKEND_DIRECTORY = Path(__file__).resolve().parents[2]

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)

#: Every table the baseline owns. Listed explicitly rather than derived from the
#: metadata, so that a table quietly dropped from a migration fails here instead of
#: passing against a shortened expectation.
EXPECTED_TABLES = frozenset(
    {
        "users",
        "user_sessions",
        "tenants",
        "tenant_memberships",
        "membership_invitations",
        "devices",
        "roles",
        "permissions",
        "role_permissions",
        "tenant_storage_usage",
        "categories",
        "products",
        "product_images",
        "inventory",
        "inventory_movements",
    }
)


def resolve_test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)


def build_settings() -> Settings:
    """Build settings for the migration tests.

    The URL is read from the environment because migrations read it the same way the
    application does: ``alembic/env.py`` loads settings, and settings load the
    environment. A migration test pointed at any other database would be an
    expensive mistake, so this never falls back to a development default beyond the
    local test database.
    """
    return Settings(
        _env_file=None,
        app_env=AppEnvironment.TEST,
        database_url=resolve_test_database_url(),
        jwt_secret="test-signing-secret-value-0000000001",
        refresh_token_pepper="test-refresh-pepper-value-00000000011",
        storage_provider=StorageProviderName.R2,
        r2_endpoint="https://account.r2.cloudflarestorage.com",
        r2_access_key_id="r2-access-key",
        r2_secret_access_key="r2-secret-key",
        r2_bucket="ahia-test",
    )


#: The environment a migration run needs, as variable names and test values.
#:
#: Migrations load the same settings object the application loads, so they need the
#: same variables. None of these is a real credential: they are the values the test
#: database and a throwaway key pair are addressed with.
MIGRATION_ENVIRONMENT = {
    "APP_ENV": "test",
    "JWT_SECRET": "test-signing-secret-value-0000000001",
    "REFRESH_TOKEN_PEPPER": "test-refresh-pepper-value-00000000011",
    "STORAGE_PROVIDER": "r2",
    "R2_ENDPOINT": "https://account.r2.cloudflarestorage.com",
    "R2_ACCESS_KEY_ID": "r2-access-key",
    "R2_SECRET_ACCESS_KEY": "r2-secret-key",
    "R2_BUCKET": "ahia-test",
}


@contextlib.contextmanager
def migration_environment() -> Iterator[None]:
    """Apply the migration environment, then put the previous one back.

    ``DATABASE_URL`` is set here rather than in ``alembic.ini`` because the migration
    environment reads it through application settings - which is the point: no
    credential is committed. Restoring every variable afterwards keeps this from
    leaking into tests that assert on environment handling.
    """
    previous = {name: os.environ.get(name) for name in MIGRATION_ENVIRONMENT}
    previous["DATABASE_URL"] = os.environ.get("DATABASE_URL")
    os.environ.update(MIGRATION_ENVIRONMENT)
    os.environ["DATABASE_URL"] = resolve_test_database_url()
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@pytest.fixture
def alembic_configuration() -> Iterator[Config]:
    """Hand Alembic a configuration pointed at the script directory.

    The URL itself arrives through the environment in ``migration_environment``.
    """
    with migration_environment():
        configuration = Config(str(BACKEND_DIRECTORY / "alembic.ini"))
        configuration.set_main_option("script_location", str(BACKEND_DIRECTORY / "alembic"))
        yield configuration


@pytest.fixture
async def database() -> Any:
    instance = Database(build_settings())
    try:
        yield instance
    finally:
        await instance.dispose()


async def drop_everything(database: Database) -> None:
    """Return the database to the state a brand-new deployment finds it in.

    Every table the baseline owns is dropped, plus the revision marker, so each test
    starts from genuinely nothing rather than from whatever the previous test left.
    """
    import_all_record_modules()
    quoted_names = ", ".join(f'"{name}"' for name in sorted(EXPECTED_TABLES))
    async with database.engine.begin() as connection:
        await connection.execute(text(f"DROP TABLE IF EXISTS {quoted_names} CASCADE"))
        await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))


async def existing_tables(database: Database) -> set[str]:
    async with database.engine.begin() as connection:
        result = await connection.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        return {str(row[0]) for row in result.all()}


# Alembic drives migrations with ``asyncio.run`` inside ``alembic/env.py``, and
# ``asyncio.run`` refuses to start from inside a running event loop. These two
# helpers therefore hand the command to a worker thread, which has no loop of its
# own. The alternative would be to give the tests their own copy of the migration
# environment, and a test that runs a different environment from the one production
# runs proves nothing.
async def upgrade(configuration: Config) -> None:
    await asyncio.to_thread(command.upgrade, configuration, "head")


async def downgrade(configuration: Config) -> None:
    await asyncio.to_thread(command.downgrade, configuration, "base")


@pytest.mark.integration
async def test_upgrade_from_empty_creates_every_table(
    alembic_configuration: Config, database: Database
) -> None:
    await drop_everything(database)

    await upgrade(alembic_configuration)

    tables = await existing_tables(database)
    assert tables >= EXPECTED_TABLES, f"missing: {sorted(EXPECTED_TABLES - tables)}"
    assert "alembic_version" in tables, "the revision marker was not written"


@pytest.mark.integration
async def test_downgrade_returns_to_an_empty_database(
    alembic_configuration: Config, database: Database
) -> None:
    """A migration that cannot come down cannot be rolled back during an incident."""
    await drop_everything(database)
    await upgrade(alembic_configuration)

    await downgrade(alembic_configuration)

    survivors = EXPECTED_TABLES & await existing_tables(database)
    assert survivors == set(), f"tables survived the downgrade: {sorted(survivors)}"


@pytest.mark.integration
async def test_upgrade_and_downgrade_are_repeatable(
    alembic_configuration: Config, database: Database
) -> None:
    """The up-down-up sequence a developer runs on a branch must not fail."""
    await drop_everything(database)

    await upgrade(alembic_configuration)
    await downgrade(alembic_configuration)
    await upgrade(alembic_configuration)

    assert await existing_tables(database) >= EXPECTED_TABLES


@pytest.mark.integration
async def test_the_migration_matches_the_models(
    alembic_configuration: Config, database: Database
) -> None:
    """The drift check: an autogenerate run after the migration must find nothing.

    This is what catches the case that matters months from now - a model changed
    without a migration - and it is asserted rather than left to review.
    """
    import_all_record_modules()
    await drop_everything(database)
    await upgrade(alembic_configuration)

    def compare(sync_connection: Any) -> list[Any]:
        context = MigrationContext.configure(
            sync_connection,
            opts={"compare_type": True, "compare_server_default": True},
        )
        return list(compare_metadata(context, Base.metadata))

    async with database.engine.connect() as connection:
        differences = await connection.run_sync(compare)

    assert differences == [], (
        "the migration and the models disagree; run "
        f"alembic revision --autogenerate and review: {differences}"
    )


@pytest.mark.unit
def test_the_migration_history_is_one_linear_chain() -> None:
    """Every revision has at most one parent, and exactly one head exists.

    A branch point or a second head means two developers generated revisions from the
    same parent, and `alembic upgrade head` then fails on a database that has already
    applied one of them. That is worth failing here rather than in a deployment.
    """
    revisions: dict[str, str | None] = {}
    for path in migration_files():
        assignments = _revision_assignments(path)
        revisions[assignments["revision"]] = assignments["down_revision"]

    assert revisions, "no migration revisions found"

    parents = {parent for parent in revisions.values() if parent is not None}
    for parent in parents:
        assert parent in revisions, f"a revision names an unknown parent: {parent}"

    heads = sorted(set(revisions) - parents)
    assert len(heads) == 1, f"expected exactly one head, found: {heads}"
    assert revisions["ae15ce60c835"] is None, "the baseline must have no parent"


def migration_files() -> list[Path]:
    return sorted(
        path
        for path in (BACKEND_DIRECTORY / "alembic" / "versions").glob("*.py")
        if not path.name.startswith("__")
    )


def _revision_assignments(path: Path) -> dict[str, str | None]:
    """Read a revision's identity without importing the module.

    Parsed rather than imported: importing every revision executes module-level code
    in a migration, which is not something a test about the history needs to do.
    """
    found: dict[str, str | None] = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id not in {"revision", "down_revision"}:
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            found[node.target.id] = value.value
        elif isinstance(value, ast.Constant) and value.value is None:
            found[node.target.id] = None
        else:
            found[node.target.id] = None
    assert "revision" in found, f"{path.name} declares no revision identifier"
    found.setdefault("down_revision", None)
    return found


@pytest.mark.security
def test_no_credential_appears_in_the_alembic_configuration() -> None:
    """A database URL in a committed file is a credential in version control."""
    configuration = (BACKEND_DIRECTORY / "alembic.ini").read_text(encoding="utf-8")

    for forbidden in ("postgresql", "password", "secret", "host="):
        assert forbidden not in configuration.lower(), (
            f"alembic.ini contains {forbidden!r}; the URL belongs in the environment"
        )
