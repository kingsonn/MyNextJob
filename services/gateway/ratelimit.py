"""Per-user and per-tenant token buckets. Redis down fails closed."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Protocol


class Bucket(Protocol):
    def allow(self, key: str, now: datetime) -> tuple[bool, int]: ...


class MemoryBucket:
    def __init__(self, rate: int, window: timedelta) -> None:
        self.rate = rate
        self.window = window
        self._tokens: dict[str, float] = {}
        self._updated: dict[str, datetime] = {}

    def allow(self, key: str, now: datetime) -> tuple[bool, int]:
        tokens = self._tokens.get(key, float(self.rate))
        updated = self._updated.get(key, now)
        elapsed = (now - updated).total_seconds()
        window_seconds = self.window.total_seconds()
        tokens = min(float(self.rate), tokens + (elapsed * self.rate / window_seconds))
        if tokens >= 1:
            self._tokens[key] = tokens - 1
            self._updated[key] = now
            return True, 0
        deficit = 1 - tokens
        retry_after = int((deficit * window_seconds / self.rate) + 0.999)
        self._tokens[key] = tokens
        self._updated[key] = now
        return False, max(retry_after, 1)


class RedisBucket:
    """Runtime bucket. Tests pass a fake client and never open a socket."""

    def __init__(self, client: Any, script: str, rate: int, window_ms: int) -> None:
        self.client = client
        self.script = script
        self.rate = rate
        self.window_ms = window_ms

    def allow(self, key: str, now: datetime) -> tuple[bool, int]:
        now_ms = int(now.timestamp() * 1000)
        allowed, retry_ms = self.client.eval(
            self.script,
            1,
            key,
            now_ms,
            self.rate,
            self.window_ms,
            1,
        )
        if int(allowed) == 1:
            return True, 0
        return False, max(1, int(retry_ms) // 1000)


class FailingBucket:
    def allow(self, key: str, now: datetime) -> tuple[bool, int]:
        raise ConnectionError("redis unavailable")


class RateLimiter:
    def __init__(self, user_bucket: Bucket, tenant_bucket: Bucket) -> None:
        self.user_bucket = user_bucket
        self.tenant_bucket = tenant_bucket

    def allow(self, user_id: str, tenant_id: str, now: datetime) -> tuple[bool, int]:
        try:
            user_ok, user_wait = self.user_bucket.allow(f"user:{user_id}", now)
            tenant_ok, tenant_wait = self.tenant_bucket.allow(f"tenant:{tenant_id}", now)
        except ConnectionError:
            return False, 60
        if user_ok and tenant_ok:
            return True, 0
        return False, max(user_wait, tenant_wait)
