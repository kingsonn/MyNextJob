### Phase 3: Intelligence and PDF ingestion (weeks 9 to 12)

- [ ] Build the model router with the policy table and escalation triggers
- [ ] Build the tenant-scoped semantic cache with verification and invalidation
- [ ] Index documents for hybrid retrieval with reranking and citations
- [ ] Load the knowledge graph and expose parameterised Cypher tools
- [ ] Build the multi-hop benchmark and compare vector, graph and combined retrieval
- [ ] Implement memory layers with write filtering and a delete path
- [ ] Report cost per resolved claim for routed versus single-model runs

**Added scope for PDFs (adds about one week):**

- [ ] Generate the PDF corpus with sidecar ground truth, including scanned and hostile variants
- [ ] Build the ingestion pipeline: validation, scan, parse with OCR fallback, structuring, review data model
- [ ] Implement document versioning, effective-date filters, atomic publish and rollback
- [ ] Add corrective and date-aware adaptive retrieval with page-level citations
- [ ] Run the PDF evaluation set (parsing, tables, OCR, retrieval, freshness, rollback)