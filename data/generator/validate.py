"""Referential integrity, planted outcomes, and synthetic-data hygiene."""

from __future__ import annotations

import re
from datetime import date, timedelta

from generator.coerce import as_bool, as_dict, as_int, as_str, as_str_list
from generator.config import GeneratorConfig
from generator.constants import (
    AMBIGUOUS_COVERAGE,
    EMAIL_DOMAINS,
)
from generator.dataset import Dataset

_PHONE = re.compile(r"^\+1-555-01[0-9]{2}$")
_PROBLEM_LIMIT = 40


def all_problems(dataset: Dataset, config: GeneratorConfig) -> list[str]:
    problems: list[str] = []
    problems.extend(integrity_problems(dataset, config))
    problems.extend(planted_problems(dataset, config))
    problems.extend(hygiene_problems(dataset, config))
    return problems


def integrity_problems(dataset: Dataset, config: GeneratorConfig) -> list[str]:
    problems: list[str] = []
    expected = {
        "tenants": config.volumes.tenants,
        "customers": config.volumes.customers,
        "policies": config.volumes.policies,
        "coverages": config.volumes.coverages,
        "endorsements": config.volumes.endorsements,
        "providers": config.volumes.providers,
        "adjusters": config.volumes.adjusters,
        "claims": config.volumes.claims,
        "payments": config.volumes.payments,
        "interactions": config.volumes.interactions,
        "policy_documents": config.volumes.policy_documents,
        "faq_pages": config.volumes.faq_pages,
        "idempotency_keys": config.volumes.payments,
        "documents": config.volumes.policy_documents,
        "golden": 30,
    }
    actual = dataset.manifest()["counts"]
    if not isinstance(actual, dict):
        return ["manifest counts are not a mapping"]
    for name, count in expected.items():
        if actual.get(name) != count:
            _push(problems, f"{name} count is {actual.get(name)}, expected {count}")

    tenants = _index(dataset.tenants)
    customers = _index(dataset.customers)
    policies = _index(dataset.policies)
    adjusters = _index(dataset.adjusters)
    providers = _index(dataset.providers)
    claims = _index(dataset.claims)
    _require_tenant(problems, dataset.customers, tenants, "customers")
    _require_parent(
        problems,
        dataset.policies,
        customers,
        "policies",
        "customer_id",
        "customers",
    )
    _require_parent(problems, dataset.coverages, policies, "coverages", "policy_id", "policies")
    _require_parent(
        problems,
        dataset.endorsements,
        policies,
        "endorsements",
        "policy_id",
        "policies",
    )
    _require_parent(problems, dataset.claims, policies, "claims", "policy_id", "policies")
    _require_parent(problems, dataset.claims, adjusters, "claims", "adjuster_id", "adjusters")
    _require_parent(
        problems,
        [row for row in dataset.claims if row["provider_id"] is not None],
        providers,
        "claims",
        "provider_id",
        "providers",
    )
    _require_parent(problems, dataset.payments, claims, "payments", "claim_id", "claims")
    _require_parent(
        problems,
        dataset.interactions,
        customers,
        "interactions",
        "customer_id",
        "customers",
    )
    _require_parent(
        problems,
        dataset.policy_documents,
        policies,
        "policy_documents",
        "policy_id",
        "policies",
    )
    _require_tenant(problems, dataset.providers, tenants, "providers")
    _require_tenant(problems, dataset.adjusters, tenants, "adjusters")
    _require_tenant(problems, dataset.faq_pages, tenants, "faq_pages")
    _require_tenant(problems, dataset.planted_scenarios, tenants, "planted_scenarios")
    _require_tenant(problems, dataset.idempotency_keys, tenants, "idempotency_keys")

    payment_keys = [
        (as_str(row["tenant_id"]), as_str(row["idempotency_key"])) for row in dataset.payments
    ]
    if len(payment_keys) != len(set(payment_keys)):
        _push(problems, "duplicate payment idempotency key")
    submission_keys = [
        (as_str(row["tenant_id"]), as_str(row["submission_key"])) for row in dataset.claims
    ]
    if len(submission_keys) != len(set(submission_keys)):
        _push(problems, "duplicate claim submission key")
    idempotency = {
        (as_str(row["tenant_id"]), as_str(row["key"])): row for row in dataset.idempotency_keys
    }
    if len(idempotency) != len(dataset.idempotency_keys):
        _push(problems, "duplicate idempotency primary key")
    for payment in dataset.payments:
        key = (as_str(payment["tenant_id"]), as_str(payment["idempotency_key"]))
        row = idempotency.get(key)
        if row is None or as_str(row["state"]) != "succeeded":
            _push(problems, f"payment {as_str(payment['id'])} has no succeeded idempotency row")
    return problems


