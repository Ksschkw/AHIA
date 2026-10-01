"""Normalize phone numbers to standard international format across all tables.

Ensures that 0801..., 801..., 234801..., and +234801... all resolve consistently
to canonical E.164 form (+234801...) across tenants, storefronts, customers,
requests, and invitations.

Revision ID: 8f3a1d9c5e27
Revises: 7e4b2c9d6f18
"""

from __future__ import annotations

from alembic import op

revision: str = "8f3a1d9c5e27"
down_revision: str | None = "7e4b2c9d6f18"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE tenants
        SET phone = CASE
            WHEN REGEXP_REPLACE(phone, '[^0-9+]', '', 'g') ~ '^\\+234' THEN REGEXP_REPLACE(phone, '[^0-9+]', '', 'g')
            WHEN REGEXP_REPLACE(phone, '[^0-9+]', '', 'g') ~ '^234[0-9]{10}$' THEN '+' || REGEXP_REPLACE(phone, '[^0-9+]', '', 'g')
            WHEN REGEXP_REPLACE(phone, '[^0-9+]', '', 'g') ~ '^0[0-9]{10}$' THEN '+234' || SUBSTRING(REGEXP_REPLACE(phone, '[^0-9+]', '', 'g') FROM 2)
            WHEN REGEXP_REPLACE(phone, '[^0-9+]', '', 'g') ~ '^[789][0-9]{9}$' THEN '+234' || REGEXP_REPLACE(phone, '[^0-9+]', '', 'g')
            ELSE REGEXP_REPLACE(phone, '[^0-9+]', '', 'g')
        END
        WHERE phone IS NOT NULL AND phone != ''
    """)
    op.execute("""
        UPDATE storefronts
        SET contact_phone = CASE
            WHEN REGEXP_REPLACE(contact_phone, '[^0-9+]', '', 'g') ~ '^\\+234' THEN REGEXP_REPLACE(contact_phone, '[^0-9+]', '', 'g')
            WHEN REGEXP_REPLACE(contact_phone, '[^0-9+]', '', 'g') ~ '^234[0-9]{10}$' THEN '+' || REGEXP_REPLACE(contact_phone, '[^0-9+]', '', 'g')
            WHEN REGEXP_REPLACE(contact_phone, '[^0-9+]', '', 'g') ~ '^0[0-9]{10}$' THEN '+234' || SUBSTRING(REGEXP_REPLACE(contact_phone, '[^0-9+]', '', 'g') FROM 2)
            WHEN REGEXP_REPLACE(contact_phone, '[^0-9+]', '', 'g') ~ '^[789][0-9]{9}$' THEN '+234' || REGEXP_REPLACE(contact_phone, '[^0-9+]', '', 'g')
            ELSE REGEXP_REPLACE(contact_phone, '[^0-9+]', '', 'g')
        END
        WHERE contact_phone IS NOT NULL AND contact_phone != ''
    """)
    op.execute("""
        UPDATE customers
        SET phone = CASE
            WHEN REGEXP_REPLACE(phone, '[^0-9+]', '', 'g') ~ '^\\+234' THEN REGEXP_REPLACE(phone, '[^0-9+]', '', 'g')
            WHEN REGEXP_REPLACE(phone, '[^0-9+]', '', 'g') ~ '^234[0-9]{10}$' THEN '+' || REGEXP_REPLACE(phone, '[^0-9+]', '', 'g')
            WHEN REGEXP_REPLACE(phone, '[^0-9+]', '', 'g') ~ '^0[0-9]{10}$' THEN '+234' || SUBSTRING(REGEXP_REPLACE(phone, '[^0-9+]', '', 'g') FROM 2)
            WHEN REGEXP_REPLACE(phone, '[^0-9+]', '', 'g') ~ '^[789][0-9]{9}$' THEN '+234' || REGEXP_REPLACE(phone, '[^0-9+]', '', 'g')
            ELSE REGEXP_REPLACE(phone, '[^0-9+]', '', 'g')
        END
        WHERE phone IS NOT NULL AND phone != ''
    """)
    op.execute("""
        UPDATE requests
        SET customer_phone = CASE
            WHEN REGEXP_REPLACE(customer_phone, '[^0-9+]', '', 'g') ~ '^\\+234' THEN REGEXP_REPLACE(customer_phone, '[^0-9+]', '', 'g')
            WHEN REGEXP_REPLACE(customer_phone, '[^0-9+]', '', 'g') ~ '^234[0-9]{10}$' THEN '+' || REGEXP_REPLACE(customer_phone, '[^0-9+]', '', 'g')
            WHEN REGEXP_REPLACE(customer_phone, '[^0-9+]', '', 'g') ~ '^0[0-9]{10}$' THEN '+234' || SUBSTRING(REGEXP_REPLACE(customer_phone, '[^0-9+]', '', 'g') FROM 2)
            WHEN REGEXP_REPLACE(customer_phone, '[^0-9+]', '', 'g') ~ '^[789][0-9]{9}$' THEN '+234' || REGEXP_REPLACE(customer_phone, '[^0-9+]', '', 'g')
            ELSE REGEXP_REPLACE(customer_phone, '[^0-9+]', '', 'g')
        END
        WHERE customer_phone IS NOT NULL AND customer_phone != ''
    """)
    op.execute("""
        UPDATE requests
        SET transporter_phone = CASE
            WHEN REGEXP_REPLACE(transporter_phone, '[^0-9+]', '', 'g') ~ '^\\+234' THEN REGEXP_REPLACE(transporter_phone, '[^0-9+]', '', 'g')
            WHEN REGEXP_REPLACE(transporter_phone, '[^0-9+]', '', 'g') ~ '^234[0-9]{10}$' THEN '+' || REGEXP_REPLACE(transporter_phone, '[^0-9+]', '', 'g')
            WHEN REGEXP_REPLACE(transporter_phone, '[^0-9+]', '', 'g') ~ '^0[0-9]{10}$' THEN '+234' || SUBSTRING(REGEXP_REPLACE(transporter_phone, '[^0-9+]', '', 'g') FROM 2)
            WHEN REGEXP_REPLACE(transporter_phone, '[^0-9+]', '', 'g') ~ '^[789][0-9]{9}$' THEN '+234' || REGEXP_REPLACE(transporter_phone, '[^0-9+]', '', 'g')
            ELSE REGEXP_REPLACE(transporter_phone, '[^0-9+]', '', 'g')
        END
        WHERE transporter_phone IS NOT NULL AND transporter_phone != ''
    """)
    op.execute("""
        UPDATE membership_invitations
        SET invited_phone = CASE
            WHEN REGEXP_REPLACE(invited_phone, '[^0-9+]', '', 'g') ~ '^\\+234' THEN REGEXP_REPLACE(invited_phone, '[^0-9+]', '', 'g')
            WHEN REGEXP_REPLACE(invited_phone, '[^0-9+]', '', 'g') ~ '^234[0-9]{10}$' THEN '+' || REGEXP_REPLACE(invited_phone, '[^0-9+]', '', 'g')
            WHEN REGEXP_REPLACE(invited_phone, '[^0-9+]', '', 'g') ~ '^0[0-9]{10}$' THEN '+234' || SUBSTRING(REGEXP_REPLACE(invited_phone, '[^0-9+]', '', 'g') FROM 2)
            WHEN REGEXP_REPLACE(invited_phone, '[^0-9+]', '', 'g') ~ '^[789][0-9]{9}$' THEN '+234' || REGEXP_REPLACE(invited_phone, '[^0-9+]', '', 'g')
            ELSE REGEXP_REPLACE(invited_phone, '[^0-9+]', '', 'g')
        END
        WHERE invited_phone IS NOT NULL AND invited_phone != ''
    """)


def downgrade() -> None:
    pass
