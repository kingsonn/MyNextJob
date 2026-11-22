"""Reversible masking. Logs store tokens, not the original value."""

from __future__ import annotations

import re
from datetime import datetime

from services.guardrails.audit import AuditLog

_PHONE = re.compile(r"\+1-555-01[0-9]{2}")
_EMAIL = re.compile(r"[A-Za-z0-9._+-]+@example\.(?:com|net|org)")


class Vault:
    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}
        self._values: dict[str, str] = {}
        self._count = 0

    def mask(self, text: str) -> str:
        masked = _EMAIL.sub(lambda match: self._token(match.group(0), "email"), text)
        return _PHONE.sub(lambda match: self._token(match.group(0), "phone"), masked)

    def reveal(self, token: str, *, reason: str, actor: str, audit: AuditLog) -> str:
        if not reason.strip():
            raise ValueError("a reason is required")
        value = self._values.get(token)
        if value is None:
            raise KeyError(token)
        audit.append(
            actor=actor, action="unmask", now=_now(), reason=reason, after={"token": token}
        )
        return value

    def _token(self, value: str, kind: str) -> str:
        existing = self._tokens.get(value)
        if existing is not None:
            return existing
        self._count += 1
        token = f"[{kind}:{self._count}]"
        self._tokens[value] = token
        self._values[token] = value
        return token


def _now() -> datetime:
    return datetime(2026, 1, 1)
