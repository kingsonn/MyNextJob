# Offline routing, retrieval, and PDF ingestion

Phase 3 needs a model router, a verified cache, hybrid retrieval, a knowledge graph, memory, and a PDF pipeline. The test gate still forbids network and model calls, and Appendix A does not define memory or document-version tables.

## Decision

The router is a versioned policy table plus rules. Escalation is low confidence, a second schema failure, a failed citation check, or a guardrail disagreement. A financial task always keeps the approval requirement. Cost is the shadow price of the chosen tier against the strong tier on the same token counts.

Retrieval stays on the hashing embedding. Hybrid search fuses keyword and vector ranks, then reranks by token overlap. The cache verifier is the same overlap check. A labelled near-duplicate set measures false hits. If the cache backend is down, lookup is a miss.

The graph tools stay parameterised. `graph.impact` answers which active policy an endorsement touches. The multi-hop set is 100 questions built from those tables: 40 answers sit in one clause, and 60 answers exist only on the rider record.

Memory is an in-memory store with source, time, and confidence. Instruction-like text is dropped. Delete removes that customer's items and cache derivatives. A conflicting CRM field overwrites the memory item. No new database table is added.

PDFs are generated with sidecars beside the Phase 0 corpus, so the Phase 0 manifest does not change. Parsing uses the text layer. A page with no text is an OCR miss at confidence 0 and is flagged for review. Tesseract, Ollama, Neo4j, and ClamAV are not on the `make test` path. The malware check is a synthetic marker in the bytes.

## Consequences

The measured routing saving and the multi-hop gap are properties of this offline set, not of a live model. Scanned pages are reported as unreadable until a local OCR engine is added. Admin upload screens stay in Phase 4.
