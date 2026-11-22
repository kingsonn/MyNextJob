"""Tenant-scoped semantic cache. Eligibility and verification stay in code."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from services.knowledge.hashing import embed, tokens


def eligible(question: str) -> bool:
    lowered = question.lower()
    blocked = ("clm_", "cus_", "pol_", "+1-555", "@")
    return not any(marker in lowered for marker in blocked)


def _overlap(left: str, right: str) -> float:
    left_terms = set(tokens(left))
    right_terms = set(tokens(right))
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


@dataclass
class _Entry:
    namespace: tuple[str, str, str, str]
    question: str
    answer: str
    embedding: tuple[float, ...]
    expires_at: datetime


class SemanticCache:
    def __init__(
        self,
        *,
        similarity: float = 0.92,
        verifier_overlap: float = 0.9,
        ttl_seconds: int = 3600,
    ) -> None:
        self.similarity = similarity
        self.verifier_overlap = verifier_overlap
        self.ttl = timedelta(seconds=ttl_seconds)
        self.entries: list[_Entry] = []

    def put(
        self,
        *,
        tenant_id: str,
        language: str,
        policy_version: str,
        model_tier: str,
        question: str,
        answer: str,
        now: datetime,
    ) -> bool:
        if not eligible(question):
            return False
        self.entries.append(
            _Entry(
                (tenant_id, language, policy_version, model_tier),
                question,
                answer,
                embed(question),
                now + self.ttl,
            )
        )
        return True

    def get(
        self,
        *,
        tenant_id: str,
        language: str,
        policy_version: str,
        model_tier: str,
        question: str,
        now: datetime,
    ) -> str | None:
        if not eligible(question):
            return None
        namespace = (tenant_id, language, policy_version, model_tier)
        query = embed(question)
        for entry in self.entries:
            if entry.namespace != namespace or entry.expires_at <= now:
                continue
            if _cosine(query, entry.embedding) < self.similarity:
                continue
            if _overlap(question, entry.question) < self.verifier_overlap:
                continue
            return entry.answer
        return None

    def purge_version(self, policy_version: str) -> int:
        before = len(self.entries)
        self.entries = [entry for entry in self.entries if entry.namespace[2] != policy_version]
        return before - len(self.entries)
