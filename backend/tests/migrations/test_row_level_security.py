"""Verification of the Row-Level Security policies.

The application scopes every query by `tenant_id`, and this module is about the second line: the
database refusing to return another business's rows even when a query forgets to filter. A policy
that is never verified is a policy everybody believes is protecting them.

**The suite usually runs as a role that bypasses policies, and that is not a reason to skip this.**
The migration sets `FORCE ROW LEVEL SECURITY`, but a *superuser* is exempt regardless - and the
local development role is one - so a test that read these tables as the ordinary test connection
would pass whether or not a single policy existed. Every behavioural assertion here therefore runs
through a dedicated unprivileged probe role (`ahia_rls_probe`: login, no superuser, no bypass),
granted exactly what the application is granted. The role is created with a random password for the
duration of the run and carries no fixed credential.

Three assertions per table, as the rollout plan requires:

1. Without a scope, a query returns nothing - with rows present in the database.
2. With a scope, a query returns exactly that business's rows.
3. A cross-tenant read by primary key returns nothing.

Two more are made here because they are the failures that are invisible in review:

- a transaction that borrows a pooled connection after a scoped one must return no rows rather
  than raise, because PostgreSQL leaves the setting defined as an empty string after `SET LOCAL`
  commits and `''::uuid` is an error, not an absence.
- the policy text must be identical on every scoped table, and absent on every table that was
  deliberately left out.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import TENANT_SCOPE_SETTING, Database
from ahia.core.errors import NotFoundError
from ahia.core.tenant_scope import tenant_scope
from ahia.crud import category_crud, customer_crud, ledger_entry_crud, tenant_crud
from ahia.models.entities.category_model import CategoryModel
from ahia.models.entities.customer_model import CustomerModel
from ahia.models.entities.ledger_entry_model import LedgerEntryModel, LedgerEntryType
from ahia.models.entities.tenant_model import TenantModel

BACKEND_DIRECTORY = Path(__file__).resolve().parents[2]

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)

#: The unprivileged role every behavioural assertion runs as. Named here rather than taken from the
#: migration: the migration creates policies, it does not create roles, and a role that only exists
#: because a test needed one must not become part of the deployment.
PROBE_ROLE_NAME = "ahia_rls_probe"

#: The tables the migration is expected to scope. Listed explicitly rather than read from the
#: migration module, so that dropping a table from the migration fails here instead of passing
#: against a shortened expectation.
EXPECTED_SCOPED_TABLES = (
    "ledger_entries",
    "audit_events",
    "inventory_movements",
    "payments",
    "sales",
    "sale_items",
    "receipt_counters",
    "expenses",
    "customers",
    "products",
    "product_images",
    "categories",
    "inventory",
    "notifications",
    "report_exports",
    "storefronts",
    "tenant_storage_usage",
    "sync_changes",
    "sync_cursors",
    "sync_operations",
)

#: The tables deliberately left without a policy, each for a reason recorded in the migration and in
#: `docs/RLS_ROLLOUT.md`. A policy appearing on one of these is a bug in the shape of a security
#: improvement: it would break public addresses, membership resolution or share links.
EXPECTED_UNSCOPED_TABLES = (
    "tenants",
    "users",
    "user_sessions",
    "devices",
    "tenant_memberships",
    "membership_invitations",
    "share_links",
    "roles",
    "permissions",
    "role_permissions",
    "alembic_version",
)

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


def resolve_test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)


def build_settings(**overrides: Any) -> Settings:
    baseline: dict[str, Any] = {
        "_env_file": None,
        "app_env": AppEnvironment.TEST,
        "database_url": resolve_test_database_url(),
        "jwt_secret": "test-signing-secret-value-0000000001",
        "refresh_token_pepper": "test-refresh-pepper-value-00000000011",
        "storage_provider": StorageProviderName.R2,
        "r2_endpoint": "https://account.r2.cloudflarestorage.com",
        "r2_access_key_id": "r2-access-key",
        "r2_secret_access_key": "r2-secret-key",
        "r2_bucket": "ahia-test",
    }
    baseline.update(overrides)
    return Settings(**baseline)


@contextlib.contextmanager
def migration_environment() -> Iterator[None]:
    """Apply the environment a migration run needs, then put the previous one back."""
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


async def _drop_everything(settings: Settings) -> None:
    """Empty the public schema, so the migration is what creates it."""
    database = Database(settings)
    try:
        async with database.engine.begin() as connection:
            rows = await connection.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                    "AND tablename <> 'alembic_version'"
                )
            )
            names = ", ".join(f'"{row[0]}"' for row in rows.all())
            if names:
                await connection.execute(text(f"DROP TABLE IF EXISTS {names} CASCADE"))
            await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    finally:
        await database.dispose()


@pytest.fixture(scope="module", autouse=True)
def migrated_schema() -> Iterator[None]:
    """Reach the migrated state once per module.

    The policies only exist after the migration has run, so the tests cannot be written against
    whatever schema happened to be in the test database. Rebuilding it here also means this module
    verifies the migration itself, not a state somebody applied by hand.
    """
    settings = build_settings()
    with migration_environment():
        configuration = Config(str(BACKEND_DIRECTORY / "alembic.ini"))
        configuration.set_main_option("script_location", str(BACKEND_DIRECTORY / "alembic"))
        asyncio.run(_drop_everything(settings))
        command.upgrade(configuration, "head")
    yield


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    """The test database, as the role that owns the tables."""
    instance = Database(build_settings())
    try:
        yield instance
    finally:
        await instance.dispose()


async def provision_probe_role(database: Database) -> str:
    """Create the unprivileged role and return the password generated for it.

    The password is random per run and never written to a file: a fixed credential in a test module
    is still a committed credential, and the scanner is right to fail the build over one.
    """
    password = secrets.token_urlsafe(24)
    async with database.engine.begin() as connection:
        exists = await connection.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": PROBE_ROLE_NAME}
        )
        if exists.scalar() is None:
            await connection.execute(
                text(
                    f'CREATE ROLE "{PROBE_ROLE_NAME}" LOGIN NOSUPERUSER '
                    "NOCREATEDB NOCREATEROLE NOBYPASSRLS"
                )
            )
        # A password cannot be a bind parameter in ALTER ROLE, so it is quoted here. The value comes
        # from `secrets.token_urlsafe`, whose alphabet contains no quote, and it is escaped anyway.
        escaped_password = password.replace("'", "''")
        await connection.execute(
            text(f"ALTER ROLE \"{PROBE_ROLE_NAME}\" WITH PASSWORD '{escaped_password}'")
        )
        await connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{PROBE_ROLE_NAME}"'))
        # Exactly what the application is granted, and nothing more: this role must be able to do
        # ordinary work so that a refusal can only come from a policy.
        await connection.execute(
            text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
                f'TO "{PROBE_ROLE_NAME}"'
            )
        )
    return password


@pytest.fixture
async def probe_database(database: Database) -> AsyncIterator[Database]:
    """A connection pool as a role the policies actually bind.

    Skipped when the test role cannot create a role of its own, which is the one environment where
    the property genuinely cannot be observed. When that happens the answer is a skip with the
    reason attached, never a green test that proved nothing.
    """
    try:
        password = await provision_probe_role(database)
    except ProgrammingError as error:
        pytest.skip(f"cannot create the unprivileged probe role here: {error.orig}")

    probe_url = make_url(resolve_test_database_url()).set(
        username=PROBE_ROLE_NAME, password=password
    )
    instance = Database(
        build_settings(database_url=probe_url.render_as_string(hide_password=False))
    )
    try:
        yield instance
    finally:
        await instance.dispose()


async def seed_tenant(database: Database, name: str) -> UUID:
    """Insert one business as the table owner."""
    tenant_id = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await tenant_crud.create(
            unit_of_work.session_handle,
            TenantModel.create(
                tenant_id=tenant_id,
                name=name,
                slug=f"{name.lower().replace(' ', '-')}-{tenant_id.hex[:8]}",
                now=NOW,
            ),
        )
        await unit_of_work.commit()
    return tenant_id


async def seed_customer(database: Database, *, tenant_id: UUID, name: str) -> UUID:
    customer = CustomerModel.create(
        customer_id=uuid4(),
        tenant_id=tenant_id,
        name=name,
        now=NOW,
        phone="+2348031234567",
    )
    async with database.transaction_scope() as unit_of_work:
        await customer_crud.create(unit_of_work.session_handle, customer)
        await unit_of_work.commit()
    return customer.id


async def seed_category(database: Database, *, tenant_id: UUID, name: str) -> UUID:
    category = CategoryModel.create(
        category_id=uuid4(),
        tenant_id=tenant_id,
        name=name,
        now=NOW,
    )
    async with database.transaction_scope() as unit_of_work:
        await category_crud.create(unit_of_work.session_handle, category)
        await unit_of_work.commit()
    return category.id


async def seed_ledger_entry(database: Database, *, tenant_id: UUID) -> UUID:
    """Append one financial entry, which is the one table a leak would be unrecoverable in."""
    entry = LedgerEntryModel.record(
        entry_id=uuid4(),
        tenant_id=tenant_id,
        entry_type=LedgerEntryType.SALE_REVENUE,
        amount=Decimal("10.00"),
        reference_type="sale",
        reference_id=uuid4(),
        now=NOW,
    )
    async with database.transaction_scope() as unit_of_work:
        await ledger_entry_crud.record(unit_of_work.session_handle, entry)
        await unit_of_work.commit()
    return entry.id


@dataclass(frozen=True, slots=True)
class IsolationProbe:
    """One table, with a row belonging to each of two businesses."""

    table_name: str
    first_tenant_id: UUID
    first_row_id: UUID
    second_tenant_id: UUID
    second_row_id: UUID


@dataclass(frozen=True, slots=True)
class Visibility:
    """What a query can see, for each of the three assertions."""

    without_scope: int
    within_scope: int
    other_business_rows_visible_as_own: int
    cross_tenant_read_by_identifier: int


async def scalar_count(
    database: Database, statement: str, parameters: dict[str, Any] | None = None
) -> int:
    """Run a count through the unit of work, which is what applies the scope."""
    async with database.transaction_scope() as unit_of_work:
        result = await unit_of_work.session_handle.execute(text(statement), parameters or {})
        return int(result.scalar_one())


def count_statement(table_name: str, *, where: str = "") -> str:
    """Return a count statement for one of the tables this module expects to be scoped.

    The table name is interpolated because an SQL identifier cannot be a bind parameter. It is
    checked against this module's own list first and never comes from input, and the `where` clauses
    are constants written at the call sites below - which is the whole reason the interpolation is
    acceptable here and nowhere else.
    """
    assert table_name in EXPECTED_SCOPED_TABLES, f"unexpected table in a probe: {table_name}"
    clause = f" WHERE {where}" if where else ""
    return f'SELECT count(*) FROM "{table_name}"{clause}'  # noqa: S608 - identifier from a closed list


async def read_visibility(probe_database: Database, probe: IsolationProbe) -> Visibility:
    """Ask the three questions of one table, as a role the policies bind."""
    without_scope = await scalar_count(probe_database, count_statement(probe.table_name))
    with tenant_scope(probe.first_tenant_id):
        within_scope = await scalar_count(probe_database, count_statement(probe.table_name))
        other_rows = await scalar_count(
            probe_database,
            count_statement(probe.table_name, where="tenant_id = :other"),
            {"other": probe.second_tenant_id},
        )
        cross_tenant = await scalar_count(
            probe_database,
            count_statement(probe.table_name, where="id = :identifier"),
            {"identifier": probe.second_row_id},
        )
    return Visibility(
        without_scope=without_scope,
        within_scope=within_scope,
        other_business_rows_visible_as_own=other_rows,
        cross_tenant_read_by_identifier=cross_tenant,
    )


async def build_probe(database: Database, table_name: str) -> IsolationProbe:
    """Seed two businesses with one row each in the named table."""
    seed_by_table = {
        "customers": seed_customer,
        "categories": seed_category,
    }
    seeder = seed_by_table.get(table_name)
    first_tenant_id = await seed_tenant(database, "First Trader")
    second_tenant_id = await seed_tenant(database, "Second Trader")
    if table_name == "ledger_entries":
        first_row_id = await seed_ledger_entry(database, tenant_id=first_tenant_id)
        second_row_id = await seed_ledger_entry(database, tenant_id=second_tenant_id)
    else:
        assert seeder is not None, f"no seeder for {table_name}"
        first_row_id = await seeder(database, tenant_id=first_tenant_id, name="First Row")
        second_row_id = await seeder(database, tenant_id=second_tenant_id, name="Second Row")
    return IsolationProbe(
        table_name=table_name,
        first_tenant_id=first_tenant_id,
        first_row_id=first_row_id,
        second_tenant_id=second_tenant_id,
        second_row_id=second_row_id,
    )


@pytest.mark.security
@pytest.mark.parametrize("table_name", ["customers", "categories", "ledger_entries"])
async def test_a_scoped_table_answers_all_three_questions(
    database: Database, probe_database: Database, table_name: str
) -> None:
    """No scope sees nothing, a scope sees its own rows, and asking by key reaches nothing else."""
    probe = await build_probe(database, table_name)

    visibility = await read_visibility(probe_database, probe)

    assert visibility == Visibility(
        without_scope=0,
        within_scope=1,
        other_business_rows_visible_as_own=0,
        cross_tenant_read_by_identifier=0,
    )


@pytest.mark.security
async def test_a_write_without_a_scope_is_refused(
    database: Database, probe_database: Database
) -> None:
    """A policy with a check is a constraint, not a filter.

    Without `WITH CHECK`, a scoped read would hide another business's rows and a scoped write could
    still create one. The row count after the refusal is the second half of the assertion: the
    refusal has to have left nothing behind.
    """
    probe = await build_probe(database, "customers")
    before = await scalar_count(database, "SELECT count(*) FROM customers")
    statement = text(
        "INSERT INTO customers (id, tenant_id, name, is_active, version, created_at, updated_at, "
        "marketing_opt_in) VALUES (:id, :tenant_id, :name, true, 1, :now, :now, false)"
    )

    with pytest.raises(ProgrammingError):
        async with probe_database.engine.begin() as connection:
            await connection.execute(
                statement,
                {
                    "id": uuid4(),
                    "tenant_id": probe.second_tenant_id,
                    "name": "Smuggled",
                    "now": NOW,
                },
            )

    assert await scalar_count(database, "SELECT count(*) FROM customers") == before


@pytest.mark.security
async def test_a_pooled_connection_carries_no_scope_into_the_next_transaction(
    database: Database, probe_database: Database
) -> None:
    """The failure that only appears under a connection pool.

    After a transaction that used `SET LOCAL` commits, PostgreSQL leaves the setting defined as an
    empty string rather than removing it. A policy written as
    `tenant_id = current_setting('app.current_tenant', true)::uuid` therefore raises
    `invalid input syntax for type uuid: ""` on the *next* transaction that borrows the connection -
    a hard failure where the answer should be "no rows". The `nullif` in the policy is what turns
    that empty string back into an absent scope, and this is the test that proves it, because both
    transactions run on one connection.
    """
    probe = await build_probe(database, "customers")

    async with probe_database.engine.connect() as connection:
        async with connection.begin():
            await connection.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": TENANT_SCOPE_SETTING, "value": str(probe.first_tenant_id)},
            )
            scoped = await connection.execute(text("SELECT count(*) FROM customers"))
            assert int(scoped.scalar_one()) == 1

        async with connection.begin():
            after_commit = await connection.execute(text("SELECT count(*) FROM customers"))
            assert int(after_commit.scalar_one()) == 0

            setting = await connection.execute(
                text("SELECT current_setting(:name, true)"), {"name": TENANT_SCOPE_SETTING}
            )
            # Recorded rather than assumed: the empty string is the reason the policy uses nullif.
            assert setting.scalar_one() == ""


@pytest.mark.security
async def test_the_application_read_fails_closed_without_a_scope(
    database: Database, probe_database: Database
) -> None:
    """The unit of work is what binds the scope, and its absence is a refusal, not a leak.

    This is the application path, not raw SQL: a repository read through the unit of work. Without a
    resolved business the row exists in the database and is invisible; with one it is found. That is
    the property that makes a forgotten filter fail closed instead of silently returning everything.
    """
    first_tenant_id = await seed_tenant(database, "First Trader")
    customer_id = await seed_customer(database, tenant_id=first_tenant_id, name="Ada Obi")

    async with probe_database.transaction_scope() as unit_of_work:
        with pytest.raises(NotFoundError):
            await customer_crud.require_by_id(
                unit_of_work.session_handle,
                tenant_id=first_tenant_id,
                customer_id=customer_id,
            )

    with tenant_scope(first_tenant_id):
        async with probe_database.transaction_scope() as unit_of_work:
            found = await customer_crud.require_by_id(
                unit_of_work.session_handle,
                tenant_id=first_tenant_id,
                customer_id=customer_id,
            )

    assert found.id == customer_id


@pytest.mark.security
@pytest.mark.parametrize("table_name", EXPECTED_SCOPED_TABLES)
async def test_a_scoped_table_has_row_level_security_enabled_and_forced(
    database: Database, table_name: str
) -> None:
    """Enabled alone would leave the table's owner exempt, which in this deployment is everybody."""
    async with database.engine.connect() as connection:
        state = await connection.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = :name AND relkind = 'r'"
            ),
            {"name": table_name},
        )
        row = state.one_or_none()

    assert row is not None, f"{table_name} does not exist"
    assert row[0] is True, f"{table_name} does not have row level security enabled"
    assert row[1] is True, f"{table_name} does not force row level security"


