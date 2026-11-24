"""Fast acknowledgement, then a slow claim-status lookup. No live speech model."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field


def _distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for i, char in enumerate(left, start=1):
        current = [i]
        for j, other in enumerate(right, start=1):
            cost = 0 if char == other else 1
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1]


def word_error_rate(reference: str, heard: str) -> float:
    if not reference:
        return 0.0
    return _distance(reference, heard) / len(reference.split())


def encode(transcript: str) -> bytes:
    return b"CLAIMPILOT\n" + transcript.encode("utf-8") + b"\n"


def recognize(audio: bytes, *, noise: float, seed: int) -> tuple[str, float]:
    if not audio.startswith(b"CLAIMPILOT\n"):
        return "", 0.0
    body = audio.split(b"\n", 2)[1].decode("utf-8")
    if noise <= 0:
        return body, 1.0
    rng = random.Random(seed)
    heard = "".join(char if rng.random() > noise else "x" for char in body)
    confidence = max(0.0, 1.0 - noise)
    return heard, confidence


@dataclass
class Playback:
    chunks: list[str]
    cancelled: bool = False
    cancel_ms: float = 0.0

    def cancel(self) -> None:
        started = time.perf_counter()
        self.chunks.clear()
        self.cancelled = True
        self.cancel_ms = (time.perf_counter() - started) * 1000


@dataclass
class VoiceTurn:
    path: str
    spoken: list[str]
    transcript: str
    confidence: float
    completed: bool
    first_sound_ms: float
    full_answer_ms: float
    stored_audio: bool = False
    events: list[str] = field(default_factory=list)


def claim_status(transcript: str, claims: dict[str, str]) -> VoiceTurn:
    started = time.perf_counter()
    blocked = "ignore previous" in transcript.lower() or "approve the payout" in transcript.lower()
    if blocked:
        spoken = ["I can't do that."]
        return _finish("fast", spoken, transcript, 1.0, False, started, ["blocked"])
    if "status" not in transcript.lower():
        spoken = ["Hello. How can I help?"]
        return _finish("fast", spoken, transcript, 1.0, True, started, ["fast"])
    claim_id = next((claim for claim in claims if claim in transcript), "")
    spoken = ["Let me pull that up."]
    events = ["fast"]
    if not claim_id:
        spoken.append("What is the claim number?")
        return _finish("fast", spoken, transcript, 1.0, False, started, events)
    first_sound = (time.perf_counter() - started) * 1000
    spoken.append(f"Your claim is {claims[claim_id]}.")
    events.append("slow")
    if claim_id in " ".join(spoken):
        raise RuntimeError("a spoken status must not read the raw id")
    turn = _finish("slow", spoken, transcript, 1.0, True, started, events)
    turn.first_sound_ms = first_sound
    return turn


def hear(
    audio: bytes,
    claims: dict[str, str],
    *,
    noise: float = 0.0,
    seed: int = 0,
) -> VoiceTurn:
    transcript, confidence = recognize(audio, noise=noise, seed=seed)
    if confidence < 0.5:
        started = time.perf_counter()
        return _finish(
            "fast",
            ["Please repeat that."],
            transcript,
            confidence,
            False,
            started,
            ["repeat"],
        )
    turn = claim_status(transcript, claims)
    turn.confidence = confidence
    return turn


def _finish(
    path: str,
    spoken: list[str],
    transcript: str,
    confidence: float,
    completed: bool,
    started: float,
    events: list[str],
) -> VoiceTurn:
    elapsed = (time.perf_counter() - started) * 1000
    return VoiceTurn(
        path, spoken, transcript, confidence, completed, elapsed, elapsed, False, events
    )


def percentile(values: list[float], rank: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(rank * (len(ordered) - 1))))
    return ordered[index]
