# ADR 0001: Postgres with pgvector is the system of record

## Status

Accepted

## Context

Claims, checkpoints, idempotency keys, and later document vectors all have to live somewhere. A separate vector database would add another service to the free local stack and another place for a claim and its evidence to drift apart.

## Decision

PostgreSQL with the pgvector extension is the only system of record. The Phase 0 migration creates the `vector` extension. No vector column or index is created until Phase 3, when documents are embedded.

Neo4j is a projection for relationship queries. Langfuse stores traces. Neither replaces a row in Postgres.

## Consequences

One database to back up and to reset from the generator. Vector search waits on Phase 3, so Phase 0 does not pretend retrieval works. Operators who only start the core Compose profile still get the database the later phases expect.
