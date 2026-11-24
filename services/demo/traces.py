"""Record one claim turn and replay it without calling a model."""

from __future__ import annotations

import json
from typing import Any

from services.catalog.store import Catalog
from services.contracts.provider import (
    CompletionRequest,
    CompletionResponse,
    RecordingProvider,
    ScriptedProvider,
)
from services.orchestrator.graph import build_graph, run_turn

MESSAGE = "Please look at loss_outside_window for clm_000001 and tell me the outcome."


class _ClosedProvider:
    def complete(self, request: CompletionRequest) -> CompletionResponse:
        raise RuntimeError("replay has no recording for this request")


def record_trace(catalog: Catalog, trace_id: str = "demo-trace") -> dict[str, Any]:
    recorded = RecordingProvider(ScriptedProvider(), {}, mode="record")
    state = run_turn(build_graph(catalog, recorded), MESSAGE, trace_id)
    outcome = json.loads(state["messages"][-1]["content"])
    return {
        "id": trace_id,
        "message": MESSAGE,
        "messages": state["messages"],
        "cassette": recorded.cassette,
        "outcome": outcome,
    }


def replay_trace(catalog: Catalog, item: dict[str, Any]) -> dict[str, Any]:
    provider = RecordingProvider(_ClosedProvider(), item["cassette"], mode="replay")
    state = run_turn(
        build_graph(catalog, provider), str(item["message"]), str(item["id"]) + "-replay"
    )
    parsed = json.loads(state["messages"][-1]["content"])
    if not isinstance(parsed, dict):
        raise TypeError("replay outcome is not an object")
    return parsed