def planted_problems(dataset: Dataset, config: GeneratorConfig) -> list[str]:
    problems: list[str] = []
    counts: dict[str, int] = {}
    for row in dataset.planted_scenarios:
        scenario_type = as_str(row["scenario_type"])
        counts[scenario_type] = counts.get(scenario_type, 0) + 1
    for name, expected_count in config.planted.model_dump().items():
        if counts.get(name) != expected_count:
            _push(problems, f"{name} planted {counts.get(name)}, expected {expected_count}")

    claims = _index(dataset.claims)
    policies = _index(dataset.policies)
    customers = _index(dataset.customers)
    endorsements = _index(dataset.endorsements)
    payments = _index(dataset.payments)
    interactions = _index(dataset.interactions)
    documents = _index(dataset.policy_documents)
    adjusters = _index(dataset.adjusters)
    artifacts = {item.document_id: item for item in dataset.documents}
    payments_by_claim = {as_str(row["claim_id"]): row for row in dataset.payments}
    submission_counts: dict[str, int] = {}
    for claim in dataset.claims:
        key = as_str(claim["submission_key"])
        submission_counts[key] = submission_counts.get(key, 0) + 1
    interaction_counts: dict[str, int] = {}
    for interaction in dataset.interactions:
        customer_id = as_str(interaction["customer_id"])
        interaction_counts[customer_id] = interaction_counts.get(customer_id, 0) + 1

    for row in dataset.planted_scenarios:
        scenario_type = as_str(row["scenario_type"])
        expected = as_dict(row["expected"])
        if scenario_type == "loss_outside_window":
            claim = claims[as_str(expected["claim_id"])]
            policy = policies[as_str(claim["policy_id"])]
            loss = date.fromisoformat(as_str(claim["loss_date"]))
            start = date.fromisoformat(as_str(policy["start_date"]))
            end = date.fromisoformat(as_str(policy["end_date"]))
            outside = loss == end + timedelta(days=1) or loss == start - timedelta(days=1)
            if not outside or expected["covered"] is not False:
                _push(problems, f"{as_str(claim['id'])} is not one day outside the term")
            if as_str(claim["id"]) in payments_by_claim:
                _push(problems, f"{as_str(claim['id'])} outside the term was paid")
        elif scenario_type == "rider_timing":
            endorsement = endorsements[as_str(expected["endorsement_id"])]
            claim = claims[as_str(expected["claim_id"])]
            applies = date.fromisoformat(
                as_str(endorsement["effective_date"])
            ) <= date.fromisoformat(as_str(claim["loss_date"]))
            if applies != as_bool(expected["rider_applies"]):
                _push(problems, f"rider {as_str(endorsement['id'])} outcome drifted")
        elif scenario_type == "duplicate_claim":
            claim = claims[as_str(expected["claim_id"])]
            key = as_str(claim["submission_key"])
            if submission_counts[key] != 1 or as_int(expected["rejected_amount"]) == as_int(
                claim["amount"]
            ):
                _push(problems, f"duplicate claim {key} did not keep a single row")
        elif scenario_type == "shared_contact_ring":
            member_ids = as_str_list(expected["customer_ids"])
            if len(member_ids) != config.ring_size:
                _push(problems, "shared contact ring has the wrong size")
            phones = {as_str(customers[member_id]["phone"]) for member_id in member_ids}
            addresses = {as_str(customers[member_id]["address"]) for member_id in member_ids}
            if phones != {as_str(expected["phone"])} or addresses != {as_str(expected["address"])}:
                _push(problems, "shared contact ring does not share phone and address")
        elif scenario_type == "provider_cluster":
            claim_ids = as_str_list(expected["claim_ids"])
            provider_id = as_str(expected["provider_id"])
            if len(claim_ids) != config.cluster_size:
                _push(problems, "provider cluster has the wrong size")
            if any(
                as_str(claims[claim_id]["provider_id"]) != provider_id for claim_id in claim_ids
            ):
                _push(problems, f"provider cluster {provider_id} is not shared")
        elif scenario_type == "payout_above_authority":
            payment = payments[as_str(expected["payment_id"])]
            adjuster = adjusters[as_str(expected["adjuster_id"])]
            if as_int(payment["amount"]) <= as_int(adjuster["authority_limit"]):
                _push(problems, f"payment {as_str(payment['id'])} is within authority")
            if expected["requires_approval"] is not True:
                _push(problems, f"payment {as_str(payment['id'])} does not require approval")
        elif scenario_type == "conflicting_records":
            customer = customers[as_str(expected["customer_id"])]
            interaction = interactions[as_str(expected["interaction_id"])]
            stated = as_str(expected["stated_phone"])
            if as_str(customer["phone"]) != as_str(expected["canonical_phone"]):
                _push(problems, "conflict canonical phone drifted")
            if stated == as_str(customer["phone"]) or stated not in as_str(interaction["summary"]):
                _push(problems, "conflict does not disagree with the CRM phone")
            if expected["winner"] != "crm":
                _push(problems, "conflict winner is not the CRM")
        elif scenario_type == "identity_failure":
            customer = customers[as_str(expected["customer_id"])]
            if customer["identity_verified"] is not False or expected["safe_refusal"] is not True:
                _push(problems, f"identity failure {as_str(customer['id'])} is verified")
        elif scenario_type == "document_injection":
            document = documents[as_str(expected["document_id"])]
            marker = as_str(expected["marker"])
            artifact = artifacts[as_str(document["id"])]
            if document["injection"] != marker or marker not in artifact.text:
                _push(problems, f"document {as_str(document['id'])} lost its injection")
            if marker.encode() not in artifact.pdf_bytes:
                _push(problems, f"document {as_str(document['id'])} PDF lost its injection")
        elif scenario_type == "portal_injection":
            claim = claims[as_str(expected["claim_id"])]
            if claim["portal_note"] != as_str(expected["marker"]):
                _push(problems, f"claim {as_str(claim['id'])} lost its portal injection")
        elif scenario_type == "ambiguous_coverage":
            policy = policies[as_str(expected["policy_id"])]
            artifact = artifacts[as_str(expected["document_id"])]
            if policy["coverage_language"] != AMBIGUOUS_COVERAGE:
                _push(problems, f"policy {as_str(policy['id'])} is not ambiguous")
            if (
                AMBIGUOUS_COVERAGE not in artifact.text
                or expected["escalate"] is not True
                or expected["confident"] is not False
            ):
                _push(problems, f"policy {as_str(policy['id'])} ambiguity outcome drifted")
        elif scenario_type == "multilingual":
            customer = customers[as_str(expected["customer_id"])]
            if (
                as_str(customer["language"]) != as_str(expected["language"])
                or as_str(customer["language"]) == "en"
            ):
                _push(problems, f"customer {as_str(customer['id'])} language drifted")
        elif scenario_type == "long_history":
            customer_id = as_str(expected["customer_id"])
            count = interaction_counts.get(customer_id, 0)
            if count != as_int(expected["interaction_count"]) or count < as_int(
                expected["min_interactions"]
            ):
                _push(problems, f"customer {customer_id} history is shorter than planted")
        else:
            _push(problems, f"unknown scenario type {scenario_type}")
        if len(problems) >= _PROBLEM_LIMIT:
            return problems
    return problems


