"""Deterministic idempotency keys for agent-initiated actions."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _normalise(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, dict):
        return {str(key): _normalise(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_normalise(item) for item in value]
    return value


def derive_key(tenant_id: str, claim_id: str, action: str, parameters: dict[str, Any]) -> str:
    payload = {
        "action": action.strip().lower(),
        "claim_id": claim_id.strip(),
        "parameters": _normalise(parameters),
        "tenant_id": tenant_id.strip(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def request_hash(body: dict[str, Any]) -> str:
    encoded = json.dumps(_normalise(body), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
