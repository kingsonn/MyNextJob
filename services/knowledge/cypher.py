"""Parameterised, read-only Cypher templates.

The in-memory catalog answers the same three questions. Neo4j runs these templates
with bound parameters; nothing in the agent concatenates a user string into the query.
"""

COVERAGE_PATH = """
MATCH (policy:Policy {id: $policy_id, tenant_id: $tenant_id})
OPTIONAL MATCH (policy)-[:INCLUDES]->(coverage:Coverage)
OPTIONAL MATCH (endorsement:Endorsement {policy_id: $policy_id, tenant_id: $tenant_id})
OPTIONAL MATCH (claim:Claim {policy_id: $policy_id, tenant_id: $tenant_id})
RETURN policy, collect(DISTINCT coverage), collect(DISTINCT endorsement), collect(DISTINCT claim)
"""

SHARED_CONTACT = """
MATCH (customer:Customer {id: $customer_id, tenant_id: $tenant_id})-[:USES]->(contact:ContactPoint)
MATCH (other:Customer {tenant_id: $tenant_id})-[:USES]->(contact)
RETURN contact.phone AS phone,
       contact.address AS address,
       collect(DISTINCT other.id) AS customer_ids
"""

PROVIDER_CLUSTER = """
MATCH (provider:Provider {id: $provider_id, tenant_id: $tenant_id})<-[:HANDLED_BY]-(claim:Claim)
WITH claim.loss_date AS loss_date, claim.amount AS amount, collect(claim.id) AS claim_ids
WHERE size(claim_ids) >= 5
ORDER BY size(claim_ids) ASC, loss_date ASC
LIMIT 1
RETURN $provider_id AS provider_id, claim_ids
"""

TEMPLATES = {
    "graph.coverage_path": COVERAGE_PATH,
    "graph.shared_contact": SHARED_CONTACT,
    "graph.provider_cluster": PROVIDER_CLUSTER,
}
