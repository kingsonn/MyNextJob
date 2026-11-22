"""Shared tool dispatch. Permissions are checked here, not in prompts."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from services.catalog.store import Catalog
from services.contracts.envelope import (
    ScopedToken,
    ToolEnvelope,
    error_envelope,
    parse_envelope,
)
from services.mcp.claims_server.tools import CLAIM_TOOLS
from services.mcp.crm_server.tools import CRM_TOOLS
from services.mcp.docs_server.tools import DOC_TOOLS
from services.mcp.graph_server.tools import GRAPH_TOOLS
from services.mcp.payments_server.tools import PAYMENT_TOOLS
from services.mcp.policy_server.tools import POLICY_TOOLS
from services.mcp.spec import ToolSpec
from services.telemetry import span


def tool_registry() -> dict[str, ToolSpec]:
    specs: dict[str, ToolSpec] = {}
    for spec in (*POLICY_TOOLS, *CRM_TOOLS, *GRAPH_TOOLS, *PAYMENT_TOOLS, *CLAIM_TOOLS, *DOC_TOOLS):
        specs[spec.name] = spec
    return specs


def call_tool(
    catalog: Catalog,
    token: ScopedToken,
    name: str,
    arguments: dict[str, Any],
) -> ToolEnvelope:
    with span("tool." + name, tenant_id=token.tenant_id, trace_id=token.trace_id):
        registry = tool_registry()
        spec = registry.get(name)
        if spec is None or name not in token.allowed_tools:
            return error_envelope(
                name,
                token.trace_id,
                "forbidden_tool",
                "This worker cannot call that tool.",
                retryable=False,
            )
        try:
            parsed = spec.input_model.model_validate(arguments)
        except ValidationError:
            return error_envelope(
                name,
                token.trace_id,
                "validation_error",
                "The tool arguments do not match the schema.",
                retryable=False,
            )
        return spec.handler(catalog, token, parsed)


def accept_tool_result(payload: object, trace_id: str) -> ToolEnvelope:
    """Tell the supervisor when a tool result is not a valid envelope."""

    try:
        return parse_envelope(payload)
    except ValidationError:
        return error_envelope(
            "tool.unknown",
            trace_id,
            "malformed_result",
            "The tool result did not match the envelope schema.",
            retryable=False,
        )
