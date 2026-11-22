"""Initial claims schema and idempotency keys.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_STATEMENTS: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS vector",
    """
    CREATE TABLE tenants (
        id text PRIMARY KEY,
        name text NOT NULL,
        region text NOT NULL,
        plan text NOT NULL
    )
    """,
    """
    CREATE TABLE customers (
        id text PRIMARY KEY,
        tenant_id text NOT NULL REFERENCES tenants (id),
        name text NOT NULL,
        dob date NOT NULL,
        address text NOT NULL,
        phone text NOT NULL,
        email text NOT NULL,
        language text NOT NULL,
        risk_segment text NOT NULL,
        identity_verified boolean NOT NULL
    )
    """,
    "CREATE INDEX customers_tenant_id_idx ON customers (tenant_id)",
    """
    CREATE TABLE policies (
        id text PRIMARY KEY,
        tenant_id text NOT NULL REFERENCES tenants (id),
        customer_id text NOT NULL REFERENCES customers (id),
        type text NOT NULL,
        status text NOT NULL,
        start_date date NOT NULL,
        end_date date NOT NULL,
        premium bigint NOT NULL,
        coverage_language text NOT NULL
    )
    """,
    "CREATE INDEX policies_tenant_id_idx ON policies (tenant_id)",
    "CREATE INDEX policies_customer_id_idx ON policies (customer_id)",
    """
    CREATE TABLE coverages (
        id text PRIMARY KEY,
        tenant_id text NOT NULL REFERENCES tenants (id),
        policy_id text NOT NULL REFERENCES policies (id),
        peril text NOT NULL,
        limit_amount bigint NOT NULL,
        deductible bigint NOT NULL
    )
    """,
    "CREATE INDEX coverages_policy_id_idx ON coverages (policy_id)",
    """
    CREATE TABLE endorsements (
        id text PRIMARY KEY,
        tenant_id text NOT NULL REFERENCES tenants (id),
        policy_id text NOT NULL REFERENCES policies (id),
        effective_date date NOT NULL,
        change_description text NOT NULL
    )
    """,
    "CREATE INDEX endorsements_policy_id_idx ON endorsements (policy_id)",
    """
    CREATE TABLE providers (
        id text PRIMARY KEY,
        tenant_id text NOT NULL REFERENCES tenants (id),
        type text NOT NULL,
        region text NOT NULL,
        rating integer NOT NULL
    )
    """,
    "CREATE INDEX providers_tenant_id_idx ON providers (tenant_id)",
    """
    CREATE TABLE adjusters (
        id text PRIMARY KEY,
        tenant_id text NOT NULL REFERENCES tenants (id),
        name text NOT NULL,
        authority_limit bigint NOT NULL
    )
    """,
    "CREATE INDEX adjusters_tenant_id_idx ON adjusters (tenant_id)",
    """
    CREATE TABLE claims (
        id text PRIMARY KEY,
        tenant_id text NOT NULL REFERENCES tenants (id),
        policy_id text NOT NULL REFERENCES policies (id),
        loss_date date NOT NULL,
        type text NOT NULL,
        amount bigint NOT NULL,
        status text NOT NULL,
        adjuster_id text NOT NULL REFERENCES adjusters (id),
        provider_id text REFERENCES providers (id),
        portal_note text,
        submission_key text NOT NULL,
        UNIQUE (tenant_id, submission_key)
    )
    """,
    "CREATE INDEX claims_policy_id_idx ON claims (policy_id)",
    "CREATE INDEX claims_adjuster_id_idx ON claims (adjuster_id)",
    "CREATE INDEX claims_provider_id_idx ON claims (provider_id)",
    """
    CREATE TABLE payments (
        id text PRIMARY KEY,
        tenant_id text NOT NULL REFERENCES tenants (id),
        claim_id text NOT NULL REFERENCES claims (id),
        amount bigint NOT NULL,
        paid_on date NOT NULL,
        method text NOT NULL,
        idempotency_key text NOT NULL,
        UNIQUE (tenant_id, idempotency_key),
        UNIQUE (claim_id)
    )
    """,
    "CREATE INDEX payments_tenant_id_idx ON payments (tenant_id)",
    """
    CREATE TABLE interactions (
        id text PRIMARY KEY,
        tenant_id text NOT NULL REFERENCES tenants (id),
        customer_id text NOT NULL REFERENCES customers (id),
        channel text NOT NULL,
        summary text NOT NULL,
        occurred_on date NOT NULL
    )
    """,
    "CREATE INDEX interactions_customer_id_idx ON interactions (customer_id)",
    """
    CREATE TABLE policy_documents (
        id text PRIMARY KEY,
        tenant_id text NOT NULL REFERENCES tenants (id),
        policy_id text NOT NULL REFERENCES policies (id),
        version text NOT NULL,
        path text NOT NULL,
        clause_count integer NOT NULL,
        watermark text NOT NULL,
        injection text
    )
    """,
    "CREATE INDEX policy_documents_policy_id_idx ON policy_documents (policy_id)",
    """
    CREATE TABLE faq_pages (
        id text PRIMARY KEY,
        tenant_id text NOT NULL REFERENCES tenants (id),
        topic text NOT NULL,
        body text NOT NULL
    )
    """,
    """
    CREATE TABLE planted_scenarios (
        id text PRIMARY KEY,
        tenant_id text NOT NULL REFERENCES tenants (id),
        scenario_type text NOT NULL,
        entity_id text NOT NULL,
        expected jsonb NOT NULL
    )
    """,
    "CREATE INDEX planted_scenarios_scenario_type_idx ON planted_scenarios (scenario_type)",
    """
    CREATE TABLE idempotency_keys (
        tenant_id text NOT NULL REFERENCES tenants (id),
        key text NOT NULL,
        request_hash text NOT NULL,
        state text NOT NULL CHECK (state IN
            ('in_progress','succeeded','failed_retryable','failed_final')),
        response_body jsonb,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        lock_expires_at timestamptz,
        PRIMARY KEY (tenant_id, key)
    )
    """,
)

DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    "DROP TABLE IF EXISTS idempotency_keys",
    "DROP TABLE IF EXISTS planted_scenarios",
    "DROP TABLE IF EXISTS faq_pages",
    "DROP TABLE IF EXISTS policy_documents",
    "DROP TABLE IF EXISTS interactions",
    "DROP TABLE IF EXISTS payments",
    "DROP TABLE IF EXISTS claims",
    "DROP TABLE IF EXISTS adjusters",
    "DROP TABLE IF EXISTS providers",
    "DROP TABLE IF EXISTS endorsements",
    "DROP TABLE IF EXISTS coverages",
    "DROP TABLE IF EXISTS policies",
    "DROP TABLE IF EXISTS customers",
    "DROP TABLE IF EXISTS tenants",
    "DROP EXTENSION IF EXISTS vector",
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
