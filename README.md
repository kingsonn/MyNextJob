# ClaimPilot

ClaimPilot is a control plane for an insurance-claims agent. Phase 1 runs a supervisor with intake, verification, and coverage workers over the seeded book. Phase 2 adds idempotent payouts and portal notes, loop and budget limits, a provider pool, and an approval page. Phase 3 adds the model router, hybrid retrieval, memory, and PDF ingestion. Phase 4 adds guardrails, the red-team suite, and the admin console. Phase 5 adds the legacy-portal agent and the claim-status voice path. Phase 6 adds the trace page, the walkthrough, and this report. Model calls go through one provider interface. The demo and the tests use a scripted fake, so no provider key is required.

All people, policies, claims, and payments in this repository are synthetic. Phone numbers use the reserved `555-01xx` range. Email addresses use `example.com`, `example.net`, and `example.org`. Policy documents carry the watermark `SYNTHETIC - NOT A REAL POLICY`. Nothing here is a real customer or a real payment rail.

## Quickstart

You do not need an API key, an Ollama install, or a `.env` file to run the demo or the tests. Copy `deploy/env.example` to `.env` only if you want Docker Compose to use your own database password. The committed example values are local placeholders.

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m services.demo
```

Open http://127.0.0.1:8080 for the customer desk. Start a call to keep the microphone open until you press End call or the agent transfers you; Send text stays available either way. Steps stay on the page and are not spoken. Open http://127.0.0.1:8080/admin and paste the `ADMIN_TOKEN` from `deploy/env.example` for claims, traces, audit, and policy upload. Without keys, a claim-status fact still comes from the book. With `CLAIMPILOT_LIVE_MODELS=1` in a gitignored `.env`, the demo loads that file and routes turns through Groq `openai/gpt-oss-20b`, Groq `openai/gpt-oss-120b` for coverage questions, then Cerebras `gpt-oss-120b` and Gemini `gemini-3.8-flash`. The customer call can use read-only tools only. A manual script is in `docs/demo/manual-checks.md`. Do not put keys in the repo. Ollama is not required.

```bash
.venv\Scripts\python -m pytest
```

That is `make test` when GNU Make is on your PATH. It does not start Docker or call a model.

`make up` starts Postgres with pgvector and Redis, applies migrations, and loads the synthetic book. `make seed` loads again. `make demo` is the same server as the command above. `make eval` reruns the golden scenarios and the walkthrough. The voice and Langfuse profiles stay off until you ask for them. They download images and are not required for the scores in this file.

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
| Trajectory quality | 85% or more average score | 1.0 mean on the 30 golden scenarios (`evals/baselines/phase-1.json`) |
| Voice | p50 under 1.5 s, p95 under 3 s | offline pipeline p50 and p95 are under those bounds; this is not a Whisper or Piper run |
| Regression | CI fails on a drop over 3 points | the golden test fails the build if any scenario score changes |

## Limitations

The three-minute video is a script in `docs/demo/three-minute.md`. It is not recorded in this repository. The portal agent drives the Flask portal in-process; Playwright is not on the test path. Voice is one claim-status flow with a scripted recognizer, not the Compose speech containers. Admin roles are four synthetic bearer tokens. All 30 golden scenarios score 1.0. Live provider keys stay in a gitignored `.env`. Ollama is not required; Groq `openai/gpt-oss-20b` fills that slot. Charts, the settings editor, the customers page, and the platform-health page were the screens the plan says to cut. Retrieval, the cache, and reranking use a hashing embedding, not a model. The graph load is parameterised, and tests record those statements instead of opening Neo4j. OCR reads the synthetic bitmap font; Tesseract is not on the test path, and the original blank scans stay flagged for review. Memory, document versions, and the audit log are in-memory because the schema appendix does not define those tables. Chaos tests do not open Redis or Postgres. Langfuse starts empty aside from the hello-world trace. The evaluation write-up is `docs/evaluation-report.md`. The walkthrough is `docs/demo/walkthrough.md`.
