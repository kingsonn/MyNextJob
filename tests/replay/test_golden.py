"""Full golden run, recorded and then replayed with no model calls."""

from __future__ import annotations

import json
import os
from pathlib import Path

from evals.runners.score import (
    assistant_payload,
    outcome_score,
    tool_calls_from_state,
    trajectory_score,
)
from generator.build import generate
from generator.config import load_config
from services.catalog.load import catalog_from_dataset
from services.contracts.provider import (
    CompletionRequest,
    CompletionResponse,
    RecordingProvider,
    ScriptedProvider,
)
from services.mcp.dispatch import tool_registry
from services.orchestrator.graph import build_graph, run_turn
from services.paths import repo_root

BASELINE = repo_root() / "evals" / "baselines" / "phase-1.json"


class _ExplodingProvider:
    def complete(self, request: CompletionRequest) -> CompletionResponse:
        raise AssertionError("replay called the inner model")


def _scores(catalog: object, provider: RecordingProvider) -> dict[str, dict[str, float]]:
    graph = build_graph(catalog, provider)  # type: ignore[arg-type]
    registered = set(tool_registry())
    scores: dict[str, dict[str, float]] = {}
    golden_dir = repo_root() / "data" / "golden"
    for path in sorted(golden_dir.glob("golden-*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        state = run_turn(graph, case["customer_turns"][0], case["id"])
        calls = tool_calls_from_state(state)
        assert {call["tool"] for call in calls} <= registered
        scores[case["id"]] = {
            "outcome": outcome_score(assistant_payload(state), case["answer_key"]),
            "trajectory": trajectory_score(calls, case["expected_tool_calls"]),
        }
    return scores


def test_golden_baseline_records_and_replays() -> None:
    dataset = generate(load_config())
    catalog = catalog_from_dataset(dataset)
    recorded = RecordingProvider(ScriptedProvider(), {}, mode="record")
    first = _scores(catalog, recorded)
    payload = {
        "seed": dataset.seed,
        "scenarios": first,
        "outcome_mean": sum(item["outcome"] for item in first.values()) / len(first),
        "trajectory_mean": sum(item["trajectory"] for item in first.values()) / len(first),
    }
    if os.environ.get("CLAIMPILOT_WRITE_BASELINE") == "1":
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    committed = json.loads(Path(BASELINE).read_text(encoding="utf-8"))
    assert payload["scenarios"] == committed["scenarios"]
    assert payload["outcome_mean"] == committed["outcome_mean"]
    assert payload["trajectory_mean"] == committed["trajectory_mean"]
    replay = RecordingProvider(_ExplodingProvider(), recorded.cassette, mode="replay")
    assert _scores(catalog, replay) == first
