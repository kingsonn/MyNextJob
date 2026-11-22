"""Tool result envelope from appendix C."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TOOL_VERSION = "1.0.0"


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    retryable: bool


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    version: str
    trace_id: str


class IdempotencyInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str | None = None
    replayed: bool


class ToolEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "error"]
    data: dict[str, Any] = Field(default_factory=dict)
    error: ToolError | None = None
    provenance: Provenance
    idempotency: IdempotencyInfo
    untrusted_content: bool = True


class ScopedToken(BaseModel):
    """Short-lived token. It names the tenant, the task, and the allowed tools."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    task: str
    allowed_tools: list[str]
    trace_id: str


def ok_envelope(
    tool: str,
    trace_id: str,
    data: dict[str, Any],
    *,
    key: str | None = None,
    replayed: bool = False,
) -> ToolEnvelope:
    return ToolEnvelope(
        status="ok",
        data=data,
        error=None,
        provenance=Provenance(tool=tool, version=TOOL_VERSION, trace_id=trace_id),
        idempotency=IdempotencyInfo(key=key, replayed=replayed),
        untrusted_content=True,
    )


def error_envelope(
    tool: str,
    trace_id: str,
    code: str,
    message: str,
    *,
    retryable: bool,
    key: str | None = None,
) -> ToolEnvelope:
    return ToolEnvelope(
        status="error",
        data={},
        error=ToolError(code=code, message=message, retryable=retryable),
        provenance=Provenance(tool=tool, version=TOOL_VERSION, trace_id=trace_id),
        idempotency=IdempotencyInfo(key=key, replayed=False),
        untrusted_content=True,
    )


def parse_envelope(payload: object) -> ToolEnvelope:
    """Reject a tool payload that does not match the envelope."""

    return ToolEnvelope.model_validate(payload)
