"""Phase 2 failure cases. No sockets and no model calls."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from langgraph.types import Command

from db.tables import idempotency_keys, payments
from services.catalog.store import Catalog
from services.contracts.envelope import ScopedToken
from services.contracts.provider import (
    CompletionRequest,
    ModelOutputError,
    ScriptedProvider,
    complete_validated,
)
from services.contracts.state import AgentState
from services.gateway.approvals import ApprovalBook, create_app
from services.gateway.budget import BudgetCaps, BudgetState, charge, decide
from services.gateway.cache import SemanticCache
from services.gateway.fake import ChaosProvider, retry_call
from services.gateway.idempotency import RECLAIM_SQL, MemoryIdempotency
from services.gateway.keys import derive_key, request_hash
from services.gateway.pool import ProviderError, ProviderPool
from services.gateway.ratelimit import FailingBucket, MemoryBucket, RateLimiter, RedisBucket
from services.legacy_portal.app import INJECTION, PortalStore
from services.legacy_portal.app import create_app as portal_app
from services.mcp.dispatch import accept_tool_result, call_tool
from services.mcp.payments_server.tools import adjuster_token, ledger_for
from services.orchestrator.graph import build_graph, freeze_state, initial_state
from services.orchestrator.loops import LoopLimits, loop_reason
from services.paths import repo_root

NOW = datetime(2026, 1, 1)
MESSAGE = "Please look at loss_outside_window for clm_000001 and tell me the outcome."
TOKEN = "Bearer " + adjuster_token()


def _request() -> CompletionRequest:
    return CompletionRequest(
        model="scripted-fake",
        messages=[{"role": "user", "content": "{}"}],
        tool_allow_list=["payments.execute_payout"],
        response_schema="answer",
        prompt_version="phase2",
        trace_id="trace-phase2",
    )


def _state() -> AgentState:
    return {
        "messages": [{"role": "user", "content": "{}"}],
        "verified_identity": None,
        "claim_draft": {},
        "coverage_decision": {},
        "proposed_payout": None,
        "approval": None,
        "step_count": 0,
        "signatures": [],
        "budget": {"remaining_tokens": 8000, "shadow_cost": "0"},
        "trace_id": "trace-phase2",
        "escalation": None,
        "retry_count": 0,
    }


def _payout_catalog() -> Catalog:
    return Catalog(
        {
            "customers": [],
            "policies": [],
            "claims": [
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
                }
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


def _token() -> ScopedToken:
    return ScopedToken(
        tenant_id="ten_01",
        task="payments",
        allowed_tools=["payments.propose_payout", "payments.execute_payout"],
        trace_id="trace-pay",
    )


def _caps() -> BudgetCaps:
    return BudgetCaps(
        session_tokens=10,
        tenant_shadow_micros=50,
        prices_per_token_micros={"cheap": 60, "strong": 100},
    )


def test_schema_and_reclaim_sql_are_unchanged() -> None:
    assert [column.name for column in idempotency_keys.primary_key.columns] == [
        "tenant_id",
        "key",
    ]
    names = {constraint.name for constraint in payments.constraints}
    assert "payments_tenant_idempotency_key" in names
    assert "payments_claim_id_key" in names
    assert "lock_expires_at <= %(now)s" in RECLAIM_SQL
    assert "state = 'in_progress'" in RECLAIM_SQL


def test_replay_conflict_crash_reclaim_and_final() -> None:
    machine = MemoryIdempotency()
    ledger = {"rows": 0}

    def effect() -> dict[str, int]:
        ledger["rows"] += 1
        return {"payment_id": "pay_new_000001"}

    body = request_hash({"amount": 800000})
    first = machine.execute("ten_01", "k1", body, NOW, timedelta(seconds=30), effect)
    second = machine.execute("ten_01", "k1", body, NOW, timedelta(seconds=30), effect)
    assert first.kind == "proceed" and second.kind == "replay"
    assert ledger["rows"] == 1
    other = request_hash({"amount": 1})
    conflict = machine.execute("ten_01", "k1", other, NOW, timedelta(seconds=30), effect)
    assert conflict.kind == "conflict" and ledger["rows"] == 1

    crashed = MemoryIdempotency()
    crashed.crash_after_effect(
        "ten_01", "k2", body, NOW, timedelta(seconds=30), {"payment_id": "pay_new_000001"}
    )
    reconciled = crashed.execute("ten_01", "k2", body, NOW, timedelta(seconds=30), effect)
    assert reconciled.kind == "replay" and ledger["rows"] == 1

    stale = MemoryIdempotency()
    stale.hold("ten_01", "k3", body, NOW, timedelta(seconds=1))
    later = NOW + timedelta(seconds=5)
    reclaimed = stale.execute("ten_01", "k3", body, later, timedelta(seconds=30), effect)
    again = stale.execute("ten_01", "k3", body, later, timedelta(seconds=30), effect)
    assert reclaimed.reclaimed and again.kind == "replay"
    assert stale.rows[("ten_01", "k3")].reclaim_count == 1
    assert ledger["rows"] == 2

    final = MemoryIdempotency()
    final.hold("ten_01", "k4", body, NOW, timedelta(seconds=30))
    final.fail("ten_01", "k4", "failed_final", {"error": "rejected"})
    assert final.execute("ten_01", "k4", body, NOW, timedelta(seconds=30), effect).kind == "final"
    assert ledger["rows"] == 2


def test_concurrent_payout_and_portal_write_once() -> None:
    catalog = _payout_catalog()
    key = derive_key("ten_01", "clm_000191", "payments.execute_payout", {"amount": 100})

    def once(_: int) -> str:
        envelope = call_tool(
            catalog,
            _token(),
            "payments.execute_payout",
            {
                "claim_id": "clm_000191",
                "amount": 100,
                "idempotency_key": key,
                "approval_token": adjuster_token(),
            },
        )
        assert envelope.status == "ok"
        return str(envelope.data["payment"]["id"])

    with ThreadPoolExecutor(max_workers=50) as pool:
        ids = list(pool.map(once, range(1000)))
    ledger = ledger_for(catalog)
    assert ledger.writes == 1
    assert len(ledger.rows) == 1
    assert len(set(ids)) == 1

    store = PortalStore()

    def note(_: int) -> str:
        outcome = store.machine.execute(
            "ten_01",
            "portal-key",
            request_hash({"claim_id": "clm_000191", "note": "received"}),
            NOW,
            timedelta(seconds=30),
            lambda: store.write("ten_01", "clm_000191", "received", "portal-key"),
        )
        assert outcome.response is not None
        return str(outcome.response["note"])

    with ThreadPoolExecutor(max_workers=50) as pool:
        notes = list(pool.map(note, range(1000)))
    assert store.writes == 1
    assert len(set(notes)) == 1


def test_portal_layouts_conflict_and_crash() -> None:
    store = PortalStore()
    client = portal_app(store).test_client()
    pages = [
        client.get("/claims/clm_000191?layout=" + layout).get_data(as_text=True)
        for layout in ("1", "2", "3")
    ]
    assert all('name="note"' in page and INJECTION in page for page in pages)
    form = {"tenant_id": "ten_01", "note": "received", "idempotency_key": "portal-1"}
    first = client.post("/claims/clm_000191/note", data=form)
    second = client.post("/claims/clm_000191/note", data=form)
    assert first.status_code == 200 and second.json["replayed"] is True
    assert store.writes == 1
    changed = client.post("/claims/clm_000191/note", data={**form, "note": "other"})
    assert changed.status_code == 409 and store.writes == 1
    crashed = PortalStore()
    body = {"claim_id": "clm_000191", "note": "received"}
    recorded = crashed.write("ten_01", "clm_000191", "received", "portal-2")
    crashed.machine.crash_after_effect(
        "ten_01", "portal-2", request_hash(body), NOW, timedelta(seconds=30), recorded
    )
    replay = (
        portal_app(crashed)
        .test_client()
        .post(
            "/claims/clm_000191/note",
            data={"tenant_id": "ten_01", "note": "received", "idempotency_key": "portal-2"},
        )
    )
    assert replay.status_code == 200 and crashed.writes == 1


def test_derived_keys_and_loop_breaker() -> None:
    params = {"amount": 100, "note": "  received   today "}
    first = derive_key("ten_01", "clm_000191", " Payments.Execute_Payout ", params)
    second = derive_key("ten_01", "clm_000191", "payments.execute_payout", params)
    assert first == second
    assert first != derive_key("ten_01", "clm_000191", "payments.execute_payout", {"amount": 101})
    tight = LoopLimits(
        max_steps=2, max_tool_calls=1, max_identical_consecutive=2, signature_repeats=9
    )
    assert loop_reason(3, ["a"], 0, limits=tight) == "loop_steps"
    assert loop_reason(1, ["a"], 2, limits=tight) == "loop_tools"
    assert loop_reason(1, ["a", "a"], 0, limits=tight) == "loop_consecutive"
    repeated = LoopLimits(max_identical_consecutive=9, signature_repeats=3, signature_window=10)
    assert loop_reason(1, ["a", "b", "a", "a"], 0, limits=repeated) == "loop_signature"
    quiet = LoopLimits(max_identical_consecutive=9, signature_repeats=9, no_progress_steps=3)
    assert loop_reason(1, ["a"], 0, limits=quiet, fact_hashes=["h", "h", "h"]) == "loop_no_progress"


def test_budgets_degrade_and_cache_stays_inside_a_tenant() -> None:
    caps = _caps()
    low_tokens = BudgetState(remaining_tokens=2, shadow_micros=0, tier="strong")
    assert decide(low_tokens, 8, caps, cache_hit=False) == "cheap"
    low_tokens.tier = "cheap"
    assert decide(low_tokens, 8, caps, cache_hit=False) == "handoff"
    rich = BudgetState(remaining_tokens=100, shadow_micros=0, tier="strong")
    assert decide(rich, 1, caps, cache_hit=True) == "cache"
    assert decide(rich, 1, caps, cache_hit=False) == "cheap"
    rich.tier = "cheap"
    assert decide(rich, 1, caps, cache_hit=False) == "handoff"
    cache = SemanticCache()
    assert cache.put(
        tenant_id="ten_01",
        language="en",
        policy_version="v1",
        model_tier="cheap",
        question="What is the deductible?",
        answer="500",
        now=NOW,
    )
    hit = cache.get(
        tenant_id="ten_01",
        language="en",
        policy_version="v1",
        model_tier="cheap",
        question="What is the deductible?",
        now=NOW,
    )
    other = cache.get(
        tenant_id="ten_02",
        language="en",
        policy_version="v1",
        model_tier="cheap",
        question="What is the deductible?",
        now=NOW,
    )
    private = cache.get(
        tenant_id="ten_01",
        language="en",
        policy_version="v1",
        model_tier="cheap",
        question="What about clm_000191?",
        now=NOW,
    )
    assert hit == "500" and other is None and private is None
    assert cache.purge_version("v1") == 1


def test_rate_limits_retry_after_and_fail_closed() -> None:
    user = MemoryBucket(10, timedelta(minutes=1))
    tenant = MemoryBucket(1, timedelta(minutes=1))
    limiter = RateLimiter(user, tenant)
    assert limiter.allow("u1", "t1", NOW) == (True, 0)
    assert limiter.allow("u2", "t2", NOW)[0] is True
    denied, wait = limiter.allow("u3", "t1", NOW)
    assert denied is False and wait >= 1
    lua = (repo_root() / "services" / "gateway" / "token_bucket.lua").read_text(encoding="utf-8")
    assert "KEYS[1]" in lua and "ARGV[1]" in lua

    class FakeRedis:
        def eval(self, script: str, count: int, *args: object) -> list[int]:
            assert "KEYS" in script and count == 1
            return [0, 2000]

    bucket = RedisBucket(FakeRedis(), lua, 60, 60_000)
    allowed, retry_after = bucket.allow("user:u1", NOW)
    assert allowed is False and retry_after >= 1
    closed = RateLimiter(FailingBucket(), FailingBucket())
    assert closed.allow("u1", "t1", NOW) == (False, 60)


def test_provider_failover_timeout_and_malformed_output() -> None:
    request = _request()
    pool = ProviderPool.from_providers(
        [("primary", ChaosProvider(["429"])), ("backup", ScriptedProvider(['{"ok": true}']))]
    )
    served = pool.complete(request, NOW)
    assert served.provider == "backup" and "primary:429" in pool.events
    down = ProviderPool.from_providers(
        [("primary", ChaosProvider(["500"])), ("backup", ChaosProvider(["429"]))]
    )
    handoff = down.complete(request, NOW)
    assert handoff.handoff and handoff.response is None and handoff.reason == "all_providers_down"

    def slow() -> dict[str, str]:
        return {"payment_id": "pay_new_000001"}

    machine = MemoryIdempotency()
    body = request_hash({"amount": 1})
    machine.execute("ten_01", "slow", body, NOW, timedelta(seconds=30), slow)
    machine.execute("ten_01", "slow", body, NOW, timedelta(seconds=30), slow)
    assert machine.rows[("ten_01", "slow")].state == "succeeded"

    def timed_out() -> str:
        raise ProviderError(408, retry_after=1)

    assert retry_call(timed_out, attempts=2) == "escalate:408"
    bad = ChaosProvider(["bad_json", "bad_json"])
    try:
        complete_validated(bad, request, _state())
    except ModelOutputError:
        pass
    else:
        raise AssertionError("invalid JSON was accepted")
    malformed = accept_tool_result({"nope": True}, "trace-phase2")
    assert malformed.error is not None and malformed.error.code == "malformed_result"
    false_success = ChaosProvider(["false_success"]).complete(request)
    assert false_success.tool_calls[0].arguments == {}
    rejected = call_tool(_payout_catalog(), _token(), "payments.execute_payout", {})
    assert rejected.error is not None and rejected.error.code == "validation_error"
    injected = ChaosProvider(["injection"]).complete(request)
    assert injected.content == INJECTION


def test_approval_page_and_interrupt_resume_once() -> None:
    book = ApprovalBook()
    catalog = _payout_catalog()
    paid = call_tool(
        catalog,
        _token(),
        "payments.execute_payout",
        {
            "claim_id": "clm_000191",
            "amount": 100,
            "idempotency_key": "approved-once",
            "approval_token": adjuster_token(),
        },
    )
    assert paid.status == "ok"
    graph = build_graph(catalog, ScriptedProvider(), interrupt_before=["finish"])
    config = {"configurable": {"thread_id": "approval-1"}}
    paused = freeze_state(graph.invoke(initial_state(MESSAGE, "approval-1"), config))
    assert paused["approval"] is None
    approval_id = book.open(paused, "Payout above authority")
    client = TestClient(create_app(book))
    assert client.get("/v1/approvals").status_code == 401
    refused = client.post(f"/v1/approvals/{approval_id}/decision", json={"decision": "approve"})
    assert refused.status_code == 401
    page = client.get("/v1/approvals", headers={"Authorization": TOKEN})
    assert page.status_code == 200 and approval_id in page.text
    approved = client.post(
        f"/v1/approvals/{approval_id}/decision",
        headers={"Authorization": TOKEN},
        json={"decision": "approve", "reason": "within the edited amount"},
    )
    assert approved.status_code == 200
    assert approved.json()["approval"]["status"] == "approve"
    for decision, edits in (("reject", None), ("edit", {"amount": 100})):
        item = book.open(paused, decision)
        response = client.post(
            f"/v1/approvals/{item}/decision",
            headers={"Authorization": TOKEN},
            json={"decision": decision, "edits": edits, "reason": decision},
        )
        assert response.status_code == 200
        assert response.json()["approval"]["status"] == decision
    resumed = freeze_state(
        graph.invoke(
            Command(resume="approve", update={"approval": approved.json()["approval"]}),
            config,
        )
    )
    assert resumed["approval"]["status"] == "approve"
    replay = call_tool(
        catalog,
        _token(),
        "payments.execute_payout",
        {
            "claim_id": "clm_000191",
            "amount": 100,
            "idempotency_key": "approved-once",
            "approval_token": adjuster_token(),
        },
    )
    assert replay.idempotency is not None and replay.idempotency.replayed is True
    assert ledger_for(catalog).writes == 1


def test_missing_approval_token_does_not_pay() -> None:
    catalog = _payout_catalog()
    refused = call_tool(
        catalog,
        _token(),
        "payments.execute_payout",
        {"claim_id": "clm_000191", "amount": 800000, "idempotency_key": "needs-token"},
    )
    assert refused.error is not None and refused.error.code == "approval_required"
    assert ledger_for(catalog).writes == 0
    proposed = call_tool(catalog, _token(), "payments.propose_payout", {"entity_id": "pay_000001"})
    assert proposed.data["requires_approval"] is True


def test_injected_loops_are_caught_before_the_step_cap() -> None:
    limits = LoopLimits()
    patterns = ("consecutive", "signature", "tools", "no_progress")
    caught = 0
    for index in range(20):
        kind = patterns[index % len(patterns)]
        signatures: list[str] = []
        facts: list[str] = []
        reason = None
        steps = 0
        for step in range(1, limits.max_steps + 3):
            steps = step
            if kind == "consecutive":
                signatures.append("same")
            elif kind == "signature":
                signatures.append("a" if step % 2 else "b")
            elif kind == "tools":
                signatures.append(f"tool-{step}")
            else:
                signatures.append(f"step-{step}")
                facts.append("same-fact")
            tool_calls = step if kind == "tools" else 0
            reason = loop_reason(
                step,
                signatures,
                tool_calls,
                limits=limits,
                fact_hashes=facts or None,
            )
            if reason is not None:
                break
        if reason is not None and steps <= limits.max_steps:
            caught += 1
    assert caught / 20 >= 0.95


def test_twenty_sessions_stay_inside_the_token_budget() -> None:
    caps = BudgetCaps(
        session_tokens=100,
        tenant_shadow_micros=1_000_000,
        prices_per_token_micros={"cheap": 1},
    )
    over = 0
    for _ in range(20):
        state = BudgetState(remaining_tokens=caps.session_tokens, shadow_micros=0, tier="cheap")
        spent = 0
        for _step in range(10):
            action = decide(state, 30, caps, cache_hit=False)
            if action != "allow":
                break
            charge(state, 30, caps)
            spent += 30
        if spent > caps.session_tokens or state.remaining_tokens < 0:
            over += 1
    assert over == 0
