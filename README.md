# ClaimPilot

ClaimPilot is a control plane for an insurance-claims agent. Phase 1 runs a supervisor with intake, verification, and coverage workers over the seeded book. Phase 2 adds idempotent payouts and portal notes, loop and budget limits, a provider pool, and an approval page. Model calls go through one provider interface and tests use a scripted fake.

All people, policies, claims, and payments in this repository are synthetic. Phone numbers use the reserved `555-01xx` range. Email addresses use `example.com`, `example.net`, and `example.org`. Policy documents carry the watermark `SYNTHETIC - NOT A REAL POLICY`. Nothing here is a real customer or a real payment rail.

## Quickstart

Install GNU Make, Docker, and Python 3.11 or newer, then:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
make up
make test
```

`make up` starts Postgres with pgvector and Redis, applies migrations, and loads the synthetic book. `make seed` generates and loads again. `make test` runs the offline tests, including the golden-scenario baseline. It does not start Docker or call a model.

Other profiles stay off until you ask for them:

```bash
make observability
make langfuse-hello
docker compose --env-file deploy/env.example -f deploy/docker-compose.yml --profile graph up -d
```

`make langfuse-hello` sends one trace named `phase0-hello` to self-hosted Langfuse. The voice profile is reserved for Phase 5 and is not a working voice agent. Starting it downloads local speech models.

Refresh the committed answer key without a database:

```bash
python -m generator write
```

## What Phase 0 contains

- Compose profiles for core (Postgres and Redis), graph (Neo4j Community), observability (Langfuse), and voice (pinned local speech images).
- Alembic schema for the section 14 entities, planted scenarios, and the idempotency table.
- A deterministic generator at the full suggested volumes, with planted scenarios, 120 watermarked policy documents, and 30 golden conversations.

## Results

Only the trajectory row has been measured. The other rows have not been run.

| Area | Target | Result |
| --- | --- | --- |
| Idempotency | 0 duplicate side effects in 1,000 replays | 0 duplicates in 1,000 concurrent payout calls and 1,000 portal writes |
| Durability | 100% of 50 crash trials resume | one crash reconcile is covered; the 50-trial run is not |
| Loop control | 95% or more of injected loops caught | hard caps, signature, and no-progress stops are covered; no corpus rate yet |
| Cost control | 0 sessions over budget | budget decisions hand off in chaos tests; session cost is not measured |
| Routing | 40% or more lower cost, accuracy within 2 points | not measured |
| Semantic cache | 30% or more hit rate on repeated FAQ traffic | not measured |
| Cache safety | 0 cross-tenant leaks | 0 in the tenant-isolation test |
| Knowledge graph | at least 15 points above vector-only RAG | not measured |
| Guardrails | 90% or more block rate, false positives under 3% | not measured |
| Trajectory quality | 85% or more average score | 0.94 mean on the 30 golden scenarios (`evals/baselines/phase-1.json`) |
| Voice | p50 under 1.5 s, p95 under 3 s | not measured |
| Regression | CI fails on a drop over 3 points | not measured |

## Limitations

Phases 3 through 6 are not built. There is no model router, no guardrail stack, no voice agent, and no browser agent that recovers from a portal layout change. The approval page uses one synthetic adjuster token, not a role matrix. Nine of the 30 golden scenarios still escalate because payout, portal, and document paths are not on the Phase 1 route; their outcome score is 0 and the outcome mean is 0.70. Retrieval and the budget cache use a deterministic hashing embedding, not a model, and the graph tools answer from memory rather than Neo4j. Chaos tests do not open Redis or Postgres. Langfuse starts empty aside from the hello-world trace. Policy documents are clean text and PDF renderings, not the scanned corpus.
