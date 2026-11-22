"""Router, cache safety, retrieval, memory, and the PDF evaluation set."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO

from pypdf import PdfWriter

from evals.runners.multihop import run
from services.catalog.store import Catalog
from services.contracts.envelope import ScopedToken
from services.gateway.cache import SemanticCache, UnavailableCache, safe_get
from services.gateway.cost import compare
from services.gateway.router import classify, load_policy, route
from services.ingestion.adaptive import answer
from services.ingestion.corpus import COUNTS, INJECTION, build_corpus
from services.ingestion.pipeline import Library, Rejected, Version, parse_pdf, word_error_rate
from services.knowledge.memory import MemoryStore
from services.knowledge.retrieve import ChunkIndex
from services.mcp.dispatch import call_tool
from services.paths import repo_root

NOW = datetime(2026, 1, 1)


def test_router_policy_and_escalation() -> None:
    policy = load_policy()
    assert policy["faq"]["primary"] == "cache"
    assert policy["payout"]["approval"] is True
    assert classify("What is a deductible?") == "faq"
    assert classify("Please extract the loss date") == "extraction"
    low = route("classification", confidence=0.2)
    assert low.tier == "fast" and "low_confidence" in low.reason
    extracted = route("extraction", schema_failures=2)
    assert extracted.tier == "strong" and "schema_validation" in extracted.reason
    disagreed = route("coverage", guardrail_disagreement=True)
    assert disagreed.tier == "human"
    uncited = route("faq", citation_failed=True)
    assert uncited.tier == "local"
    payout = route("payout", confidence=1.0)
    assert payout.tier == "strong" and payout.approval_required is True
    assert route("voice").tier == "local"


def test_routed_cost_is_lower_than_one_model() -> None:
    cases = [("faq", 100)] * 10 + [("classification", 100)] * 10 + [("coverage", 100)] * 10
    report = compare(cases)
    assert report["resolved"] == 30
    assert report["routed_micros"] < report["single_micros"] * 0.6
    assert report["routed_micros_per_claim"] < report["single_micros"] / 30


def test_cache_false_hits_and_a_dead_cache_is_a_miss() -> None:
    import yaml

    labelled = yaml.safe_load(
        (repo_root() / "services" / "gateway" / "false_hits.yaml").read_text()
    )
    cache = SemanticCache()
    negatives = 0
    false_hits = 0
    for pair in labelled["pairs"]:
        cache.put(
            tenant_id="ten_01",
            language="en",
            policy_version="v1",
            model_tier="fast",
            question=pair["cached"],
            answer="500",
            now=NOW,
            token_cost=12,
        )
        found = cache.get(
            tenant_id="ten_01",
            language="en",
            policy_version="v1",
            model_tier="fast",
            question=pair["probe"],
            now=NOW,
        )
        if pair["same_meaning"]:
            assert found == "500"
        else:
            negatives += 1
            false_hits += int(found is not None)
    assert negatives > 0 and false_hits == 0
    assert cache.saved_tokens > 0
    assert safe_get(UnavailableCache(), question="what is a deductible?") is None


def test_memory_filters_deletes_and_prefers_the_crm() -> None:
    cache = SemanticCache()
    memory = MemoryStore()
    assert memory.write("ten_01", "cus_1", "profile", "channel", "email", "customer", NOW, 0.9)
    assert (
        memory.write(
            "ten_01",
            "cus_1",
            "profile",
            "preference",
            INJECTION,
            "portal",
            NOW,
            0.2,
        )
        is False
    )
    cache.put(
        tenant_id="ten_01",
        language="en",
        policy_version="v1",
        model_tier="fast",
        question="what is a deductible?",
        answer="email",
        now=NOW,
        customer_id="cus_1",
    )
    assert memory.reconcile("ten_01", "cus_1", {"channel": "phone"}) == 1
    shown = memory.show("ten_01", "cus_1")
    assert shown[0]["value"] == "phone" and shown[0]["source"] == "crm"
    assert memory.show("ten_02", "cus_1") == []
    assert memory.delete("ten_01", "cus_1", cache) == 1
    assert memory.show("ten_01", "cus_1") == []
    assert cache.purge_customer("ten_01", "cus_1") == 0


def test_multihop_graph_beats_vector_on_the_hundred() -> None:
    report = run()
    assert report["questions"] == 100
    assert report["multi_hop_gain"] >= 0.15
    assert report["simple_combined"] >= report["simple_vector"]
    assert report["simple_combined_retrievals"] == report["simple_vector_retrievals"]


def test_impact_template_lists_the_active_policy() -> None:
    catalog = Catalog(
        {
            "policies": [
                {
                    "id": "pol_000001",
                    "tenant_id": "ten_01",
                    "customer_id": "cus_000001",
                    "type": "auto",
                    "status": "active",
                    "start_date": "2023-01-01",
                    "end_date": "2024-01-01",
                    "premium": 1,
                    "coverage_language": "covered",
                }
            ],
            "endorsements": [
                {
                    "id": "end_000001",
                    "tenant_id": "ten_01",
                    "policy_id": "pol_000001",
                    "effective_on": "2023-03-03",
                }
            ],
        }
    )
    token = ScopedToken(
        tenant_id="ten_01", task="graph", allowed_tools=["graph.impact"], trace_id="trace-impact"
    )
    found = call_tool(catalog, token, "graph.impact", {"entity_id": "end_000001"})
    assert found.data["policy_ids"] == ["pol_000001"]


def test_pdf_evaluation_set() -> None:
    corpus = build_corpus()
    assert {name: sum(item.pdf_class == name for item in corpus) for name in COUNTS} == COUNTS
    assert sum(item.holdout for item in corpus) == 10
    library = Library()
    cache = SemanticCache()
    loaded = [library.upload(item) for item in corpus if not item.holdout]
    assert len(loaded) == len(corpus) - 10
    again = library.upload(next(item for item in corpus if not item.holdout))
    assert again.content_hash == loaded[0].content_hash or again.document_id

    digital = [item for item in corpus if item.pdf_class == "digital" and not item.holdout]
    recalled = 0
    cited = 0
    for item in digital:
        version = library.versions[(item.document_id, str(item.sidecar["version"]))]
        for clause in item.sidecar["clauses"]:
            text = str(clause["text"])
            recalled += int(text in version.parsed["text"] or text in _clause_text(version))
            if any(
                hit["page"] == clause["page"] and text in str(hit["text"])
                for hit in version.parsed["clauses"]
            ):
                cited += 1
    clause_count = sum(len(item.sidecar["clauses"]) for item in digital)
    assert recalled / clause_count >= 0.95
    assert cited / clause_count >= 0.90

    tables = [item for item in corpus if item.pdf_class == "table"]
    cells = 0
    matched = 0
    for item in tables:
        version = library.versions[(item.document_id, "v1")]
        for row in item.sidecar["tables"][0]["cells"]:
            for cell in row:
                cells += 1
                matched += int(str(cell) in version.parsed["text"])
    assert matched / cells >= 0.90

    scanned_rates: dict[str, list[float]] = {"skew": [], "noise": [], "low_resolution": []}
    for item in corpus:
        if item.pdf_class != "scanned" or item.holdout:
            continue
        version = library.versions[(item.document_id, "v1")]
        reference = str(item.sidecar["clauses"][0]["text"])
        scanned_rates[str(item.sidecar["degradation"])].append(
            word_error_rate(reference, version.parsed["text"])
        )
        assert "needs_review" in version.flags
    assert scanned_rates["skew"] and min(scanned_rates["skew"]) == 1.0

    hostile = [item for item in corpus if item.pdf_class == "hostile" and not item.holdout]
    for item in hostile:
        version = library.versions[(item.document_id, "v1")]
        assert "hostile_instruction" in version.flags
        assert all(INJECTION not in str(clause["text"]) for clause in version.parsed["clauses"])

    base = next(item for item in corpus if item.document_id == "doc_digital_0000")
    revised = next(item for item in corpus if item.document_id == "doc_digital_0058")
    base_version = library.versions[(base.document_id, "v1")]
    library.review(base.document_id, "v1", "approve")
    library.publish(base.document_id, "v1", cache)
    cache.put(
        tenant_id="ten_01",
        language="en",
        policy_version="v1",
        model_tier="fast",
        question="what is a deductible?",
        answer="100",
        now=NOW,
    )
    revised_version = library.upload(revised)
    library.review(revised.document_id, "v2", "approve")
    library.publish(revised.document_id, "v2", cache)
    assert (
        cache.get(
            tenant_id="ten_01",
            language="en",
            policy_version="v1",
            model_tier="fast",
            question="what is a deductible?",
            now=NOW,
        )
        is None
    )
    current = library.active("pol_p3_0000", "2023-06-01")
    assert current is not None and current.parsed["limit"] == "999"
    library.rollback(revised.document_id, "v2", cache)
    restored = library.active("pol_p3_0000", "2023-06-01")
    assert restored is not None and restored.parsed["limit"] == "100"
    assert base_version.status == "published"
    assert revised_version.status == "retired"

    rows = []
    published = library.active("pol_p3_0000", "2023-06-01")
    assert published is not None
    for clause in published.parsed["clauses"]:
        rows.append(
            {
                "tenant_id": "ten_01",
                "policy_id": "pol_p3_0000",
                "document_id": published.document_id,
                "version": published.version,
                "clause_id": clause["id"],
                "page": clause["page"],
                "text": clause["text"],
                "effective_start": "2023-01-01",
                "effective_end": "2024-01-01",
            }
        )
    found = answer(ChunkIndex(rows), "ten_01", "pol_p3_0000", "collision insured", "2023-06-01")
    assert found["escalated"] is False and found["citations"]
    missed = answer(ChunkIndex(rows), "ten_01", "pol_p3_0000", "zzzz", "2023-06-01")
    assert missed["escalated"] is True and missed["attempts"] == 2 and missed["citations"] == []
    outside = answer(ChunkIndex(rows), "ten_01", "pol_p3_0000", "collision insured", "2024-06-01")
    assert outside["escalated"] is True


def test_upload_rejects_malware_and_encrypted_files() -> None:
    library = Library()
    sample = next(item for item in build_corpus() if item.pdf_class == "digital")
    poisoned = sample.__class__(
        sample.document_id,
        sample.pdf_class,
        sample.holdout,
        sample.pdf + b"SYNTHETIC_MALWARE",
        sample.sidecar,
    )
    try:
        library.upload(poisoned)
    except Rejected:
        pass
    else:
        raise AssertionError("malware marker was accepted")
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("synthetic")
    buffer = BytesIO()
    writer.write(buffer)
    encrypted = sample.__class__(
        "doc_encrypted",
        "digital",
        False,
        buffer.getvalue(),
        sample.sidecar,
    )
    try:
        library.upload(encrypted)
    except Rejected:
        return
    raise AssertionError("encrypted pdf was accepted")


def _clause_text(version: Version) -> str:
    return " ".join(str(clause["text"]) for clause in version.parsed["clauses"])


def test_parser_reads_a_digital_clause() -> None:
    item = next(entry for entry in build_corpus() if entry.document_id == "doc_digital_0000")
    parsed = parse_pdf(item.pdf)
    assert "100" in str(parsed["limit"])