def hygiene_problems(dataset: Dataset, config: GeneratorConfig) -> list[str]:
    problems: list[str] = []
    allowed_domains = set(EMAIL_DOMAINS)
    for customer in dataset.customers:
        phone = as_str(customer["phone"])
        email = as_str(customer["email"])
        if _PHONE.fullmatch(phone) is None:
            _push(problems, f"{as_str(customer['id'])} phone {phone} is outside 555-01xx")
        domain = email.rsplit("@", 1)[-1]
        if domain not in allowed_domains:
            _push(problems, f"{as_str(customer['id'])} email domain {domain} is not reserved")
        if len(problems) >= _PROBLEM_LIMIT:
            return problems
    watermark = config.watermark.encode()
    for artifact in dataset.documents:
        if config.watermark not in artifact.text or watermark not in artifact.pdf_bytes:
            _push(problems, f"{artifact.document_id} is missing the synthetic watermark")
    return problems


def _index(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {as_str(row["id"]): row for row in rows}


def _push(problems: list[str], message: str) -> None:
    if len(problems) < _PROBLEM_LIMIT:
        problems.append(message)


def _require_tenant(
    problems: list[str],
    rows: list[dict[str, object]],
    tenants: dict[str, dict[str, object]],
    label: str,
) -> None:
    for row in rows:
        if as_str(row["tenant_id"]) not in tenants:
            _push(problems, f"{label} {_row_label(row)} has an unknown tenant")
            return


def _row_label(row: dict[str, object]) -> str:
    if "id" in row:
        return as_str(row["id"])
    if "key" in row:
        return as_str(row["key"])
    return "row"


def _require_parent(
    problems: list[str],
    rows: list[dict[str, object]],
    parents: dict[str, dict[str, object]],
    label: str,
    foreign_key: str,
    parent_label: str,
) -> None:
    for row in rows:
        parent = parents.get(as_str(row[foreign_key]))
        row_id = as_str(row["id"]) if "id" in row else as_str(row[foreign_key])
        if parent is None:
            _push(problems, f"{label} {row_id} missing {parent_label}")
            return
        if as_str(parent["tenant_id"]) != as_str(row["tenant_id"]):
            _push(problems, f"{label} {row_id} tenant does not match {parent_label}")
            return
