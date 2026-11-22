"""Compile the Phase 1 graph and resume it from a checkpointer."""

from __future__ import annotations

from typing import Any, cast

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from services.catalog.store import Catalog
from services.contracts.provider import ModelProvider
from services.contracts.state import AgentState, GraphState
from services.orchestrator.routing import COVERAGE_AFTER, INTAKE, VERIFY_FIRST, parse_request
from services.orchestrator.workers import (
    make_coverage,
    make_finish,
    make_intake,
    make_supervisor,
    make_verification,
)

_STATE_KEYS = (
    "messages",
    "verified_identity",
    "claim_draft",
    "coverage_decision",
    "proposed_payout",
    "approval",
    "step_count",
    "signatures",
    "budget",
    "trace_id",
    "escalation",
    "retry_count",
)


def build_graph(
    catalog: Catalog,
    provider: ModelProvider,
    checkpointer: Any = None,
    interrupt_before: list[str] | None = None,
) -> Any:
    builder: StateGraph[AgentState] = StateGraph(AgentState)
    builder.add_node("supervisor", make_supervisor())
    builder.add_node("intake", make_intake(catalog, provider))
    builder.add_node("verification", make_verification(catalog, provider))
    builder.add_node("coverage", make_coverage(catalog, provider))
    builder.add_node("finish", make_finish())
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        _route_first,
        ["intake", "verification", "finish"],
    )
    builder.add_edge("intake", "finish")
    builder.add_conditional_edges("verification", _route_after, ["coverage", "finish"])
    builder.add_edge("coverage", "finish")
    builder.add_edge("finish", END)
    saver = MemorySaver() if checkpointer is None else checkpointer
    return builder.compile(checkpointer=saver, interrupt_before=interrupt_before or [])


def initial_state(message: str, trace_id: str) -> AgentState:
    return {
        "messages": [{"role": "user", "content": message}],
        "verified_identity": None,
        "claim_draft": {},
        "coverage_decision": {},
        "proposed_payout": None,
        "approval": None,
        "step_count": 0,
        "signatures": [],
        "budget": {"remaining_tokens": 8000, "shadow_cost": "0"},
        "trace_id": trace_id,
        "escalation": None,
        "retry_count": 0,
    }


def freeze_state(result: object) -> AgentState:
    if not isinstance(result, dict):
        raise TypeError("graph result is not a state dict")
    payload = {key: result[key] for key in _STATE_KEYS}
    validated = GraphState.model_validate(payload)
    return cast(AgentState, validated.model_dump())


def run_turn(graph: Any, message: str, thread_id: str) -> AgentState:
    result = graph.invoke(
        initial_state(message, thread_id),
        {"configurable": {"thread_id": thread_id}},
    )
    return freeze_state(result)


def _route_first(state: AgentState) -> str:
    if state["escalation"] is not None:
        return "finish"
    parsed = parse_request(state["messages"][0]["content"])
    if parsed is None:
        return "finish"
    scenario = parsed[0]
    if scenario in INTAKE:
        return "intake"
    if scenario in VERIFY_FIRST:
        return "verification"
    return "finish"


def _route_after(state: AgentState) -> str:
    if state["escalation"] is not None:
        return "finish"
    identity = state["verified_identity"] or {}
    if identity.get("identity_verified") is not True:
        return "finish"
    parsed = parse_request(state["messages"][0]["content"])
    if parsed is not None and parsed[0] in COVERAGE_AFTER:
        return "coverage"
    return "finish"
