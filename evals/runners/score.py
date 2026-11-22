"""Outcome and trajectory scores."""

from __future__ import annotations

import json
from typing import Any

from services.orchestrator.permissions import ALLOW_LISTS

CLAIM_READING = {"policy.get_policy", "policy.get_endorsements", "graph.provider_cluster"}
WRITE_TOOLS = {"crm.add_note", "crm.update_contact"}
PHASE1_TOOLS = {tool for tools in ALLOW_LISTS.values() for tool in tools}


def tool_calls_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    messages = state.get("messages")
    if not isinstance(messages, list):
        return calls
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        arguments = json.loads(str(message["arguments"]))
        if isinstance(arguments, dict):
            calls.append({"tool": str(message["name"]), "arguments": arguments})
    return calls


def assistant_payload(state: dict[str, Any]) -> dict[str, Any] | None:
    messages = state.get("messages")
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "assistant":
            parsed = json.loads(str(message["content"]))
            if isinstance(parsed, dict):
                return parsed
    return None


def outcome_score(actual: dict[str, Any] | None, expected: dict[str, Any]) -> float:
    if actual != expected:
        return 0.0
    return 1.0


def trajectory_score(
    calls: list[dict[str, Any]],
    expected: list[dict[str, Any]],
    *,
    allow: set[str] | None = None,
    margin: int = 3,
) -> float:
    permitted = PHASE1_TOOLS if allow is None else allow
    forbidden = any(str(call["tool"]) not in permitted for call in calls)
    missing_key = any(
        str(call["tool"]) in WRITE_TOOLS and not str(call["arguments"].get("idempotency_key", ""))
        for call in calls
    )
    if forbidden or missing_key:
        return 0.0
    required = all(_has_expected(calls, item) for item in expected)
    ordered = _identity_before_claim(calls)
    efficient = len(calls) <= len(expected) + margin
    passed = sum((required, True, True, ordered, efficient))
    return passed / 5


def _has_expected(calls: list[dict[str, Any]], expected: dict[str, Any]) -> bool:
    arguments = expected["arguments"]
    if not isinstance(arguments, dict):
        return False
    return any(
        call["tool"] == expected["tool"]
        and call["arguments"].get("entity_id") == arguments.get("entity_id")
        for call in calls
    )


def _identity_before_claim(calls: list[dict[str, Any]]) -> bool:
    verify_at = next(
        (index for index, call in enumerate(calls) if call["tool"] == "crm.verify_identity"),
        None,
    )
    claim_at = next(
        (index for index, call in enumerate(calls) if call["tool"] in CLAIM_READING),
        None,
    )
    if verify_at is None or claim_at is None:
        return True
    return verify_at < claim_at
