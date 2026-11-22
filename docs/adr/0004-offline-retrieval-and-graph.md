# Deterministic retrieval and an in-memory coverage graph

Phase 1 needs cited clauses and coverage paths for the coverage worker. The blueprint's retrieval design uses a local embedding model, and its graph design uses Neo4j. The test gate forbids network and model calls, so this phase does not call Ollama and does not require Neo4j to answer.

## Decision

Clause retrieval uses a deterministic hashing embedding plus token overlap, filtered by tenant, policy, and effective date. The coverage, shared-contact, and provider-cluster questions are answered from the synthetic tables by the same parameterised predicates as the Cypher templates in `services/knowledge/cypher.py`. Neo4j can run those templates later. It is not on the `make test` path.

CRM notes and contact updates are new tables. Uniqueness of `(tenant_id, idempotency_key)` is a database constraint. The idempotency state machine stays in Phase 2. LangGraph creates its own checkpoint tables in Postgres; the Phase 0 business tables are unchanged.

## Consequences

A later embedding model can replace `services/knowledge/hashing.py` without changing the tool envelope. Golden scenarios whose tools belong to claims, payments, documents, or the browser are escalated and scored as misses. They are not implemented by widening Phase 1.
