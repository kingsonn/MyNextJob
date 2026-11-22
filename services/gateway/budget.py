"""Token and shadow-cost budgets. Prices are representative, not invoices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Action = Literal["allow", "cache", "cheap", "handoff"]


@dataclass
class BudgetState:
    remaining_tokens: int
    shadow_micros: int
    tier: str


@dataclass(frozen=True)
class BudgetCaps:
    session_tokens: int
    tenant_shadow_micros: int
    prices_per_token_micros: dict[str, int]


def decide(
    state: BudgetState,
    tokens: int,
    caps: BudgetCaps,
    *,
    cache_hit: bool,
) -> Action:
    if state.remaining_tokens < tokens:
        if state.tier == "strong":
            return "cheap"
        return "handoff"
    price = caps.prices_per_token_micros[state.tier]
    if state.shadow_micros + (tokens * price) > caps.tenant_shadow_micros:
        if cache_hit:
            return "cache"
        if state.tier == "strong":
            return "cheap"
        return "handoff"
    return "allow"


def charge(state: BudgetState, tokens: int, caps: BudgetCaps) -> None:
    price = caps.prices_per_token_micros[state.tier]
    state.remaining_tokens -= tokens
    state.shadow_micros += tokens * price
