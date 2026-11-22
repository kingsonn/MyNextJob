# ADR 0003: Template generation, not a model

## Status

Accepted

## Context

The blueprint's generation pipeline optionally rewrites policy sentences with a local model and caches the output. That makes the first run depend on a model, a network or GPU, and a cache that can drift. Phase 0 tests have to be deterministic on a clean machine with no network.

## Decision

Names and street lines come from a pinned, seeded Faker. Every other field, clause, planted outcome, and golden conversation is produced by rule functions from `data/generator/config.yaml`. The same seed yields the same rows, PDF bytes, and answer key. A model is not called.

Rejected for Phase 0: local-LLM phrasing, even with a disk cache. It is a better fit once a cassette or cache is itself a reviewed artifact.

## Consequences

The prose is repetitive. It is also reproducible in CI. Document variety that needs a model, including scanned and hostile PDF variants, stays in Phase 3. Forty of the 120 policy documents still carry a fixed injection string so that later guardrail tests have something to find.
