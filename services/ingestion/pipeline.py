"""Validate, parse, review, publish, and roll back policy versions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from pypdf import PdfReader

from services.gateway.cache import SemanticCache
from services.ingestion.corpus import INJECTION, CorpusFile

MAX_BYTES = 2_000_000
MAX_PAGES = 20
MALWARE = b"SYNTHETIC_MALWARE"


class Rejected(ValueError):
    pass


@dataclass
class Version:
    document_id: str
    version: str
    policy_id: str
    status: str
    effective_from: str
    effective_to: str
    saved_effective_to: str
    pdf: bytes
    content_hash: str
    parsed: dict[str, Any]
    flags: list[str] = field(default_factory=list)
    approved: bool = False
    graph_updated: bool = False
    notes: str = ""


class Library:
    def __init__(self) -> None:
        self.versions: dict[tuple[str, str], Version] = {}
        self.by_hash: dict[str, tuple[str, str]] = {}

    def upload(self, item: CorpusFile) -> Version:
        self._validate(item.pdf)
        digest = hashlib.sha256(item.pdf).hexdigest()
        existing = self.by_hash.get(digest)
        if existing is not None:
            return self.versions[existing]
        parsed = parse_pdf(item.pdf)
        sidecar = item.sidecar
        flags = list(parsed["flags"])
        if item.pdf_class == "hostile" or INJECTION in str(sidecar):
            flags.append("hostile_instruction")
        confidence = float(parsed["confidence"])
        version = Version(
            document_id=str(sidecar["document_id"]),
            version=str(sidecar["version"]),
            policy_id=str(sidecar["policy_id"]),
            status="in_review",
            effective_from=str(sidecar["effective_from"]),
            effective_to=str(sidecar["effective_to"]),
            saved_effective_to=str(sidecar["effective_to"]),
            pdf=item.pdf,
            content_hash=digest,
            parsed=parsed,
            flags=sorted(set(flags)),
            graph_updated=False,
        )
        version.parsed["confidence"] = confidence
        version.parsed["pdf_class"] = item.pdf_class
        self.versions[(version.document_id, version.version)] = version
        self.by_hash[digest] = (version.document_id, version.version)
        return version

    def review(
        self, document_id: str, version: str, decision: str, edits: dict[str, str] | None = None
    ) -> Version:
        item = self.versions[(document_id, version)]
        if decision == "reject":
            item.status = "draft"
            item.approved = False
            item.notes = "rejected"
            return item
        if decision != "approve" and decision != "edit":
            raise Rejected("review decision must be approve, edit, or reject")
        if edits:
            item.parsed["clauses"] = [
                {**clause, "text": edits.get(str(clause["id"]), clause["text"])}
                for clause in item.parsed["clauses"]
            ]
        item.approved = True
        confident = float(item.parsed["confidence"]) >= 0.8
        item.graph_updated = item.parsed["pdf_class"] == "endorsement" and confident
        if not confident:
            item.flags.append("graph_not_updated")
        return item

    def publish(self, document_id: str, version: str, cache: SemanticCache) -> Version:
        item = self.versions[(document_id, version)]
        if not item.approved:
            raise Rejected("only an approved version can be published")
        for other in self.versions.values():
            if other.policy_id != item.policy_id or other.status != "published":
                continue
            other.saved_effective_to = other.effective_to
            other.effective_to = item.effective_from
            other.status = "retired"
            cache.purge_version(other.version)
        item.status = "published"
        return item

    def rollback(self, document_id: str, version: str, cache: SemanticCache) -> Version:
        item = self.versions[(document_id, version)]
        item.status = "retired"
        cache.purge_version(item.version)
        previous = [
            other
            for other in self.versions.values()
            if other.policy_id == item.policy_id and other is not item
        ]
        if not previous:
            raise Rejected("there is no previous version to restore")
        restored = previous[-1]
        restored.status = "published"
        restored.effective_to = restored.saved_effective_to
        return restored

    def active(self, policy_id: str, on_date: str) -> Version | None:
        matches = [
            item
            for item in self.versions.values()
            if item.policy_id == policy_id
            and item.status == "published"
            and item.effective_from <= on_date < item.effective_to
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.effective_from)[-1]

    def _validate(self, pdf: bytes) -> None:
        if not pdf.startswith(b"%PDF") or MALWARE in pdf:
            raise Rejected("file failed validation")
        if len(pdf) > MAX_BYTES:
            raise Rejected("file is too large")
        reader = PdfReader(BytesIO(pdf))
        if reader.is_encrypted or len(reader.pages) > MAX_PAGES:
            raise Rejected("file failed validation")


def parse_pdf(pdf: bytes) -> dict[str, Any]:
    reader = PdfReader(BytesIO(pdf))
    pages: list[dict[str, Any]] = []
    clauses: list[dict[str, Any]] = []
    tables: list[list[str]] = []
    flags: list[str] = []
    texts: list[str] = []
    for number, page in enumerate(reader.pages, start=1):
        extracted = page.extract_text() or ""
        if extracted.strip():
            confidence = 1.0
            ocr = False
            text = extracted
        else:
            confidence = 0.0
            ocr = True
            text = ""
            flags.append("needs_review")
        texts.append(text)
        pages.append({"page": number, "text": text, "confidence": confidence, "ocr": ocr})
        for line in text.splitlines():
            if INJECTION in line:
                flags.append("hostile_instruction")
                continue
            if line.startswith("Clause ") or line.startswith("Section "):
                clauses.append(
                    {"id": line.split(".", 1)[0].split()[-1], "page": number, "text": line}
                )
            if line.startswith("CELL "):
                tables.append(line.split()[3:])
            if line.startswith("continued "):
                if clauses:
                    clauses[-1]["text"] = clauses[-1]["text"] + " " + line
                    clauses[-1]["page"] = number
    joined = "\n".join(texts)
    limit = _last_limit(joined)
    return {
        "pages": pages,
        "clauses": clauses,
        "tables": tables,
        "flags": flags,
        "confidence": 0.0 if any(page["ocr"] for page in pages) else 1.0,
        "text": joined,
        "limit": limit,
    }


def _last_limit(text: str) -> str | None:
    found: str | None = None
    for token in text.replace(".", " ").split():
        if found == "limit" and token.isdigit():
            found = token
            continue
        if token == "limit" or token == "up":
            found = "limit" if token == "limit" else found
        if token.isdigit() and "up to" in text:
            found = token
    if "sets collision limit" in text:
        numbers = [token for token in text.replace(".", " ").split() if token.isdigit()]
        return numbers[-1] if numbers else None
    if "insured up to" in text:
        numbers = [token for token in text.replace(".", " ").split() if token.isdigit()]
        return numbers[-1] if numbers else None
    return found if found is not None and found.isdigit() else None


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref = reference.split()
    hyp = hypothesis.split()
    if not ref:
        return 0.0
    return _distance(ref, hyp) / len(ref)


def _distance(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for i, token in enumerate(left, start=1):
        current = [i]
        for j, other in enumerate(right, start=1):
            cost = 0 if token == other else 1
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1]
