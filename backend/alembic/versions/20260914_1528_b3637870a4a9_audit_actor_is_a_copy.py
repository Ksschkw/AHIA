"""the audit actor and device become copies rather than references

Found while wiring the recorder into the use cases: every test that built an authorized context
with an actor identifier failed, because `audit_events.actor_id` was a foreign key to `users`
and the actor was a plausible-looking identifier rather than a row. The failure exposed a design
mistake rather than a test problem.

An event that pointed at `users` would be a copy with a leash. Two consequences, and both are
wrong for a trail:

*   The event could not be written if the actor row were missing, so a real action by a real
    person would fail to be recorded because of a row in another table.
*   More seriously, this table is append-only - it refuses UPDATE and DELETE by trigger - so a
    foreign key here would pin every actor row forever. An erasure of a person's account would
    be impossible to complete while the trail holds events about them, and the trail would be the
    reason.

The right shape is a copy with no leash: the identifier is recorded at the moment of the action
and belongs to the event. The tenant reference stays, because tenant isolation is the one
relationship the database must enforce, and a trail entry in no business is meaningless.

The application is what keeps the copy honest: `actor_id` comes from the authorized context,
which was built from an authenticated session and an active membership, never from a request
body. A caller cannot claim to be somebody else.

Revision ID: b3637870a4a9
Revises: 854223f8fd8e
Create Date: 2026-09-14 15:28:49.567979

Generated where autogenerate was sufficient, reviewed before it was applied, and
edited by hand wherever a constraint the database should enforce is not something
autogenerate can infer.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b3637870a4a9"
down_revision: str | None = "854223f8fd8e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("fk_audit_events_device_id_devices"), "audit_events", type_="foreignkey"
    )
    op.drop_constraint(op.f("fk_audit_events_actor_id_users"), "audit_events", type_="foreignkey")


def downgrade() -> None:
    op.create_foreign_key(
        op.f("fk_audit_events_actor_id_users"), "audit_events", "users", ["actor_id"], ["id"]
    )
    op.create_foreign_key(
        op.f("fk_audit_events_device_id_devices"),
        "audit_events",
        "devices",
        ["device_id"],
        ["id"],
    )
