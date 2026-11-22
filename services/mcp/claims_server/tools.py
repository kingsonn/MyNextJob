"""Claim submission. A repeated submission key returns the original claim."""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel, ConfigDict

from services.catalog.store import Catalog
from services.contracts.envelope import ScopedToken, ToolEnvelope, error_envelope, ok_envelope
from services.mcp.spec import ToolSpec

TOOL_CREATE = "claims.create_claim"


class EntityQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str


def create_claim(catalog: Catalog, token: ScopedToken, arguments: BaseModel) -> ToolEnvelope:
    query = cast(EntityQuery, arguments)
    claim = catalog.claims.get(query.entity_id)
    if claim is None or claim["tenant_id"] != token.tenant_id:
        return error_envelope(
            TOOL_CREATE,
            token.trace_id,
            "not_found",
            "No matching record.",
            retryable=False,
        )
    key = str(claim["submission_key"])
    matches = [
        row
        for row in catalog.claims.values()
        if row["tenant_id"] == token.tenant_id and row["submission_key"] == key
    ]
    amount = claim["amount"]
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise TypeError("claim amount is not an int")
    return ok_envelope(
        TOOL_CREATE,
        token.trace_id,
        {
            "claim_id": claim["id"],
            "idempotency_key": key,
            "claim_count": len(matches),
            "rejected_amount": amount + 1,
        },
    )


CLAIM_TOOLS: list[ToolSpec] = [
    ToolSpec(
        TOOL_CREATE,
        "Return the claim already stored for this submission key.",
        "read_only",
        "not_applicable",
        EntityQuery,
        create_claim,
        "claims",
    )
]
