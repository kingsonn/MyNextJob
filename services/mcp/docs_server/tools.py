"""Read a policy document clause, including a planted injection marker."""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel, ConfigDict

from services.catalog.store import Catalog
from services.contracts.envelope import ScopedToken, ToolEnvelope, error_envelope, ok_envelope
from services.mcp.spec import ToolSpec

TOOL_CLAUSE = "docs.get_clause"


class EntityQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str


def get_clause(catalog: Catalog, token: ScopedToken, arguments: BaseModel) -> ToolEnvelope:
    query = cast(EntityQuery, arguments)
    document = catalog.policy_documents.get(query.entity_id)
    if document is None or document["tenant_id"] != token.tenant_id:
        return error_envelope(
            TOOL_CLAUSE,
            token.trace_id,
            "not_found",
            "No matching record.",
            retryable=False,
        )
    marker = document.get("injection")
    text = marker if isinstance(marker, str) else ""
    return ok_envelope(
        TOOL_CLAUSE,
        token.trace_id,
        {
            "document_id": document["id"],
            "injection_present": text != "",
            "marker": text,
        },
    )


DOC_TOOLS: list[ToolSpec] = [
    ToolSpec(
        TOOL_CLAUSE,
        "Read whether a document contains the planted injection marker.",
        "read_only",
        "not_applicable",
        EntityQuery,
        get_clause,
        "docs",
    )
]
