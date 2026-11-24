"""Scripted portal steps. The model is only asked when a selector is missing."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from services.contracts.provider import (
    CompletionRequest,
    CompletionResponse,
    ModelProvider,
    json_object,
)
from services.guardrails.stack import check_context
from services.legacy_portal.app import portal_credentials

from .session import FlaskPage, Snapshot

ALLOWED_ACTIONS = frozenset({"fill", "read"})


@dataclass
class PortalResult:
    success: bool
    escalated: bool
    steps: int
    reason: str
    evidence: list[bytes] = field(default_factory=list)
    flagged: bool = False


def update_note(
    page: FlaskPage,
    provider: ModelProvider,
    *,
    claim_id: str,
    tenant_id: str,
    note: str,
    idempotency_key: str,
    layout: str,
    gap: bool = False,
    slow: bool = False,
    lie: bool = False,
) -> PortalResult:
    steps = 0
    user, password = portal_credentials()
    steps += 1
    page.fill("user", user)
    page.fill("password", password)
    signed = page.submit("/login")
    if signed.status != 200:
        return PortalResult(False, True, steps, "login_failed")
    query = f"/claims/{claim_id}/form?layout={layout}"
    if gap:
        query += "&gap=1"
    if slow:
        query += "&slow=1"
    steps += 1
    opened = page.goto(query)
    if opened.status == 503:
        steps += 1
        opened = page.goto(query)
    if opened.status != 200:
        return PortalResult(False, True, steps, "page_unavailable")
    before = page.screenshot(f"before {claim_id}")
    field = _field_name(opened)
    if field is None:
        steps += 1
        proposed = _propose(provider, opened)
        if proposed is None:
            return PortalResult(False, True, steps, "model_action_rejected", [before])
        field = proposed
    flagged = check_context(opened.text).flagged
    page.fill(field, note)
    page.fill("tenant_id", tenant_id)
    page.fill("idempotency_key", idempotency_key)
    steps += 1
    pending = page.submit(f"/claims/{claim_id}/confirm")
    if pending.fields.get("pending") != note:
        return PortalResult(False, True, steps, "confirm_mismatch", [before])
    steps += 1
    saved_path = f"/claims/{claim_id}/save" + ("?lie=1" if lie else "")
    saved = page.submit(saved_path)
    after = page.screenshot(f"after {claim_id}")
    verified = saved.fields.get("saved") == note
    return PortalResult(
        verified,
        not verified,
        steps,
        "verified" if verified else "verify_failed",
        [before, after],
        flagged=flagged,
    )


def _field_name(snapshot: Snapshot) -> str | None:
    if "note" in snapshot.fields:
        return "note"
    if "adjuster_note" in snapshot.fields:
        return None
    return None


def _propose(provider: ModelProvider, snapshot: Snapshot) -> str | None:
    response = provider.complete(
        CompletionRequest(
            model="scripted-fake",
            messages=[{"role": "user", "content": snapshot.text}],
            tool_allow_list=["fill", "read"],
            response_schema="browser_action",
            prompt_version="phase5",
            trace_id="trace-browser",
        )
    )
    action = _action(response)
    if action is None or action.get("action") not in ALLOWED_ACTIONS:
        return None
    name = action.get("name")
    if action.get("action") == "fill" and name == "adjuster_note":
        return "adjuster_note"
    return None


def _action(response: CompletionResponse) -> dict[str, object] | None:
    parsed = json_object(response.content)
    if parsed is None:
        try:
            loaded = json.loads(response.content)
        except json.JSONDecodeError:
            return None
        parsed = loaded if isinstance(loaded, dict) else None
    return parsed
