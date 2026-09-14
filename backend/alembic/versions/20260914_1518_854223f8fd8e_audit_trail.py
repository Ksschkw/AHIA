"""audit events, and the trigger that makes the trail evidence

The milestone that records who did what. Every mutating use case from here on writes an event
in the same transaction as the change it describes, so a trail entry cannot exist for a change
that was rolled back, and a change cannot land without its entry.

The table is append-only, enforced by a trigger
    `audit_events` refuses UPDATE and DELETE, exactly as `inventory_movements` and
    `ledger_entries` do. The application has no function that could perform either, but a
    convention holds only until somebody writes the function that breaks it. A trail that can
    be edited is not evidence, and the trigger is what makes that true for a psql session and a
    future service alike.

Every event carries its own context rather than a join
    The tenant, the actor, the device, the offline operation and the moment are copied in when
    the action happens. Joining to `users` or `devices` at read time would let a later edit to
    those tables change what the trail says about the past.

`actor_id` is nullable, and that is deliberate
    The permission registry being provisioned, or a scheduled job running, is an action with no
    person behind it. Inventing one would put a name on an action nobody took.

`detail` is JSONB because a trail is queried by the identifiers inside it
    The entity bounds what goes in - short strings, lower-snake-case keys, no key that names a
    credential - so the column needs no second, weaker bound of its own.

Reads are indexed by what a person asks
    `(tenant_id, occurred_at)` for "what happened", `(tenant_id, entity_type, entity_id,
    occurred_at)` for "what happened to this record", `(tenant_id, actor_id, occurred_at)` for
    "what did this person do" and `(tenant_id, action, occurred_at)` for "how often was this
    refused". Declared with the table rather than discovered from a slow screen later.

Revision ID: 854223f8fd8e
Revises: 4cba683657a9
Create Date: 2026-09-14 15:18:58.846474

Generated where autogenerate was sufficient, reviewed before it was applied, and
edited by hand wherever a constraint the database should enforce is not something
autogenerate can infer.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "854223f8fd8e"
down_revision: str | None = "4cba683657a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPEND_ONLY_FUNCTION: str = "ahia_audit_events_append_only"
_APPEND_ONLY_TRIGGER: str = "audit_events_append_only"


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("operation_id", sa.Uuid(), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_audit_events_actor_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"], name=op.f("fk_audit_events_device_id_devices")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_audit_events_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        "ix_audit_events_tenant_action",
        "audit_events",
        ["tenant_id", "action", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_tenant_actor",
        "audit_events",
        ["tenant_id", "actor_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_tenant_entity",
        "audit_events",
        ["tenant_id", "entity_type", "entity_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_tenant_occurred",
        "audit_events",
        ["tenant_id", "occurred_at"],
        unique=False,
    )

    # The rule the application cannot be trusted to keep on its own. A correction to the trail
    # is another event, and the database is what makes that the only option.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_APPEND_ONLY_FUNCTION}() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'audit_events is append-only: record a compensating event instead';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_APPEND_ONLY_TRIGGER}
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION {_APPEND_ONLY_FUNCTION}();
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_APPEND_ONLY_TRIGGER} ON audit_events")
    op.execute(f"DROP FUNCTION IF EXISTS {_APPEND_ONLY_FUNCTION}()")
    op.drop_index("ix_audit_events_tenant_occurred", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_entity", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_actor", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_action", table_name="audit_events")
    op.drop_table("audit_events")
