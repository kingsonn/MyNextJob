"""Shadow-price cost of routed calls versus one strong model."""

from __future__ import annotations

from services.gateway.router import route
from services.paths import repo_root


def _prices() -> dict[str, int]:
    import yaml

    path = repo_root() / "services" / "gateway" / "router_policy.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    prices = loaded["prices_per_token_micros"]
    if not isinstance(prices, dict):
        raise TypeError("prices must be a mapping")
    return {str(key): int(value) for key, value in prices.items()}


def compare(cases: list[tuple[str, int]]) -> dict[str, float]:
    prices = _prices()
    routed = 0
    single = 0
    resolved = 0
    for task_class, tokens in cases:
        decision = route(task_class)
        if decision.tier != "human":
            resolved += 1
        routed += tokens * prices[decision.tier]
        single += tokens * prices["strong"]
    saving = 0.0 if single == 0 else 1.0 - (routed / single)
    per_claim = 0.0 if resolved == 0 else routed / resolved
    return {
        "routed_micros": float(routed),
        "single_micros": float(single),
        "saving": saving,
        "resolved": float(resolved),
        "routed_micros_per_claim": per_claim,
    }
