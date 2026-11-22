"""In-memory book of business used by the tool servers.

Tests never open Postgres. The SQL tables are the durable copy of the same rows.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from services.knowledge.retrieve import ChunkIndex, SourceDocument

_STATED_PHONE = re.compile(r"Caller stated phone (\+1-555-01[0-9]{2})")
AMBIGUOUS_COVERAGE = "Coverage may apply depending on circumstances."
LONG_HISTORY_MIN = 30
WRITE_AT = "2026-01-01T00:00:00+00:00"


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("expected a string column")
    return value


def _flag(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError("expected a boolean column")
    return value


def fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass
class _Write:
    request_hash: str
    data: dict[str, Any]


class Catalog:
    def __init__(
        self,
        tables: dict[str, list[dict[str, object]]],
        documents: list[SourceDocument] | None = None,
    ) -> None:
        self.customers = _index(tables.get("customers", []))
        self.policies = _index(tables.get("policies", []))
        self.coverages = _index(tables.get("coverages", []))
        self.endorsements = _index(tables.get("endorsements", []))
        self.claims = _index(tables.get("claims", []))
        self.payments = _index(tables.get("payments", []))
        self.adjusters = _index(tables.get("adjusters", []))
        self.providers = _index(tables.get("providers", []))
        self.interactions = _index(tables.get("interactions", []))
        self.policy_documents = _index(tables.get("policy_documents", []))
        self.coverages_by_policy = _group(tables.get("coverages", []), "policy_id")
        self.endorsements_by_policy = _group(tables.get("endorsements", []), "policy_id")
        self.claims_by_policy = _group(tables.get("claims", []), "policy_id")
        self.interactions_by_customer = _group(tables.get("interactions", []), "customer_id")
        self.document_by_policy: dict[str, str] = {}
        for row in self.policy_documents.values():
            self.document_by_policy[_text(row["policy_id"])] = _text(row["id"])
        self.index = ChunkIndex(self._chunks(documents or []))
        self.notes: dict[tuple[str, str], _Write] = {}
        self.contact_updates: dict[tuple[str, str], _Write] = {}
        self.note_count = 0
        self.contact_count = 0

    def _chunks(self, documents: list[SourceDocument]) -> list[dict[str, object]]:
        chunks: list[dict[str, object]] = []
        for document in documents:
            row = self.policy_documents.get(document.document_id)
            if row is None:
                continue
            sidecar = document.sidecar
            clauses = sidecar.get("clauses")
            if not isinstance(clauses, list):
                continue
            for clause in clauses:
                if not isinstance(clause, dict):
                    continue
                page = clause.get("page")
                if not isinstance(page, int):
                    continue
                chunks.append(
                    {
                        "tenant_id": _text(row["tenant_id"]),
                        "policy_id": _text(sidecar["policy_id"]),
                        "document_id": document.document_id,
                        "version": _text(sidecar["version"]),
                        "clause_id": _text(clause["id"]),
                        "page": page,
                        "text": _text(clause["text"]),
                        "effective_start": _text(sidecar["effective_start"]),
                        "effective_end": _text(sidecar["effective_end"]),
                    }
                )
        return chunks

    def entity_tenant(self, entity_id: str) -> str | None:
        for table in (
            self.customers,
            self.policies,
            self.claims,
            self.payments,
            self.adjusters,
            self.endorsements,
            self.providers,
            self.policy_documents,
        ):
            row = table.get(entity_id)
            if row is not None:
                return _text(row["tenant_id"])
        return None

    def subject_customer(self, scenario: str, entity_id: str) -> str | None:
        if scenario == "provider_cluster":
            claim_ids = self._cluster_claim_ids(entity_id)
            if not claim_ids:
                return None
            policy_id = _text(self.claims[claim_ids[0]]["policy_id"])
            return _text(self.policies[policy_id]["customer_id"])
        if entity_id in self.customers:
            return entity_id
        if entity_id in self.claims:
            policy_id = _text(self.claims[entity_id]["policy_id"])
            return _text(self.policies[policy_id]["customer_id"])
        if entity_id in self.policies:
            return _text(self.policies[entity_id]["customer_id"])
        if entity_id in self.endorsements:
            policy_id = _text(self.endorsements[entity_id]["policy_id"])
            return _text(self.policies[policy_id]["customer_id"])
        return None

    def get_policy(self, tenant_id: str, entity_id: str) -> dict[str, Any] | None:
        claim = self.claims.get(entity_id)
        if claim is not None:
            if _text(claim["tenant_id"]) != tenant_id:
                return None
            matched = self.policies[_text(claim["policy_id"])]
            loss = _text(claim["loss_date"])
            start = _text(matched["start_date"])
            end = _text(matched["end_date"])
            covered = start <= loss <= end
            return {
                "covered": covered,
                "reason": "in_term" if covered else "loss_date_outside_term",
                "claim_id": entity_id,
                "policy_id": _text(matched["id"]),
                "loss_date": loss,
                "policy_start": start,
                "policy_end": end,
                "customer_id": _text(matched["customer_id"]),
            }
        policy = self.policies.get(entity_id)
        if policy is None or _text(policy["tenant_id"]) != tenant_id:
            return None
        return {
            "policy_id": entity_id,
            "policy_start": _text(policy["start_date"]),
            "policy_end": _text(policy["end_date"]),
            "customer_id": _text(policy["customer_id"]),
            "status": _text(policy["status"]),
            "type": _text(policy["type"]),
        }

    def list_coverages(self, tenant_id: str, policy_id: str) -> dict[str, Any] | None:
        policy = self.policies.get(policy_id)
        if policy is None or _text(policy["tenant_id"]) != tenant_id:
            return None
        rows = [
            {
                "id": _text(row["id"]),
                "peril": _text(row["peril"]),
                "limit_amount": row["limit_amount"],
                "deductible": row["deductible"],
            }
            for row in self.coverages_by_policy.get(policy_id, [])
        ]
        return {"policy_id": policy_id, "coverages": rows}

    def policy_version_on_date(
        self, tenant_id: str, policy_id: str, on_date: str
    ) -> dict[str, Any] | None:
        policy = self.policies.get(policy_id)
        if policy is None or _text(policy["tenant_id"]) != tenant_id:
            return None
        if not (_text(policy["start_date"]) <= on_date <= _text(policy["end_date"])):
            return None
        document_id = self.document_by_policy.get(policy_id)
        version = "2024.1" if document_id is not None else "structured-term"
        return {
            "policy_id": policy_id,
            "on_date": on_date,
            "version": version,
            "document_id": document_id,
        }

    def get_endorsements(self, tenant_id: str, entity_id: str) -> dict[str, Any] | None:
        endorsement = self.endorsements.get(entity_id)
        if endorsement is None or _text(endorsement["tenant_id"]) != tenant_id:
            return None
        policy_id = _text(endorsement["policy_id"])
        claim_id = self._earliest_claim(policy_id)
        if claim_id is None:
            return None
        loss = _text(self.claims[claim_id]["loss_date"])
        effective = _text(endorsement["effective_date"])
        return {
            "rider_applies": effective <= loss,
            "endorsement_id": entity_id,
            "claim_id": claim_id,
            "effective_date": effective,
            "loss_date": loss,
            "policy_id": policy_id,
        }

    def get_coverage(self, tenant_id: str, entity_id: str) -> dict[str, Any] | None:
        policy = self.policies.get(entity_id)
        if policy is None or _text(policy["tenant_id"]) != tenant_id:
            return None
        language = _text(policy["coverage_language"])
        ambiguous = language == AMBIGUOUS_COVERAGE
        return {
            "policy_id": entity_id,
            "document_id": self.document_by_policy.get(entity_id),
            "escalate": ambiguous,
            "confident": not ambiguous,
            "policy_start": _text(policy["start_date"]),
            "coverage_language": language,
        }

    def find_customer(self, tenant_id: str, entity_id: str) -> dict[str, Any] | None:
        customer = self._customer(tenant_id, entity_id)
        if customer is None:
            return None
        stated = self._stated_phone(entity_id)
        if stated is not None:
            interaction_id, phone = stated
            return {
                "customer_id": entity_id,
                "interaction_id": interaction_id,
                "canonical_phone": _text(customer["phone"]),
                "stated_phone": phone,
                "winner": "crm",
                "language": _text(customer["language"]),
            }
        return {
            "customer_id": entity_id,
            "language": _text(customer["language"]),
            "phone": _text(customer["phone"]),
            "email": _text(customer["email"]),
        }

    def verify_identity(self, tenant_id: str, entity_id: str) -> dict[str, Any] | None:
        customer = self._customer(tenant_id, entity_id)
        if customer is None:
            return None
        verified = _flag(customer["identity_verified"])
        return {
            "customer_id": entity_id,
            "identity_verified": verified,
            "safe_refusal": not verified,
        }

    def list_interactions(self, tenant_id: str, entity_id: str) -> dict[str, Any] | None:
        if self._customer(tenant_id, entity_id) is None:
            return None
        count = len(self.interactions_by_customer.get(entity_id, []))
        return {
            "customer_id": entity_id,
            "interaction_count": count,
            "min_interactions": LONG_HISTORY_MIN,
        }

    def add_note(
        self, tenant_id: str, customer_id: str, body: str, idempotency_key: str
    ) -> tuple[dict[str, Any], bool] | str:
        if self._customer(tenant_id, customer_id) is None:
            return "missing"
        digest = fingerprint({"body": body, "customer_id": customer_id})
        slot = (tenant_id, idempotency_key)
        existing = self.notes.get(slot)
        if existing is not None:
            if existing.request_hash != digest:
                return "conflict"
            return existing.data, True
        self.note_count += 1
        data = {
            "id": f"nte_{self.note_count:06d}",
            "customer_id": customer_id,
            "body": body,
            "created_at": WRITE_AT,
        }
        self.notes[slot] = _Write(digest, data)
        return data, False

    def update_contact(
        self,
        tenant_id: str,
        customer_id: str,
        idempotency_key: str,
        *,
        phone: str | None,
        email: str | None,
        address: str | None,
    ) -> tuple[dict[str, Any], bool] | str:
        customer = self._customer(tenant_id, customer_id)
        if customer is None:
            return "missing"
        payload = {
            "address": address,
            "customer_id": customer_id,
            "email": email,
            "phone": phone,
        }
        digest = fingerprint(payload)
        slot = (tenant_id, idempotency_key)
        existing = self.contact_updates.get(slot)
        if existing is not None:
            if existing.request_hash != digest:
                return "conflict"
            return existing.data, True
        if phone is not None:
            customer["phone"] = phone
        if email is not None:
            customer["email"] = email
        if address is not None:
            customer["address"] = address
        self.contact_count += 1
        data = {
            "id": f"ctu_{self.contact_count:06d}",
            "customer_id": customer_id,
            "created_at": WRITE_AT,
            **payload,
        }
        self.contact_updates[slot] = _Write(digest, data)
        return data, False

    def search(self, tenant_id: str, policy_id: str, query: str, on_date: str) -> dict[str, Any]:
        return {"citations": self.index.search(tenant_id, policy_id, query, on_date)}

    def coverage_path(self, tenant_id: str, entity_id: str) -> dict[str, Any] | None:
        if entity_id in self.claims:
            return self.get_policy(tenant_id, entity_id)
        if entity_id in self.endorsements:
            return self.get_endorsements(tenant_id, entity_id)
        if entity_id in self.policies:
            return self.get_coverage(tenant_id, entity_id)
        return None

    def shared_contact(self, tenant_id: str, entity_id: str) -> dict[str, Any] | None:
        customer = self._customer(tenant_id, entity_id)
        if customer is None:
            return None
        phone = _text(customer["phone"])
        address = _text(customer["address"])
        members = [
            _text(row["id"])
            for row in self.customers.values()
            if _text(row["tenant_id"]) == tenant_id
            and _text(row["phone"]) == phone
            and _text(row["address"]) == address
        ]
        return {"phone": phone, "address": address, "customer_ids": sorted(members)}

    def provider_cluster(self, tenant_id: str, entity_id: str) -> dict[str, Any] | None:
        provider = self.providers.get(entity_id)
        if provider is None or _text(provider["tenant_id"]) != tenant_id:
            return None
        claim_ids = self._cluster_claim_ids(entity_id)
        if not claim_ids:
            return None
        return {"provider_id": entity_id, "claim_ids": claim_ids}

    def _cluster_claim_ids(self, provider_id: str) -> list[str]:
        provider_row = self.providers.get(provider_id)
        if provider_row is None:
            return []
        tenant_id = _text(provider_row["tenant_id"])
        groups: dict[tuple[str, str], list[str]] = {}
        for claim in self.claims.values():
            claim_provider = claim["provider_id"]
            amount = claim["amount"]
            if not isinstance(claim_provider, str) or isinstance(amount, bool):
                continue
            if not isinstance(amount, int):
                continue
            same_tenant = _text(claim["tenant_id"]) == tenant_id
            if same_tenant and claim_provider == provider_id:
                key = (_text(claim["loss_date"]), str(amount))
                groups.setdefault(key, []).append(_text(claim["id"]))
        eligible = {key: claim_ids for key, claim_ids in groups.items() if len(claim_ids) >= 5}
        chosen = eligible or groups
        if not chosen:
            return []
        best = min(chosen, key=lambda key: (len(chosen[key]), key))
        return sorted(chosen[best])

    def _earliest_claim(self, policy_id: str) -> str | None:
        claim_ids = [_text(row["id"]) for row in self.claims_by_policy.get(policy_id, [])]
        if not claim_ids:
            return None
        return min(claim_ids)

    def _customer(self, tenant_id: str, entity_id: str) -> dict[str, object] | None:
        customer = self.customers.get(entity_id)
        if customer is None or _text(customer["tenant_id"]) != tenant_id:
            return None
        return customer

    def _stated_phone(self, customer_id: str) -> tuple[str, str] | None:
        for row in self.interactions_by_customer.get(customer_id, []):
            match = _STATED_PHONE.search(_text(row["summary"]))
            if match is not None:
                return _text(row["id"]), match.group(1)
        return None


def _index(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {_text(row["id"]): row for row in rows}


def _group(rows: list[dict[str, object]], column: str) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(_text(row[column]), []).append(row)
    return grouped
