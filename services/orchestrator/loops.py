"""Loop breaker: hard caps, repeated signatures, and no-progress stops."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from services.paths import repo_root


@dataclass(frozen=True)
class LoopLimits:
    max_steps: int = 16
    max_tool_calls: int = 8
    max_identical_consecutive: int = 3
    signature_repeats: int = 3
    signature_window: int = 10
    no_progress_steps: int = 10


def load_limits() -> LoopLimits:
    import yaml

    path = repo_root() / "services" / "gateway" / "reliability.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    limits = raw["limits"]
    return LoopLimits(
        max_steps=int(limits["max_steps"]),
        max_tool_calls=int(limits["max_tool_calls"]),
        max_identical_consecutive=int(limits["max_identical_consecutive"]),
        signature_repeats=int(limits["signature_repeats"]),
        signature_window=int(limits["signature_window"]),
        no_progress_steps=int(limits["no_progress_steps"]),
    )


def loop_reason(
    step_count: int,
    signatures: list[str],
    tool_calls: int,
    *,
    limits: LoopLimits | None = None,
    fact_hashes: list[str] | None = None,
) -> str | None:
    rules = limits or load_limits()
    if step_count > rules.max_steps:
        return "loop_steps"
    if tool_calls > rules.max_tool_calls:
        return "loop_tools"
    if _consecutive(signatures) >= rules.max_identical_consecutive:
        return "loop_consecutive"
    window = signatures[-rules.signature_window :]
    if window and max(Counter(window).values()) >= rules.signature_repeats:
        return "loop_signature"
    if fact_hashes and _no_progress(fact_hashes, rules.no_progress_steps):
        return "loop_no_progress"
    return None


def _consecutive(signatures: list[str]) -> int:
    if not signatures:
        return 0
    last = signatures[-1]
    count = 0
    for signature in reversed(signatures):
        if signature != last:
            break
        count += 1
    return count


def _no_progress(fact_hashes: list[str], limit: int) -> bool:
    if len(fact_hashes) < limit:
        return False
    return len(set(fact_hashes[-limit:])) == 1
