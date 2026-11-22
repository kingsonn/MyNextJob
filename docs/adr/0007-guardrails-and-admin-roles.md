# Guardrails and admin roles without a new table

Phase 4 needs independent checks, an append-only audit log, and server-side roles. Appendix A does not define an audit table. The test gate still forbids network calls.

## Decision

Guardrail verdicts come from rules: injection markers, allow-lists, citations, and the approval token. A checker exception blocks a payout and allows a FAQ, and the FAQ path records `fail_open`.

The audit log is an in-memory append-only list. There is no update or delete route. PII is tokenised before it is shown. Reveal requires a reason and writes a row.

Admin routes use four synthetic bearer tokens from `deploy/env.example`. Deny by default. Uploaded bytes stay on the library object, not on a web path.

Scanned-page OCR is a bitmap reader for the synthetic font. The Neo4j load sends parameterised statements to a session; tests record that session and do not connect. The 50 crash trials use the idempotency machine and the graph checkpointer.

## Consequences

The red-team block rate is measured on the versioned case file, including four misses. It is not a live-model attack suite. Tesseract and a running Neo4j are still outside `make test`.
