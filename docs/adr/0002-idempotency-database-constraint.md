# ADR 0002: Idempotency uniqueness is a database constraint

## Status

Accepted

## Context

A retried payout has to land once. Application locks and in-memory sets miss crashes and concurrent workers. The blueprint's proof is a unique constraint that the second writer cannot bypass.

## Decision

`idempotency_keys` uses the appendix schema, with primary key `(tenant_id, key)`. Payments also have `UNIQUE (tenant_id, idempotency_key)`. The generator inserts one succeeded row per simulated payment so the key and the payment agree. The state machine that inserts `in_progress`, detects a conflicting request hash, and reclaims a stale lock is Phase 2. It is not implemented here.

## Consequences

The constraint is already in the database, so Phase 2 cannot "enforce" uniqueness only in Python. Phase 0 does not claim the replay tests pass. Those tests arrive with the state machine.