@pytest.mark.security
@pytest.mark.parametrize("table_name", EXPECTED_SCOPED_TABLES)
async def test_every_scoped_table_has_one_policy_of_the_same_shape(
    database: Database, table_name: str
) -> None:
    """One permissive policy per table, reading and checking the same predicate.

    Uniformity is the point: a table whose policy differed would be a table where the tenant filter
    is subtly wider, and nothing else in the build would notice. One policy rather than several is
    also load-bearing - policies combine with OR, so a second permissive policy can only widen.
    """
    async with database.engine.connect() as connection:
        policies = await connection.execute(
            text(
                "SELECT policyname, permissive, cmd, qual, with_check FROM pg_policies "
                "WHERE schemaname = 'public' AND tablename = :name"
            ),
            {"name": table_name},
        )
        rows = policies.all()

    assert len(rows) == 1, f"{table_name} has {len(rows)} policies, expected exactly one"
    name, permissive, command_name, using_expression, check_expression = rows[0]
    assert name == f"{table_name}_tenant_isolation"
    assert permissive == "PERMISSIVE"
    assert command_name == "ALL", "a policy for one command would leave the others unguarded"
    assert using_expression == check_expression, "a read and a write must be scoped identically"
    assert "tenant_id" in using_expression
    assert TENANT_SCOPE_SETTING in using_expression, "the policy reads a different setting"
    assert "nullif" in using_expression.lower(), (
        "without nullif an empty setting raises instead of returning no rows"
    )


