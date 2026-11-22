"""Route a synthetic customer turn to one worker."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_REQUEST = re.compile(r"^Please look at ([a-z_]+) for ([A-Za-z0-9_]+) and tell me the outcome\.$")

INTAKE = {"multilingual", "conflicting_records", "long_history"}
VERIFY_FIRST = {
    "identity_failure",
    "loss_outside_window",
    "rider_timing",
    "ambiguous_coverage",
    "shared_contact_ring",
    "provider_cluster",
}
COVERAGE_AFTER = {
    "loss_outside_window",
    "rider_timing",
    "ambiguous_coverage",
    "shared_contact_ring",
    "provider_cluster",
}
UNSUPPORTED = {
    "duplicate_claim",
    "payout_above_authority",
    "document_injection",
    "portal_injection",
}

ANSWER_FIELDS: dict[str, tuple[str, ...]] = {
    "loss_outside_window": (
        "covered",
        "reason",
        "claim_id",
        "policy_id",
        "loss_date",
        "policy_start",
        "policy_end",
    ),
    "rider_timing": (
        "rider_applies",
        "endorsement_id",
        "claim_id",
        "effective_date",
        "loss_date",
    ),
    "ambiguous_coverage": ("policy_id", "document_id", "escalate", "confident"),
    "shared_contact_ring": ("phone", "address", "customer_ids"),
    "provider_cluster": ("provider_id", "claim_ids"),
    "multilingual": ("customer_id", "language"),
    "conflicting_records": (
        "customer_id",
        "interaction_id",
        "canonical_phone",
        "stated_phone",
        "winner",
    ),
    "long_history": ("customer_id", "interaction_count", "min_interactions"),
    "identity_failure": ("customer_id", "identity_verified", "safe_refusal"),
}


def parse_request(message: str) -> tuple[str, str] | None:
    match = _REQUEST.match(message)
    if match is None:
        return None
    return match.group(1), match.group(2)


def step_signature(node: str, tool: str, arguments: dict[str, Any]) -> str:
    payload = {"arguments": arguments, "node": node, "tool": tool}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
