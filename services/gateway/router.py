"""Rule router. The policy table chooses the tier; prompts do not."""

from __future__ import annotations

from dataclasses import dataclass

from services.paths import repo_root

_ORDER = ("cache", "local", "fast", "strong", "human")


@dataclass(frozen=True)
class RouteDecision:
    task_class: str
    risk: str
    tier: str
    reason: str
    approval_required: bool


def load_policy() -> dict[str, dict[str, object]]:
    import yaml

    path = repo_root() / "services" / "gateway" / "router_policy.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    tasks = loaded["tasks"]
    if not isinstance(tasks, dict):
        raise TypeError("router policy tasks must be a mapping")
    return {str(key): value for key, value in tasks.items() if isinstance(value, dict)}


def classify(text: str) -> str:
    lowered = text.lower()
    if "status" in lowered or "hello" in lowered or "thank" in lowered:
        return "voice"
    if "payout" in lowered:
        return "payout"
    if "coverage" in lowered or "rider" in lowered:
        return "coverage"
    if "extract" in lowered:
        return "extraction"
    if lowered.startswith("what is"):
        return "faq"
    return "classification"


def route(
    task_class: str,
    *,
    confidence: float = 1.0,
    schema_failures: int = 0,
    guardrail_disagreement: bool = False,
    citation_failed: bool = False,
) -> RouteDecision:
    spec = load_policy()[task_class]
    tier = str(spec["primary"])
    triggers = spec["escalate_on"]
    if not isinstance(triggers, list):
        raise TypeError("escalate_on must be a list")
    names = {str(item) for item in triggers}
    reasons = ["policy"]
    if "low_confidence" in names and confidence < 0.6:
        tier = _escalate(tier)
        reasons.append("low_confidence")
    if "schema_validation" in names and schema_failures >= 2:
        tier = _escalate(tier)
        reasons.append("schema_validation")
    if "guardrail_disagreement" in names and guardrail_disagreement:
        tier = _escalate(tier)
        reasons.append("guardrail_disagreement")
    if "citation_failed" in names and citation_failed:
        tier = _escalate(tier)
        reasons.append("citation_failed")
    return RouteDecision(
        task_class,
        str(spec["risk"]),
        tier,
        ",".join(reasons),
        bool(spec["approval"]) or str(spec["risk"]) == "financial",
    )


def _escalate(tier: str) -> str:
    index = _ORDER.index(tier)
    return _ORDER[min(index + 1, len(_ORDER) - 1)]
