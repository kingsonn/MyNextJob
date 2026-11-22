"""Payments tools. Propose is a read. Execute is financial and idempotent."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from services.catalog.store import Catalog
from services.contracts.envelope import ScopedToken, ToolEnvelope, error_envelope, ok_envelope
from services.gateway.idempotency import MemoryIdempotency
from services.gateway.keys import request_hash
from services.mcp.spec import ToolSpec
from services.paths import repo_root

FIXED_NOW = datetime(2026, 1, 1)
TOOL_PROPOSE = "payments.propose_payout"
TOOL_EXECUTE = "payments.execute_payout"


class ProposeQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str


class ExecutePayout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    amount: int
    idempotency_key: str
    approval_token: str | None = None


class PaymentLedger:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.machine = MemoryIdempotency()
        self.writes = 0

    def write(self, tenant_id: str, claim_id: str, amount: int, key: str) -> dict[str, Any]:
        for row in self.rows.values():
            if row["tenant_id"] == tenant_id and row["claim_id"] == claim_id:
                return row
        self.writes += 1
        row = {
            "id": f"pay_new_{len(self.rows) + 1:06d}",
            "tenant_id": tenant_id,
            "claim_id": claim_id,
            "amount": amount,
            "idempotency_key": key,
        }
        self.rows[str(row["id"])] = row
        return row


_LEDGERS: dict[int, PaymentLedger] = {}


def ledger_for(catalog: Catalog) -> PaymentLedger:
    return _LEDGERS.setdefault(id(catalog), PaymentLedger())


def adjuster_token() -> str:
    path = repo_root() / "deploy" / "env.example"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("ADJUSTER_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("adjuster token is not configured")


def _missing(tool: str, token: ScopedToken) -> ToolEnvelope:
    return error_envelope(tool, token.trace_id, "not_found", "No matching record.", retryable=False)


def propose_payout(catalog: Catalog, token: ScopedToken, arguments: BaseModel) -> ToolEnvelope:
    query = cast(ProposeQuery, arguments)
    payment = catalog.payments.get(query.entity_id)
    if payment is None or catalog.entity_tenant(query.entity_id) != token.tenant_id:
        return _missing(TOOL_PROPOSE, token)
    claim = catalog.claims[str(payment["claim_id"])]
    adjuster = catalog.adjusters[str(claim["adjuster_id"])]
    amount = int(str(payment["amount"]))
    limit = int(str(adjuster["authority_limit"]))
    return ok_envelope(
        TOOL_PROPOSE,
        token.trace_id,
        {
            "payment_id": payment["id"],
            "claim_id": claim["id"],
            "amount": amount,
            "authority_limit": limit,
            "requires_approval": amount > limit,
        },
    )


def execute_payout(catalog: Catalog, token: ScopedToken, arguments: BaseModel) -> ToolEnvelope:
    query = cast(ExecutePayout, arguments)
    claim = catalog.claims.get(query.claim_id)
    if claim is None or claim["tenant_id"] != token.tenant_id:
        return _missing(TOOL_EXECUTE, token)
    adjuster = catalog.adjusters[str(claim["adjuster_id"])]
    over = query.amount > int(str(adjuster["authority_limit"]))
    if over and query.approval_token != adjuster_token():
        return error_envelope(
            TOOL_EXECUTE,
            token.trace_id,
            "approval_required",
            "This payout needs an adjuster approval token.",
            retryable=False,
            key=query.idempotency_key,
        )
    ledger = ledger_for(catalog)
    body = {"amount": query.amount, "claim_id": query.claim_id}
    outcome = ledger.machine.execute(
        token.tenant_id,
        query.idempotency_key,
        request_hash(body),
        FIXED_NOW,
        timedelta(seconds=30),
        lambda: ledger.write(token.tenant_id, query.claim_id, query.amount, query.idempotency_key),
    )
    if outcome.kind == "conflict":
        return error_envelope(
            TOOL_EXECUTE,
            token.trace_id,
            "idempotency_conflict",
            "This key was already used for a different request.",
            retryable=False,
            key=query.idempotency_key,
        )
    if outcome.kind == "busy":
        return error_envelope(
            TOOL_EXECUTE,
            token.trace_id,
            "idempotency_in_progress",
            "The original request is still running.",
            retryable=True,
            key=query.idempotency_key,
        )
    return ok_envelope(
        TOOL_EXECUTE,
        token.trace_id,
        {"payment": outcome.response or {}, "replayed": outcome.kind == "replay"},
        key=query.idempotency_key,
        replayed=outcome.kind == "replay",
    )


PAYMENT_TOOLS: list[ToolSpec] = [
    ToolSpec(
        TOOL_PROPOSE,
        "Read a payout and whether it exceeds authority.",
        "read_only",
        "not_applicable",
        ProposeQuery,
        propose_payout,
        "payments",
    ),
    ToolSpec(
        TOOL_EXECUTE,
        "Record one payout for a claim.",
        "financial",
        "required",
        ExecutePayout,
        execute_payout,
        "payments",
    ),
]
