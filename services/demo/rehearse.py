"""The eight demo beats, run offline. This is the rehearsal, not a recording."""

from __future__ import annotations

from datetime import datetime, timedelta

from services.browser_agent.agent import update_note
from services.browser_agent.session import open_portal
from services.catalog.store import Catalog
from services.contracts.envelope import ScopedToken
from services.contracts.provider import (
    CompletionRequest,
    CompletionResponse,
    ScriptedProvider,
)
from services.demo.traces import MESSAGE, record_trace
from services.gateway.idempotency import MemoryIdempotency
from services.gateway.keys import request_hash
from services.gateway.pool import ProviderError, ProviderPool
from services.guardrails.stack import check_context, check_input
from services.legacy_portal.app import INJECTION
from services.mcp.dispatch import call_tool
from services.voice.pipeline import encode, hear


class _Down:
    def complete(self, request: CompletionRequest) -> CompletionResponse:
        raise ProviderError(503, retry_after=5)


def _catalog() -> Catalog:
    return Catalog(
        {
            "customers": [
                {
                    "id": "cus_000001",
                    "tenant_id": "ten_01",
                    "name": "Ada Example",
                    "dob": "1990-01-01",
                    "address": "1 Synthetic Street",
                    "phone": "+1-555-0101",
                    "email": "cus_000001@example.com",
                    "language": "en",
                    "risk_segment": "standard",
                    "identity_verified": True,
                }
            ],
            "policies": [
                {
                    "id": "pol_000001",
                    "tenant_id": "ten_01",
                    "customer_id": "cus_000001",
                    "type": "auto",
                    "status": "active",
                    "start_date": "2023-01-01",
                    "end_date": "2024-01-01",
                    "premium": 100000,
                    "coverage_language": "Covered perils are paid subject to the stated limit.",
                }
            ],
            "claims": [
                {
                    "id": "clm_000001",
                    "tenant_id": "ten_01",
                    "policy_id": "pol_000001",
                    "loss_date": "2024-01-02",
                    "type": "collision",
                    "amount": 50000,
                    "status": "submitted",
                    "adjuster_id": "adj_01",
                    "provider_id": None,
                    "portal_note": None,
                    "submission_key": "sub:clm_000001",
                },
                {
                    "id": "clm_000191",
                    "tenant_id": "ten_01",
                    "policy_id": "pol_000191",
                    "loss_date": "2023-05-01",
                    "type": "collision",
                    "amount": 800000,
                    "status": "submitted",
                    "adjuster_id": "adj_02",
                    "provider_id": None,
                    "portal_note": None,
                    "submission_key": "sub:clm_000191",
                },
            ],
            "payments": [
                {
                    "id": "pay_000001",
                    "tenant_id": "ten_01",
                    "claim_id": "clm_000191",
                    "amount": 800000,
                    "paid_on": "2024-07-01",
                    "method": "simulated_ach",
                    "idempotency_key": "payout:clm_000191",
                }
            ],
            "adjusters": [
                {
                    "id": "adj_02",
                    "tenant_id": "ten_01",
                    "name": "Synthetic Adjuster",
                    "authority_limit": 500000,
                }
            ],
        }
    )


def rehearse() -> dict[str, bool]:
    catalog = _catalog()
    voice = hear(encode("what is the status of clm_000001"), {"clm_000001": "open"})
    trace = record_trace(catalog)
    tools = [item.get("name") for item in trace["messages"] if item.get("role") == "tool"]
    token = ScopedToken(
        tenant_id="ten_01",
        task="payments",
        allowed_tools=["payments.propose_payout", "payments.execute_payout"],
        trace_id="rehearse",
    )
    proposed = call_tool(catalog, token, "payments.propose_payout", {"entity_id": "pay_000001"})
    refused = call_tool(
        catalog,
        token,
        "payments.execute_payout",
        {"claim_id": "clm_000191", "amount": 800000, "idempotency_key": "rehearse-pay"},
    )
    machine = MemoryIdempotency()
    now = datetime(2026, 1, 1)
    writes = {"n": 0}

    def effect() -> dict[str, int]:
        writes["n"] += 1
        return {"n": writes["n"]}

    body = {"amount": 1}
    digest = request_hash(body)
    for _ in range(20):
        machine.execute("ten_01", "retry-20", digest, now, timedelta(seconds=30), effect)
    crashed = MemoryIdempotency()
    crashed.crash_after_effect("ten_01", "crash", digest, now, timedelta(seconds=30), {"n": 1})
    crashed.execute("ten_01", "crash", digest, now, timedelta(seconds=30), effect)
    page = update_note(
        open_portal(),
        ScriptedProvider(),
        claim_id="clm_000001",
        tenant_id="ten_01",
        note="received",
        idempotency_key="rehearse-portal",
        layout="2",
    )
    pool = ProviderPool.from_providers([("down", _Down()), ("spare", ScriptedProvider(["{}"]))])
    pooled = pool.complete(
        CompletionRequest(
            model="scripted-fake",
            messages=[{"role": "user", "content": "{}"}],
            tool_allow_list=[],
            response_schema="answer",
            prompt_version="phase6",
            trace_id="rehearse-pool",
        ),
        now,
    )
    return {
        "voice": voice.events == ["fast", "slow"],
        "trace": "policy.get_policy" in tools and trace["outcome"]["covered"] is False,
        "approval": proposed.data["requires_approval"] is True
        and refused.error is not None
        and refused.error.code == "approval_required",
        "idempotency": writes["n"] == 1,
        "crash": crashed.rows[("ten_01", "crash")].response == {"n": 1} and writes["n"] == 1,
        "injection": check_context(INJECTION).flagged and check_input(INJECTION).blocked,
        "portal": page.success and len(page.evidence) == 2,
        "failover": pooled.provider == "spare" and "down:503" in pool.events,
        "message": MESSAGE in trace["message"],
    }
