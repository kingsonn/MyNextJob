# ClaimPilot

ClaimPilot is a control plane for an insurance-claims agent. Phase 1 runs a supervisor with intake, verification, and coverage workers over the seeded book. Phase 2 adds idempotent payouts and portal notes, loop and budget limits, a provider pool, and an approval page. Phase 3 adds the model router, hybrid retrieval, memory, and PDF ingestion. Phase 4 adds guardrails, the red-team suite, and the admin console. Model calls go through one provider interface and tests use a scripted fake.

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

Trajectory, routing, cache safety, and the multi-hop gap below are offline measurements. Live-provider rows have not been run.

| Area | Target | Result |
| --- | --- | --- |
| Idempotency | 0 duplicate side effects in 1,000 replays | 0 duplicates in 1,000 concurrent payout calls and 1,000 portal writes |
| Durability | 100% of 50 crash trials resume | 50 seeded crash trials each end with one payout; 50 checkpoint resumes continue |
| Loop control | 95% or more of injected loops caught | 20 of 20 injected loops stop at or before the step cap |
| Cost control | 0 sessions over budget | 0 of 20 scripted sessions spend past the token cap |
| Routing | 40% or more lower cost, accuracy within 2 points | shadow price on 30 scripted tasks is about 66% below the strong tier; accuracy is not a live-model score |
| Semantic cache | 30% or more hit rate on repeated FAQ traffic | exact repeats hit; a production traffic rate is not measured |
| Cache safety | 0 cross-tenant leaks | 0 in the tenant-isolation test; 0 false hits on the labelled near-duplicate set |
| Knowledge graph | at least 15 points above vector-only RAG | 100-point gap on 60 multi-hop questions; simple questions use the same retrieval path |
| Guardrails | 90% or more block rate, false positives under 3% | 226 of 230 attacks blocked (98.3%); 0 of 100 benign blocked; four misses are named in the threat model |
| Trajectory quality | 85% or more average score | 0.987 mean on the 30 golden scenarios (`evals/baselines/phase-1.json`) |
| Voice | p50 under 1.5 s, p95 under 3 s | not measured |
| Regression | CI fails on a drop over 3 points | the golden test fails the build if any scenario score changes |

## Limitations

Phases 5 and 6 are not built. There is no voice agent and no browser agent that recovers from a portal layout change. Admin roles are four synthetic bearer tokens, not a login session. Two of the 30 golden scenarios still escalate. They ask the browser to read a portal note, which is Phase 5. Their outcome score is 0 and the outcome mean is 0.93. Retrieval, the cache, and reranking use a hashing embedding, not a model. The graph load is parameterised, and tests record those statements instead of opening Neo4j. OCR reads the synthetic bitmap font; Tesseract is not on the test path, and the original blank scans stay flagged for review. Memory, document versions, and the audit log are in-memory because the schema appendix does not define those tables. Chaos tests do not open Redis or Postgres. Langfuse starts empty aside from the hello-world trace.
