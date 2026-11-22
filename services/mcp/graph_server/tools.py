"""Graph MCP tools. Parameterised reads only."""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel

from services.catalog.store import Catalog
from services.contracts.envelope import ScopedToken, ToolEnvelope, error_envelope, ok_envelope
from services.mcp.policy_server.tools import EntityQuery
from services.mcp.spec import ToolSpec


def _missing(tool: str, token: ScopedToken) -> ToolEnvelope:
    return error_envelope(tool, token.trace_id, "not_found", "No matching record.", retryable=False)


def _path(catalog: Catalog, token: ScopedToken, arguments: BaseModel) -> ToolEnvelope:
    query = cast(EntityQuery, arguments)
    data = catalog.coverage_path(token.tenant_id, query.entity_id)
    if data is None:
        return _missing("graph.coverage_path", token)
    return ok_envelope("graph.coverage_path", token.trace_id, data)


def _ring(catalog: Catalog, token: ScopedToken, arguments: BaseModel) -> ToolEnvelope:
    query = cast(EntityQuery, arguments)
    data = catalog.shared_contact(token.tenant_id, query.entity_id)
    if data is None:
        return _missing("graph.shared_contact", token)
    return ok_envelope("graph.shared_contact", token.trace_id, data)


def _impact(catalog: Catalog, token: ScopedToken, arguments: BaseModel) -> ToolEnvelope:
    query = cast(EntityQuery, arguments)
    data = catalog.endorsement_impact(token.tenant_id, query.entity_id)
    if data is None:
        return _missing("graph.impact", token)
    return ok_envelope("graph.impact", token.trace_id, data)


def _cluster(catalog: Catalog, token: ScopedToken, arguments: BaseModel) -> ToolEnvelope:
    query = cast(EntityQuery, arguments)
    data = catalog.provider_cluster(token.tenant_id, query.entity_id)
    if data is None:
        return _missing("graph.provider_cluster", token)
    return ok_envelope("graph.provider_cluster", token.trace_id, data)


GRAPH_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "graph.coverage_path",
        "Walk policy, coverage, endorsement, and claim links for a coverage decision.",
        "read_only",
        "not_applicable",
        EntityQuery,
        _path,
        "graph",
    ),
    ToolSpec(
        "graph.shared_contact",
        "Find customers who share both a phone and an address.",
        "read_only",
        "not_applicable",
        EntityQuery,
        _ring,
        "graph",
    ),
    ToolSpec(
        "graph.provider_cluster",
        "Find the tightest set of at least five claims sharing a provider, loss date, and amount.",
        "read_only",
        "not_applicable",
        EntityQuery,
        _cluster,
        "graph",
    ),
    ToolSpec(
        "graph.impact",
        "List active policies affected by an endorsement.",
        "read_only",
        "not_applicable",
        EntityQuery,
        _impact,
        "graph",
    ),
)
