"""Supervisor, intake, verification, and coverage."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from services.catalog.store import Catalog
from services.contracts.envelope import ScopedToken, ToolEnvelope
from services.contracts.provider import (
    CompletionRequest,
    ModelOutputError,
    ModelProvider,
    complete_validated,
)
from services.contracts.state import AgentState
from services.mcp.dispatch import call_tool
from services.orchestrator.permissions import ALLOW_LISTS
from services.orchestrator.routing import (
    ANSWER_FIELDS,
    COVERAGE_AFTER,
    UNSUPPORTED,
    parse_request,
    step_signature,
)
from services.paths import repo_root
from services.telemetry import span


def prompt_fingerprint(name: str) -> str:
    payload = (repo_root() / "prompts" / f"{name}.md").read_bytes()
    return hashlib.sha256(payload).hexdigest()[:16]


def _enter(state: AgentState, node: str) -> None:
    from services.orchestrator.loops import loop_reason

    state["step_count"] += 1
    state["signatures"].append(step_signature(node, "", {}))
    tool_calls = sum(1 for message in state["messages"] if message.get("role") == "tool")
    reason = loop_reason(state["step_count"], state["signatures"], tool_calls)
    if reason is not None and state["escalation"] is None:
        state["escalation"] = {"reason": reason, "summary": "Stopped by the loop breaker."}


def _loop_stopped(state: AgentState) -> bool:
    escalation = state["escalation"]
    return escalation is not None and str(escalation["reason"]).startswith("loop_")


def _token(task: str, tenant_id: str, trace_id: str) -> ScopedToken:
    return ScopedToken(
        tenant_id=tenant_id,
        task=task,
        allowed_tools=list(ALLOW_LISTS[task]),
        trace_id=trace_id,
    )


def _invoke(
    state: AgentState,
    catalog: Catalog,
    token: ScopedToken,
    node: str,
    name: str,
    arguments: dict[str, Any],
) -> ToolEnvelope:
    envelope = call_tool(catalog, token, name, arguments)
    state["messages"].append(
        {
            "role": "tool",
            "name": name,
            "arguments": json.dumps(arguments, sort_keys=True),
            "content": envelope.model_dump_json(),
        }
    )
    state["signatures"].append(step_signature(node, name, arguments))
    return envelope


def _project(data: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any] | None:
    answer: dict[str, Any] = {}
    for field in fields:
        if field not in data:
            return None
        answer[field] = data[field]
    return answer


def _escalate(state: AgentState, reason: str, summary: str) -> None:
    state["escalation"] = {"reason": reason, "summary": summary}
    state["coverage_decision"] = {}
    state["claim_draft"] = {}


def _publish(
    state: AgentState,
    provider: ModelProvider,
    token: ScopedToken,
    prompt_name: str,
    answer: dict[str, Any],
    *,
    destination: str,
) -> None:
    encoded = json.dumps(answer, sort_keys=True)
    request = CompletionRequest(
        model="scripted-fake",
        messages=[
            {"role": "system", "content": prompt_fingerprint(prompt_name)},
            {"role": "user", "content": encoded},
        ],
        tool_allow_list=list(token.allowed_tools),
        response_schema="answer",
        prompt_version=prompt_fingerprint(prompt_name),
        trace_id=state["trace_id"],
    )
    try:
        response = complete_validated(provider, request, state)
    except ModelOutputError:
        _escalate(state, "model_output_invalid", "The model did not return a JSON object.")
        return
    for call in response.tool_calls:
        if call.name not in token.allowed_tools:
            _escalate(state, "forbidden_tool", call.name)
            return
    if destination == "coverage_decision":
        state["coverage_decision"] = answer
    elif destination == "claim_draft":
        state["claim_draft"] = answer
    elif destination == "proposed_payout":
        state["proposed_payout"] = answer
    state["messages"].append({"role": "assistant", "content": encoded})


def _require(envelope: ToolEnvelope) -> dict[str, Any] | None:
    if envelope.status != "ok":
        return None
    return envelope.data


def make_supervisor() -> Any:
    def supervisor(state: AgentState) -> AgentState:
        with span("node.supervisor", trace_id=state["trace_id"]):
            _enter(state, "supervisor")
            if _loop_stopped(state):
                return state
            parsed = parse_request(state["messages"][0]["content"])
            if parsed is None:
                _escalate(state, "unrecognised_request", "The message is not a known scenario.")
            elif parsed[0] in UNSUPPORTED or parsed[0] not in ANSWER_FIELDS:
                _escalate(
                    state,
                    "unsupported_in_phase_1",
                    f"{parsed[0]} is outside the Phase 1 workers.",
                )
        return state

    return supervisor


def make_intake(catalog: Catalog, provider: ModelProvider) -> Any:
    def intake(state: AgentState) -> AgentState:
        with span("node.intake", trace_id=state["trace_id"]):
            _enter(state, "intake")
            if _loop_stopped(state):
                return state
            parsed = parse_request(state["messages"][0]["content"])
            if parsed is None:
                _escalate(state, "unrecognised_request", "The message is not a known scenario.")
                return state
            scenario, entity_id = parsed
            tenant_id = catalog.entity_tenant(entity_id)
            if tenant_id is None:
                _escalate(state, "not_found", "No matching record.")
                return state
            token = _token("intake", tenant_id, state["trace_id"])
            tool_name = (
                "crm.list_interactions" if scenario == "long_history" else "crm.find_customer"
            )
            envelope = _invoke(state, catalog, token, "intake", tool_name, {"entity_id": entity_id})
            data = _require(envelope)
            answer = None if data is None else _project(data, ANSWER_FIELDS[scenario])
            if answer is None:
                _escalate(state, "not_found", "The CRM read did not return the answer.")
                return state
            _publish(state, provider, token, "intake", answer, destination="claim_draft")
        return state

    return intake


def make_verification(catalog: Catalog, provider: ModelProvider) -> Any:
    def verification(state: AgentState) -> AgentState:
        with span("node.verification", trace_id=state["trace_id"]):
            _enter(state, "verification")
            if _loop_stopped(state):
                return state
            parsed = parse_request(state["messages"][0]["content"])
            if parsed is None:
                _escalate(state, "unrecognised_request", "The message is not a known scenario.")
                return state
            scenario, entity_id = parsed
            customer_id = catalog.subject_customer(scenario, entity_id)
            tenant_id = catalog.entity_tenant(entity_id)
            if customer_id is None or tenant_id is None:
                _escalate(state, "not_found", "No customer to verify.")
                return state
            token = _token("verification", tenant_id, state["trace_id"])
            envelope = _invoke(
                state,
                catalog,
                token,
                "verification",
                "crm.verify_identity",
                {"entity_id": customer_id},
            )
            data = _require(envelope)
            identity = None if data is None else _project(data, ANSWER_FIELDS["identity_failure"])
            if identity is None:
                _escalate(state, "not_found", "Identity could not be read.")
                return state
            state["verified_identity"] = identity
            continuing = identity["identity_verified"] is True and scenario in COVERAGE_AFTER
            if not continuing:
                _publish(
                    state,
                    provider,
                    token,
                    "verification",
                    identity,
                    destination="verified_identity",
                )
        return state

    return verification


def make_coverage(catalog: Catalog, provider: ModelProvider) -> Any:
    def coverage(state: AgentState) -> AgentState:
        with span("node.coverage", trace_id=state["trace_id"]):
            _enter(state, "coverage")
            if _loop_stopped(state):
                return state
            parsed = parse_request(state["messages"][0]["content"])
            if parsed is None:
                _escalate(state, "unrecognised_request", "The message is not a known scenario.")
                return state
            scenario, entity_id = parsed
            tenant_id = catalog.entity_tenant(entity_id)
            if tenant_id is None:
                _escalate(state, "not_found", "No matching record.")
                return state
            token = _token("coverage", tenant_id, state["trace_id"])
            answer = _coverage_answer(state, catalog, token, scenario, entity_id)
            if answer is None:
                return state
            _publish(state, provider, token, "coverage", answer, destination="coverage_decision")
        return state

    return coverage


def _coverage_answer(
    state: AgentState,
    catalog: Catalog,
    token: ScopedToken,
    scenario: str,
    entity_id: str,
) -> dict[str, Any] | None:
    if scenario == "shared_contact_ring":
        return _one_tool(state, catalog, token, "graph.shared_contact", entity_id, scenario)
    if scenario == "provider_cluster":
        return _one_tool(state, catalog, token, "graph.provider_cluster", entity_id, scenario)
    primary_name = {
        "loss_outside_window": "policy.get_policy",
        "rider_timing": "policy.get_endorsements",
        "ambiguous_coverage": "policy.get_coverage",
    }[scenario]
    primary = _invoke(state, catalog, token, "coverage", primary_name, {"entity_id": entity_id})
    data = _require(primary)
    answer = None if data is None else _project(data, ANSWER_FIELDS[scenario])
    if data is None or answer is None:
        _escalate(state, "not_found", "The policy read did not return the answer.")
        return None
    policy_id = str(data.get("policy_id", entity_id))
    on_date = str(data.get("loss_date", data.get("policy_start", "")))
    search = _invoke(
        state,
        catalog,
        token,
        "coverage",
        "knowledge.search",
        {"entity_id": policy_id, "query": "coverage circumstances", "on_date": on_date},
    )
    path = _invoke(
        state, catalog, token, "coverage", "graph.coverage_path", {"entity_id": entity_id}
    )
    path_data = _require(path)
    if search.status != "ok" or path_data is None or not _agrees(path_data, answer):
        _escalate(state, "disagreement", "Retrieval or the graph disagreed with the policy read.")
        return None
    return answer


def _one_tool(
    state: AgentState,
    catalog: Catalog,
    token: ScopedToken,
    tool_name: str,
    entity_id: str,
    scenario: str,
) -> dict[str, Any] | None:
    envelope = _invoke(state, catalog, token, "coverage", tool_name, {"entity_id": entity_id})
    data = _require(envelope)
    answer = None if data is None else _project(data, ANSWER_FIELDS[scenario])
    if answer is None:
        _escalate(state, "not_found", "The graph read did not return the answer.")
        return None
    return answer


def _agrees(path: dict[str, Any], answer: dict[str, Any]) -> bool:
    return all(path.get(key) == value for key, value in answer.items())


def make_settlement(catalog: Catalog, provider: ModelProvider) -> Any:
    def settlement(state: AgentState) -> AgentState:
        with span("node.settlement", trace_id=state["trace_id"]):
            _enter(state, "settlement")
            if _loop_stopped(state):
                return state
            parsed = parse_request(state["messages"][0]["content"])
            if parsed is None:
                _escalate(state, "unrecognised_request", "The message is not a known scenario.")
                return state
            scenario, entity_id = parsed
            tenant_id = catalog.entity_tenant(entity_id)
            if tenant_id is None:
                _escalate(state, "not_found", "No matching record.")
                return state
            token = _token("settlement", tenant_id, state["trace_id"])
            tool_name = (
                "claims.create_claim"
                if scenario == "duplicate_claim"
                else "payments.propose_payout"
            )
            envelope = _invoke(
                state, catalog, token, "settlement", tool_name, {"entity_id": entity_id}
            )
            data = _require(envelope)
            if data is not None and scenario == "payout_above_authority":
                claim = catalog.claims.get(str(data["claim_id"]))
                if claim is not None:
                    data = {**data, "adjuster_id": claim["adjuster_id"]}
            answer = None if data is None else _project(data, ANSWER_FIELDS[scenario])
            if answer is None:
                _escalate(state, "not_found", "The settlement read did not return the answer.")
                return state
            destination = "claim_draft" if scenario == "duplicate_claim" else "proposed_payout"
            _publish(state, provider, token, "settlement", answer, destination=destination)
        return state

    return settlement


def make_documents(catalog: Catalog, provider: ModelProvider) -> Any:
    def documents(state: AgentState) -> AgentState:
        with span("node.documents", trace_id=state["trace_id"]):
            _enter(state, "documents")
            if _loop_stopped(state):
                return state
            parsed = parse_request(state["messages"][0]["content"])
            if parsed is None:
                _escalate(state, "unrecognised_request", "The message is not a known scenario.")
                return state
            _scenario, entity_id = parsed
            tenant_id = catalog.entity_tenant(entity_id)
            if tenant_id is None:
                _escalate(state, "not_found", "No matching record.")
                return state
            token = _token("documents", tenant_id, state["trace_id"])
            envelope = _invoke(
                state, catalog, token, "documents", "docs.get_clause", {"entity_id": entity_id}
            )
            data = _require(envelope)
            answer = None if data is None else _project(data, ANSWER_FIELDS["document_injection"])
            if answer is None:
                _escalate(state, "not_found", "The document read did not return the answer.")
                return state
            _publish(state, provider, token, "documents", answer, destination="claim_draft")
        return state

    return documents


def make_finish() -> Any:
    def finish(state: AgentState) -> AgentState:
        with span("node.finish", trace_id=state["trace_id"]):
            _enter(state, "finish")
        return state

    return finish
