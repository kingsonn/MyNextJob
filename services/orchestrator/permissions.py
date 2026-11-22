"""Worker tool allow-lists. The supervisor has none."""

INTAKE_TOOLS = [
    "crm.find_customer",
    "crm.list_interactions",
    "crm.update_contact",
    "crm.add_note",
]
VERIFICATION_TOOLS = [
    "crm.verify_identity",
    "crm.find_customer",
    "policy.get_policy",
    "policy.list_coverages",
    "policy.get_policy_version_on_date",
    "policy.get_endorsements",
    "policy.get_coverage",
]
COVERAGE_TOOLS = [
    "policy.get_policy",
    "policy.list_coverages",
    "policy.get_policy_version_on_date",
    "policy.get_endorsements",
    "policy.get_coverage",
    "knowledge.search",
    "graph.coverage_path",
    "graph.shared_contact",
    "graph.provider_cluster",
]
SETTLEMENT_TOOLS = [
    "claims.create_claim",
    "payments.propose_payout",
]
DOCUMENT_TOOLS = ["docs.get_clause"]
SUPERVISOR_TOOLS: list[str] = []

ALLOW_LISTS = {
    "intake": INTAKE_TOOLS,
    "verification": VERIFICATION_TOOLS,
    "coverage": COVERAGE_TOOLS,
    "settlement": SETTLEMENT_TOOLS,
    "documents": DOCUMENT_TOOLS,
    "supervisor": SUPERVISOR_TOOLS,
}
