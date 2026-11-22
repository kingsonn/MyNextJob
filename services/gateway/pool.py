"""Provider pool: health, cooldown, and failover inside one tier."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from services.contracts.provider import CompletionRequest, CompletionResponse, ModelProvider


class ProviderError(Exception):
    def __init__(self, status: int, retry_after: int = 1, remaining: int | None = None) -> None:
        self.status = status
        self.retry_after = retry_after
        self.remaining = remaining
        super().__init__(f"provider status {status}")


@dataclass
class _Slot:
    name: str
    provider: ModelProvider
    state: str = "healthy"
    cooldown_until: datetime | None = None
    remaining: int | None = None


@dataclass
class PoolResult:
    response: CompletionResponse | None
    provider: str | None
    reason: str
    handoff: bool = False


@dataclass
class ProviderPool:
    slots: list[_Slot]
    events: list[str] = field(default_factory=list)

    @classmethod
    def from_providers(cls, providers: list[tuple[str, ModelProvider]]) -> ProviderPool:
        return cls([_Slot(name, provider) for name, provider in providers])

    def complete(self, request: CompletionRequest, now: datetime) -> PoolResult:
        for slot in self.slots:
            self._refresh(slot, now)
            if slot.state != "healthy":
                continue
            try:
                response = slot.provider.complete(request)
            except ProviderError as exc:
                if exc.status in {408, 429, 500, 502, 503, 504}:
                    slot.state = "cooling_down"
                    slot.cooldown_until = now + timedelta(seconds=exc.retry_after)
                    slot.remaining = exc.remaining
                    self.events.append(f"{slot.name}:{exc.status}")
                    continue
                raise
            self.events.append(f"{slot.name}:ok")
            return PoolResult(response, slot.name, "served")
        self.events.append("handoff")
        return PoolResult(None, None, "all_providers_down", handoff=True)

    def _refresh(self, slot: _Slot, now: datetime) -> None:
        cooled = slot.state == "cooling_down" and slot.cooldown_until is not None
        if cooled and slot.cooldown_until is not None and slot.cooldown_until <= now:
            slot.state = "healthy"
            slot.cooldown_until = None
            slot.remaining = None
