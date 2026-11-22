"""Date-aware retrieval with one corrective retry and a no-guess fallback."""

from __future__ import annotations

from typing import Any

from services.knowledge.hashing import tokens
from services.knowledge.retrieve import ChunkIndex


def answer(
    index: ChunkIndex,
    tenant_id: str,
    policy_id: str,
    question: str,
    on_date: str,
    *,
    graph_note: str | None = None,
) -> dict[str, Any]:
    attempts = 0
    current = question
    hits: list[dict[str, Any]] = []
    while attempts < 2:
        attempts += 1
        hits = index.search(tenant_id, policy_id, current, on_date, limit=5)
        if _grade(current, hits) >= 0.34 or attempts == 2:
            break
        current = current + " coverage clause"
    graded = _grade(question, hits)
    if graded < 0.34:
        return {
            "escalated": True,
            "reason": "not_in_policy",
            "attempts": attempts,
            "citations": [],
            "graph_note": graph_note,
        }
    return {
        "escalated": False,
        "reason": "cited",
        "attempts": attempts,
        "citations": [
            {
                "document_id": hit["document_id"],
                "version": hit["version"],
                "page": hit["page"],
                "clause_id": hit["clause_id"],
            }
            for hit in hits
            if _grade(question, [hit]) > 0
        ],
        "graph_note": graph_note,
    }


def _grade(question: str, hits: list[dict[str, Any]]) -> float:
    query = set(tokens(question))
    if not query or not hits:
        return 0.0
    best = 0.0
    for hit in hits:
        terms = set(tokens(str(hit["text"])))
        best = max(best, len(query & terms) / len(query))
    return best
