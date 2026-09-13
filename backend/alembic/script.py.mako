"""${message}

Revision ID: ${up_revision}
Revises:${" " + down_revision if down_revision else ""}
Create Date: ${create_date}

Generated where autogenerate was sufficient, reviewed before it was applied, and
edited by hand wherever a constraint the database should enforce is not something
autogenerate can infer.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${(imports.rstrip() + "\n") if imports else ""}
revision: str = ${'"%s"' % up_revision}
down_revision: str | None = ${('"%s"' % down_revision) if down_revision else "None"}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
