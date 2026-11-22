"""Small catalogs for contract tests. The golden run uses the full generator."""

from __future__ import annotations

from services.catalog.store import Catalog
from services.knowledge.retrieve import SourceDocument


def loss_catalog(*, verified: bool = True) -> Catalog:
    customer = {
        "id": "cus_000001",
        "tenant_id": "ten_01",
        "name": "Ada Example",
        "dob": "1990-01-01",
        "address": "1 Synthetic Street, Synthetic City, us-east",
        "phone": "+1-555-0101",
        "email": "cus_000001@example.com",
        "language": "en",
        "risk_segment": "standard",
        "identity_verified": verified,
    }
    policy = {
        "id": "pol_000001",
        "tenant_id": "ten_01",
        "customer_id": "cus_000001",
        "type": "auto",
        "status": "active",
        "start_date": "2023-01-01",
        "end_date": "2024-01-01",
        "premium": 100_000,
        "coverage_language": "Covered perils are paid subject to the stated limit and deductible.",
    }
    claim = {
        "id": "clm_000001",
        "tenant_id": "ten_01",
        "policy_id": "pol_000001",
        "loss_date": "2024-01-02",
        "type": "collision",
        "amount": 50_000,
        "status": "submitted",
        "adjuster_id": "adj_01",
        "provider_id": None,
        "portal_note": None,
        "submission_key": "sub:clm_000001",
    }
    return Catalog(
        {
            "customers": [customer],
            "policies": [policy],
            "claims": [claim],
            "coverages": [],
            "endorsements": [],
            "providers": [],
            "interactions": [],
            "policy_documents": [],
        }
    )


def ambiguous_catalog() -> Catalog:
    policy = {
        "id": "pol_000441",
        "tenant_id": "ten_01",
        "customer_id": "cus_000001",
        "type": "auto",
        "status": "active",
        "start_date": "2023-01-01",
        "end_date": "2024-01-01",
        "premium": 100_000,
        "coverage_language": "Coverage may apply depending on circumstances.",
    }
    customer = {
        "id": "cus_000001",
        "tenant_id": "ten_01",
        "name": "Ada Example",
        "dob": "1990-01-01",
        "address": "1 Synthetic Street, Synthetic City, us-east",
        "phone": "+1-555-0101",
        "email": "cus_000001@example.com",
        "language": "en",
        "risk_segment": "standard",
        "identity_verified": True,
    }
    document = {
        "id": "doc_0041",
        "tenant_id": "ten_01",
        "policy_id": "pol_000441",
        "version": "2024.1",
        "path": "data/generated/documents/doc_0041.pdf",
        "clause_count": 2,
        "watermark": "SYNTHETIC - NOT A REAL POLICY",
        "injection": None,
    }
    sidecar: dict[str, object] = {
        "document_id": "doc_0041",
        "policy_id": "pol_000441",
        "version": "2024.1",
        "effective_start": "2023-01-01",
        "effective_end": "2024-01-01",
        "clauses": [
            {
                "id": "1",
                "text": "Clause 1. collision is insured up to 100000 cents.",
                "page": 1,
            },
            {
                "id": "2",
                "text": "Clause 2. Coverage may apply depending on circumstances.",
                "page": 1,
            },
        ],
    }
    return Catalog(
        {
            "customers": [customer],
            "policies": [policy],
            "policy_documents": [document],
            "claims": [],
            "coverages": [],
            "endorsements": [],
            "providers": [],
            "interactions": [],
        },
        [SourceDocument("doc_0041", sidecar)],
    )
