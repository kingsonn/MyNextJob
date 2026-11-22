"""Idempotency state machine. Uniqueness is the key, not a check-then-act outside it."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

OutcomeKind = Literal["proceed", "replay", "conflict", "busy", "final"]

RECLAIM_SQL = """
UPDATE idempotency_keys
SET state = 'in_progress', lock_expires_at = %(expires)s, updated_at = %(now)s
WHERE tenant_id = %(tenant_id)s
  AND key = %(key)s
  AND state = 'in_progress'
  AND lock_expires_at <= %(now)s
"""


@dataclass
class Outcome:
    kind: OutcomeKind
    response: dict[str, Any] | None = None
    reclaimed: bool = False


@dataclass
class _Row:
    request_hash: str
    state: str
    response: dict[str, Any] | None
    lock_expires_at: datetime
    effect: dict[str, Any] | None
    reclaim_count: int = 0


class MemoryIdempotency:
    """In-memory stand-in for the primary key. Tests never open Postgres."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], _Row] = {}
        self._lock = threading.Lock()

    def execute(
        self,
        tenant_id: str,
        key: str,
        request_hash: str,
        now: datetime,
        ttl: timedelta,
        effect: Any,
    ) -> Outcome:
        with self._lock:
            outcome = self._begin(tenant_id, key, request_hash, now, ttl)
            if outcome.kind != "proceed":
                return outcome
            row = self.rows[(tenant_id, key)]
            if row.effect is not None:
                row.state = "succeeded"
                row.response = row.effect
                return Outcome("replay", row.effect)
            body = effect()
            if not isinstance(body, dict):
                raise TypeError("side effect must return an object")
            row.effect = body
            row.state = "succeeded"
            row.response = body
            return Outcome("proceed", body, reclaimed=outcome.reclaimed)

    def crash_after_effect(
        self,
        tenant_id: str,
        key: str,
        request_hash: str,
        now: datetime,
        ttl: timedelta,
        body: dict[str, Any],
    ) -> None:
        """Record the side effect and stop before the response is stored."""

        with self._lock:
            self._begin(tenant_id, key, request_hash, now, ttl)
            row = self.rows[(tenant_id, key)]
            row.effect = body
            row.state = "in_progress"
            row.response = None

    def hold(
        self,
        tenant_id: str,
        key: str,
        request_hash: str,
        now: datetime,
        ttl: timedelta,
    ) -> Outcome:
        """Insert in_progress and return before any side effect."""

        with self._lock:
            return self._begin(tenant_id, key, request_hash, now, ttl)

    def fail(
        self, tenant_id: str, key: str, state: str, response: dict[str, Any]
    ) -> None:
        if state not in {"failed_retryable", "failed_final"}:
            raise ValueError("unsupported failure state")
        with self._lock:
            row = self.rows[(tenant_id, key)]
            row.state = state
            row.response = response

    def _begin(
        self,
        tenant_id: str,
        key: str,
        request_hash: str,
        now: datetime,
        ttl: timedelta,
    ) -> Outcome:
        slot = (tenant_id, key)
        row = self.rows.get(slot)
        if row is None:
            self.rows[slot] = _Row(request_hash, "in_progress", None, now + ttl, None)
            return Outcome("proceed")
        if row.request_hash != request_hash:
            return Outcome("conflict")
        if row.effect is not None and row.state != "succeeded":
            row.state = "succeeded"
            row.response = row.effect
            return Outcome("replay", row.effect)
        if row.state == "succeeded":
            return Outcome("replay", row.response)
        if row.state == "failed_final":
            return Outcome("final", row.response)
        if row.state == "failed_retryable":
            row.state = "in_progress"
            row.lock_expires_at = now + ttl
            return Outcome("proceed")
        if row.lock_expires_at > now:
            return Outcome("busy")
        row.reclaim_count += 1
        row.lock_expires_at = now + ttl
        return Outcome("proceed", reclaimed=True)
