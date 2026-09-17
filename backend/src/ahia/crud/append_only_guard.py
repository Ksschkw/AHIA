"""The append-only rule, attached to the tables instead of only to a migration.

A ledger entry and a stock movement are facts: a correction is another entry, never an edit.
The application never offers an update or a delete for them, and that is not enough on its own -
a migration, a script or a future use case can reach the table directly. The database is what makes
the rule true, which is why the trigger exists.

**Why it is declared here as well as in the migrations.** A test database and a CI database are
built from the SQLAlchemy metadata (`create_all`), not by running the migration chain, so a trigger
that lives only in a migration exists in production and nowhere else. That is exactly backwards:
the rule would be enforced in the one place nobody is experimenting, and missing in the two places
where every change is tried first. Declaring it on the table means every path that creates the
table also creates its protection.

The naming follows the migrations: one function per table, named `ahia_<table>_append_only`, and one
trigger named `<table>_append_only`.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import DDL, Table, event

#: The tables whose rows are facts. `audit_events` is here for the same reason as the other two:
#: the trail cannot be edited, and a database built from the metadata deserves that protection.
APPEND_ONLY_TABLES: Final[tuple[str, ...]] = (
    "inventory_movements",
    "ledger_entries",
    "audit_events",
)


def declarative_table(model: type[object]) -> Table:
    """Return the table a declarative model is mapped to.

    A declarative class exposes `__table__` as a `FromClause` to the type checker even though a
    mapped class always has a `Table`. Naming that conversion once is better than three ignores, and
    it fails loudly if the class is ever not mapped.
    """
    table = getattr(model, "__table__", None)
    if not isinstance(table, Table):
        raise TypeError(f"{getattr(model, '__name__', model)!r} is not mapped to a table")
    return table


def function_name(table_name: str) -> str:
    """Return the guard function's name for one table."""
    return f"ahia_{table_name}_append_only"


def trigger_name(table_name: str) -> str:
    """Return the guard trigger's name for one table."""
    return f"{table_name}_append_only"


def guard_append_only(table: Table) -> None:
    """Make `UPDATE` and `DELETE` fail on this table, wherever the table is created.

    Registered as an `after_create` listener, so it fires for `create_all` exactly as it does
    for a migration that creates the table. `DROP TRIGGER IF EXISTS` makes it re-runnable, and the
    function is replaced rather than created, so applying both paths in either order is harmless.
    """
    table_name = table.name
    if table_name not in APPEND_ONLY_TABLES:
        return

    # One statement per DDL object, and that is not tidiness: the driver refuses more than one
    # command in a single prepared statement, so a guard that arrived as one block of SQL would fail
    # the moment a table was created through `create_all`.
    statements = (
        f"""
        CREATE OR REPLACE FUNCTION {function_name(table_name)}() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                '{table_name} is append-only: record a compensating event instead';
        END;
        $$ LANGUAGE plpgsql;
        """,
        f"DROP TRIGGER IF EXISTS {trigger_name(table_name)} ON {table_name};",
        f"""
        CREATE TRIGGER {trigger_name(table_name)}
        BEFORE UPDATE OR DELETE ON {table_name}
        FOR EACH ROW EXECUTE FUNCTION {function_name(table_name)}();
        """,
    )

    for statement_text in statements:
        # SQLAlchemy ships no type information for `DDL`, and the ignore is scoped to that call.
        statement = DDL(statement_text).execute_if(  # type: ignore[no-untyped-call]
            dialect="postgresql"
        )
        event.listen(table, "after_create", statement)
