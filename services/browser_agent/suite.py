"""Thirty scripted portal tasks across the three layouts."""

from __future__ import annotations

from dataclasses import dataclass

from services.contracts.provider import CompletionRequest, CompletionResponse, ModelProvider

from .agent import update_note
from .session import FlaskPage, open_portal


class _ActionProvider:
    def __init__(self, hostile: bool) -> None:
        self.hostile = hostile

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        if self.hostile:
            content = '{"action":"goto","url":"https://evil.example"}'
        else:
            content = '{"action":"fill","name":"adjuster_note"}'
        return CompletionResponse(
            content=content,
            tool_calls=[],
            prompt_tokens=1,
            completion_tokens=1,
        )


@dataclass(frozen=True)
class SuiteReport:
    total: int
    successes: int
    recovered: int
    gaps: int
    average_steps: float

    @property
    def success_rate(self) -> float:
        return self.successes / self.total

    @property
    def recovery_rate(self) -> float:
        if self.gaps == 0:
            return 1.0
        return self.recovered / self.gaps


def run_suite() -> SuiteReport:
    successes = 0
    recovered = 0
    gaps = 0
    steps = 0
    for index in range(30):
        layout = str((index % 3) + 1)
        kind = "ok" if index < 24 else "gap" if index < 27 else "hostile"
        page = open_portal()
        provider: ModelProvider = _ActionProvider(kind == "hostile")
        result = update_note(
            page,
            provider,
            claim_id=f"clm_{index + 1:06d}",
            tenant_id="ten_01",
            note="received",
            idempotency_key=f"portal-{index}",
            layout=layout,
            gap=kind != "ok",
        )
        steps += result.steps
        if kind == "gap":
            gaps += 1
            if result.success:
                recovered += 1
        if result.success:
            successes += 1
        elif kind == "hostile":
            assert result.escalated is True
            assert _writes(page) == 0
    return SuiteReport(30, successes, recovered, gaps, steps / 30)


def _writes(page: FlaskPage) -> int:
    store = page.client.application.config["STORE"]
    return int(store.writes)
