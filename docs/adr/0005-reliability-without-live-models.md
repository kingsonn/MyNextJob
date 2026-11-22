# Reliability controls without live models or a browser agent

Phase 2 needs idempotent payouts, a legacy portal write, budget degradation, and an approval pause. The blueprint's later phases add a model router, a browser agent, and a role matrix. The test gate still forbids network and model calls.

## Decision

The idempotency state machine matches the existing `idempotency_keys` table. Tests use an in-memory store with the same transitions; the reclaim statement is the SQL a Postgres update would run. Uniqueness of a payout or portal note is the store's key, not a check outside it.

Agent keys are a stable hash of tenant, claim, action, and normalised parameters. The payments server and the Flask portal are real write paths. The portal has three HTML layouts around one `note` field. A browser agent that recovers from a layout change is not part of this phase.

Token and shadow budgets degrade in code. A shadow-cost miss may answer from a deterministic cache, then a cheap provider, then a human handoff. The cache reuses the hashing embedding, keeps a tenant, language, policy-version, and tier namespace, and refuses questions that contain claim, customer, or policy identifiers. It is not the Phase 3 router cache and it does not call a model.

The approval page is gated by one synthetic adjuster token from `deploy/env.example`. That is not the Phase 4 role matrix.

## Consequences

`make test` proves replay, conflict, crash reconcile, lock reclaim, and one side effect under 1,000 concurrent calls. It does not open Redis or Postgres and it does not drive a browser. Provider failover, loop stops, and budget handoff are covered by the same offline suite.
