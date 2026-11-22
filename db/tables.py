"""SQLAlchemy tables for the Phase 0 claims schema.

The Alembic revision is what runs against Postgres. These tables are the
loader's view of the same columns.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

tenants = Table(
    "tenants",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("region", Text, nullable=False),
    Column("plan", Text, nullable=False),
)

customers = Table(
    "customers",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("dob", Date, nullable=False),
    Column("address", Text, nullable=False),
    Column("phone", Text, nullable=False),
    Column("email", Text, nullable=False),
    Column("language", Text, nullable=False),
    Column("risk_segment", Text, nullable=False),
    Column("identity_verified", Boolean, nullable=False),
)

policies = Table(
    "policies",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("customer_id", Text, ForeignKey("customers.id"), nullable=False),
    Column("type", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("start_date", Date, nullable=False),
    Column("end_date", Date, nullable=False),
    Column("premium", BigInteger, nullable=False),
    Column("coverage_language", Text, nullable=False),
)

coverages = Table(
    "coverages",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("policy_id", Text, ForeignKey("policies.id"), nullable=False),
    Column("peril", Text, nullable=False),
    Column("limit_amount", BigInteger, nullable=False),
    Column("deductible", BigInteger, nullable=False),
)

endorsements = Table(
    "endorsements",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("policy_id", Text, ForeignKey("policies.id"), nullable=False),
    Column("effective_date", Date, nullable=False),
    Column("change_description", Text, nullable=False),
)

providers = Table(
    "providers",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("type", Text, nullable=False),
    Column("region", Text, nullable=False),
    Column("rating", Integer, nullable=False),
)

adjusters = Table(
    "adjusters",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("authority_limit", BigInteger, nullable=False),
)

claims = Table(
    "claims",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("policy_id", Text, ForeignKey("policies.id"), nullable=False),
    Column("loss_date", Date, nullable=False),
    Column("type", Text, nullable=False),
    Column("amount", BigInteger, nullable=False),
    Column("status", Text, nullable=False),
    Column("adjuster_id", Text, ForeignKey("adjusters.id"), nullable=False),
    Column("provider_id", Text, ForeignKey("providers.id")),
    Column("portal_note", Text),
    Column("submission_key", Text, nullable=False),
    UniqueConstraint("tenant_id", "submission_key", name="claims_tenant_submission_key"),
)

payments = Table(
    "payments",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("claim_id", Text, ForeignKey("claims.id"), nullable=False),
    Column("amount", BigInteger, nullable=False),
    Column("paid_on", Date, nullable=False),
    Column("method", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    UniqueConstraint("tenant_id", "idempotency_key", name="payments_tenant_idempotency_key"),
    UniqueConstraint("claim_id", name="payments_claim_id_key"),
)

interactions = Table(
    "interactions",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("customer_id", Text, ForeignKey("customers.id"), nullable=False),
    Column("channel", Text, nullable=False),
    Column("summary", Text, nullable=False),
    Column("occurred_on", Date, nullable=False),
)

policy_documents = Table(
    "policy_documents",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("policy_id", Text, ForeignKey("policies.id"), nullable=False),
    Column("version", Text, nullable=False),
    Column("path", Text, nullable=False),
    Column("clause_count", Integer, nullable=False),
    Column("watermark", Text, nullable=False),
    Column("injection", Text),
)

faq_pages = Table(
    "faq_pages",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("topic", Text, nullable=False),
    Column("body", Text, nullable=False),
)

planted_scenarios = Table(
    "planted_scenarios",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("scenario_type", Text, nullable=False),
    Column("entity_id", Text, nullable=False),
    Column("expected", JSONB, nullable=False),
)

crm_notes = Table(
    "crm_notes",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("customer_id", Text, ForeignKey("customers.id"), nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("request_hash", Text, nullable=False),
    Column("body", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("tenant_id", "idempotency_key", name="crm_notes_tenant_idempotency_key"),
)

crm_contact_updates = Table(
    "crm_contact_updates",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenants.id"), nullable=False),
    Column("customer_id", Text, ForeignKey("customers.id"), nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("request_hash", Text, nullable=False),
    Column("phone", Text),
    Column("email", Text),
    Column("address", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "idempotency_key",
        name="crm_contact_updates_tenant_idempotency_key",
    ),
)

idempotency_keys = Table(
    "idempotency_keys",
    metadata,
    Column("tenant_id", Text, ForeignKey("tenants.id"), primary_key=True),
    Column("key", Text, primary_key=True),
    Column("request_hash", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("response_body", JSONB),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("lock_expires_at", DateTime(timezone=True)),
    CheckConstraint(
        "state IN ('in_progress','succeeded','failed_retryable','failed_final')",
        name="idempotency_keys_state_check",
    ),
)
