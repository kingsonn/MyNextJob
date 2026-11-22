"""Append-only audit log. Rows are not updated or deleted."""

from __future__ import annotations

from datetime import datetime
from typing import Any


class AuditLog:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def append(
        self,
        *,
        actor: str,
        action: str,
        now: datetime,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        claim_id: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        row = {
            "id": f"aud_{len(self.rows) + 1:06d}",
            "actor": actor,
            "action": action,
            "at": now.isoformat(),
            "before": before or {},
            "after": after or {},
            "claim_id": claim_id,
            "reason": reason,
        }
        self.rows.append(row)
        return row

    def search(
        self, *, actor: str | None = None, claim_id: str | None = None
    ) -> list[dict[str, Any]]:
        found = self.rows
        if actor is not None:
            found = [row for row in found if row["actor"] == actor]
        if claim_id is not None:
            found = [row for row in found if row["claim_id"] == claim_id]
        return list(found)
