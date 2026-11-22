"""CRM note and contact-update tables.

Revision ID: 0002_crm_writes
Revises: 0001_initial
Create Date: 2026-11-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_crm_writes"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE crm_notes (
        id text PRIMARY KEY,
        tenant_id text NOT NULL REFERENCES tenants (id),
        customer_id text NOT NULL REFERENCES customers (id),
        idempotency_key text NOT NULL,
        request_hash text NOT NULL,
        body text NOT NULL,
        created_at timestamptz NOT NULL,
        UNIQUE (tenant_id, idempotency_key)
    )
    """,
    """
    CREATE INDEX crm_notes_customer_idx ON crm_notes (tenant_id, customer_id)
    """,
    """
    CREATE TABLE crm_contact_updates (
        id text PRIMARY KEY,
        tenant_id text NOT NULL REFERENCES tenants (id),
        customer_id text NOT NULL REFERENCES customers (id),
        idempotency_key text NOT NULL,
        request_hash text NOT NULL,
        phone text,
        email text,
        address text,
        created_at timestamptz NOT NULL,
        UNIQUE (tenant_id, idempotency_key)
    )
    """,
    """
    CREATE INDEX crm_contact_updates_customer_idx
        ON crm_contact_updates (tenant_id, customer_id)
    """,
)

DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    "DROP TABLE IF EXISTS crm_contact_updates",
    "DROP TABLE IF EXISTS crm_notes",
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
