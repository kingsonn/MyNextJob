"""Guardrails enforced in code. A checker failure closes payouts and logs FAQs."""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass

from services.orchestrator.permissions import ALLOW_LISTS

_MARKERS = (
    "ignore previous",
    "ignore your rules",
    "you are now",
    "jailbreak",
    "approve the payout",
)


@dataclass(frozen=True)
class Verdict:
    blocked: bool
    reason: str
    flagged: bool = False


def check_input(text: str, *, limit: int = 4000) -> Verdict:
    if len(text) > limit:
        return Verdict(True, "length")
    if _marked(text):
        return Verdict(True, "injection")
    return Verdict(False, "allow")


def check_context(text: str) -> Verdict:
    if _marked(text):
        return Verdict(False, "untrusted", flagged=True)
    return Verdict(False, "context")


def check_plan(worker: str, tool: str) -> Verdict:
    allowed: Collection[str] = ALLOW_LISTS.get(worker, frozenset())
    if tool not in allowed:
        return Verdict(True, "forbidden_tool")
    return Verdict(False, "allow")


def check_output(
    text: str,
    citations: list[str],
    *,
    financial: bool = False,
    approved: bool = False,
) -> Verdict:
    lowered = text.lower()
    if "guarantee" in lowered or "this is legal advice" in lowered:
        return Verdict(True, "policy")
    if "covered" in lowered and not citations:
        return Verdict(True, "citation")
    if financial and not approved:
        return Verdict(True, "approval")
    if "+1-555-01" in text or "@example." in text:
        return Verdict(True, "pii")
    return Verdict(False, "allow")


def run_check(risk: str, check: Callable[[], Verdict]) -> Verdict:
    try:
        return check()
    except Exception:
        if risk == "financial":
            return Verdict(True, "fail_closed")
        return Verdict(False, "fail_open")


def _marked(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _MARKERS)
