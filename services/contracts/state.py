"""Graph state from appendix D, plus the retry counter from section 7."""

from __future__ import annotations

from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field


class GraphState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[dict[str, str]]
    verified_identity: dict[str, Any] | None = None
    claim_draft: dict[str, Any] = Field(default_factory=dict)
    coverage_decision: dict[str, Any] = Field(default_factory=dict)
    proposed_payout: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None
    step_count: int = 0
    signatures: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(
        default_factory=lambda: {"remaining_tokens": 8000, "shadow_cost": "0"}
    )
    trace_id: str
    escalation: dict[str, Any] | None = None
    retry_count: int = 0


class AgentState(TypedDict):
    messages: list[dict[str, str]]
    verified_identity: dict[str, Any] | None
    claim_draft: dict[str, Any]
    coverage_decision: dict[str, Any]
    proposed_payout: dict[str, Any] | None
    approval: dict[str, Any] | None
    step_count: int
    signatures: list[str]
    budget: dict[str, Any]
    trace_id: str
    escalation: dict[str, Any] | None
    retry_count: int
