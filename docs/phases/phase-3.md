### Phase 3: Intelligence and PDF ingestion (weeks 9 to 12)

- [x] Build the model router with the policy table and escalation triggers
- [x] Build the tenant-scoped semantic cache with verification and invalidation
- [x] Index documents for hybrid retrieval with reranking and citations
- [x] Load the knowledge graph and expose parameterised Cypher tools
- [x] Build the multi-hop benchmark and compare vector, graph and combined retrieval
- [x] Implement memory layers with write filtering and a delete path
- [x] Report cost per resolved claim for routed versus single-model runs

**Added scope for PDFs (adds about one week):**

- [x] Generate the PDF corpus with sidecar ground truth, including scanned and hostile variants
- [x] Build the ingestion pipeline: validation, scan, parse with OCR fallback, structuring, review data model
- [x] Implement document versioning, effective-date filters, atomic publish and rollback
- [x] Add corrective and date-aware adaptive retrieval with page-level citations
- [x] Run the PDF evaluation set (parsing, tables, OCR, retrieval, freshness, rollback)