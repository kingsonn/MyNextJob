"""Deterministic hybrid retrieval over policy clause sidecars."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.knowledge.hashing import embed, tokens


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("expected a string column")
    return value


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
                    effective_start=_text(row["effective_start"]),
                    effective_end=_text(row["effective_end"]),
                    embedding=embed(_text(row["text"])),
                )
            )
        self.chunks = chunks

    def search(
        self, tenant_id: str, policy_id: str, query: str, on_date: str
    ) -> list[dict[str, Any]]:
        query_embedding = embed(query)
        query_terms = set(tokens(query))
        scored: list[tuple[float, str, _Chunk]] = []
        for chunk in self.chunks:
            if chunk.tenant_id != tenant_id or chunk.policy_id != policy_id:
                continue
            if not (chunk.effective_start <= on_date <= chunk.effective_end):
                continue
            keyword = 0.0
            if query_terms:
                keyword = len(query_terms & set(tokens(chunk.text))) / len(query_terms)
            cosine = sum(
                left * right for left, right in zip(query_embedding, chunk.embedding, strict=True)
            )
            score = (0.5 * keyword) + (0.5 * max(cosine, 0.0))
            scored.append((score, chunk.clause_id, chunk))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [
            {
                "document_id": chunk.document_id,
                "version": chunk.version,
                "page": chunk.page,
                "clause_id": chunk.clause_id,
                "text": chunk.text,
            }
            for _, _, chunk in scored[:3]
        ]
