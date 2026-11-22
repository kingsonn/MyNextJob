"""In-memory dataset and its canonical checksum."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from generator import GENERATOR_VERSION


def canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(slots=True)
class DocumentArtifact:
    document_id: str
    pdf_bytes: bytes
    text: str
    sidecar: dict[str, object]


@dataclass(slots=True)
class Dataset:
    seed: int
    tenants: list[dict[str, object]]
    customers: list[dict[str, object]]
    policies: list[dict[str, object]]
    coverages: list[dict[str, object]]
    endorsements: list[dict[str, object]]
    providers: list[dict[str, object]]
    adjusters: list[dict[str, object]]
    claims: list[dict[str, object]]
    payments: list[dict[str, object]]
    interactions: list[dict[str, object]]
    policy_documents: list[dict[str, object]]
    faq_pages: list[dict[str, object]]
    planted_scenarios: list[dict[str, object]]
    idempotency_keys: list[dict[str, object]]
    documents: list[DocumentArtifact]
    golden: list[dict[str, object]]

    def tables(self) -> dict[str, list[dict[str, object]]]:
        return {
            "tenants": self.tenants,
            "customers": self.customers,
            "policies": self.policies,
            "coverages": self.coverages,
            "endorsements": self.endorsements,
            "providers": self.providers,
            "adjusters": self.adjusters,
            "claims": self.claims,
            "payments": self.payments,
            "interactions": self.interactions,
            "policy_documents": self.policy_documents,
            "faq_pages": self.faq_pages,
            "planted_scenarios": self.planted_scenarios,
            "idempotency_keys": self.idempotency_keys,
        }

    def canonical(self) -> dict[str, object]:
        documents: list[dict[str, object]] = []
        for document in self.documents:
            documents.append(
                {
                    "id": document.document_id,
                    "text": document.text,
                    "sidecar": document.sidecar,
                    "pdf_sha256": sha256_hex(document.pdf_bytes),
                }
            )
        return {
            "tables": self.tables(),
            "documents": documents,
            "golden": self.golden,
        }

    def checksum(self) -> str:
        return sha256_hex(canonical_bytes(self.canonical()))

    def manifest(self) -> dict[str, object]:
        counts = {name: len(rows) for name, rows in self.tables().items()}
        counts["documents"] = len(self.documents)
        counts["golden"] = len(self.golden)
        return {
            "seed": self.seed,
            "generator_version": GENERATOR_VERSION,
            "counts": counts,
            "checksum": self.checksum(),
        }