@pytest.mark.security
@pytest.mark.parametrize("table_name", EXPECTED_UNSCOPED_TABLES)
async def test_a_deliberately_unscoped_table_has_no_policy(
    database: Database, table_name: str
) -> None:
    """The exclusions are decisions, and a decision nobody tests is a decision that erodes.

    Each of these tables is read before any business is known - a slug, a token, a membership - so a
    policy on one would break a public address or a login rather than protect it.
    """
    async with database.engine.connect() as connection:
        policies = await connection.execute(
            text(
                "SELECT policyname FROM pg_policies "
                "WHERE schemaname = 'public' AND tablename = :name"
            ),
            {"name": table_name},
        )
        names = [row[0] for row in policies.all()]
        state = await connection.execute(
            text("SELECT relrowsecurity FROM pg_class WHERE relname = :name AND relkind = 'r'"),
            {"name": table_name},
        )
        enabled = state.scalar_one_or_none()

    assert names == [], f"{table_name} has policies it was deliberately left out of: {names}"
    assert enabled is False, f"{table_name} has row level security enabled"


@pytest.mark.unit
def test_the_policy_setting_matches_the_unit_of_work() -> None:
    """The writer and the readers of the setting are asserted to agree.

    A rename in the application that missed the migrations would leave every policy reading a
    setting nobody writes - which fails closed, silently, and would look like a data-loss bug.
    """
    assert TENANT_SCOPE_SETTING == "app.current_tenant"
