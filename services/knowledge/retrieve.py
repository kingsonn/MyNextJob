"""Deterministic hybrid retrieval over policy clause sidecars."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.knowledge.hashing import embed, tokens


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("expected a string column")
    return value


def _optional(row: dict[str, object], key: str) -> str:
    value = row.get(key, "")
    return value if isinstance(value, str) else ""


def _matches(value: str, expected: str | None) -> bool:
    return expected is None or value == expected


def _keyword(query_terms: set[str], text: str) -> float:
    if not query_terms:
        return 0.0
    return len(query_terms & set(tokens(text))) / len(query_terms)


def _rank(chunks: list[_Chunk], score_of: Any) -> dict[int, int]:
    ordered = sorted(chunks, key=lambda chunk: (-float(score_of(chunk)), chunk.clause_id))
    return {id(chunk): index for index, chunk in enumerate(ordered, start=1)}


@dataclass(frozen=True)
class SourceDocument:
    document_id: str
    sidecar: dict[str, object]


@dataclass(frozen=True)
class _Chunk:
    tenant_id: str
    policy_id: str
    document_id: str
    version: str
    clause_id: str
    page: int
    text: str
    parent: str
    policy_type: str
    jurisdiction: str
    effective_start: str
    effective_end: str
    embedding: tuple[float, ...]


class ChunkIndex:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        chunks: list[_Chunk] = []
        for row in rows:
            page = row["page"]
            chunks.append(
                _Chunk(
                    tenant_id=_text(row["tenant_id"]),
                    policy_id=_text(row["policy_id"]),
                    document_id=_text(row["document_id"]),
                    version=_text(row["version"]),
                    clause_id=_text(row["clause_id"]),
                    page=page if isinstance(page, int) else 0,
                    text=_text(row["text"]),
                    parent=_optional(row, "parent"),
                    policy_type=_optional(row, "policy_type"),
                    jurisdiction=_optional(row, "jurisdiction"),
                    effective_start=_text(row["effective_start"]),
                    effective_end=_text(row["effective_end"]),
                    embedding=embed(_text(row["text"])),
                )
            )
        self.chunks = chunks

    def search(
        self,
        tenant_id: str,
        policy_id: str,
        query: str,
        on_date: str,
        *,
        limit: int = 3,
        policy_type: str | None = None,
        jurisdiction: str | None = None,
    ) -> list[dict[str, Any]]:
        """Keyword plus vector search, fused with reciprocal rank and a token rerank."""

        candidates = [
            chunk
            for chunk in self.chunks
            if chunk.tenant_id == tenant_id
            and chunk.policy_id == policy_id
            and chunk.effective_start <= on_date <= chunk.effective_end
            and _matches(chunk.policy_type, policy_type)
            and _matches(chunk.jurisdiction, jurisdiction)
        ]
        if not candidates:
            return []
        query_terms = set(tokens(query))
        query_embedding = embed(query)
        keyword_rank = _rank(candidates, lambda chunk: _keyword(query_terms, chunk.text))
        vector_rank = _rank(
            candidates,
            lambda chunk: sum(
                left * right for left, right in zip(query_embedding, chunk.embedding, strict=True)
            ),
        )
        fused = [
            (
                (1.0 / (60 + keyword_rank[id(chunk)])) + (1.0 / (60 + vector_rank[id(chunk)])),
                _keyword(query_terms, chunk.text),
                chunk,
            )
            for chunk in candidates
        ]
        fused.sort(key=lambda item: (-item[0], item[2].clause_id))
        reranked = sorted(fused[:10], key=lambda item: (-item[1], item[2].clause_id))
        return [
            {
                "document_id": chunk.document_id,
                "version": chunk.version,
                "page": chunk.page,
                "clause_id": chunk.clause_id,
                "text": chunk.text,
                "parent": chunk.parent,
            }
            for _, _, chunk in reranked[:limit]
        ]
