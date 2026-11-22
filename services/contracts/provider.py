"""One completion method for every model, including the scripted fake."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from services.contracts.state import AgentState
from services.telemetry import span


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict[str, str] = Field(default_factory=dict)


class CompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    messages: list[dict[str, str]]
    tool_allow_list: list[str]
    response_schema: str
    prompt_version: str
    trace_id: str


class CompletionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    prompt_tokens: int
    completion_tokens: int


class ModelProvider(Protocol):
    def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Return one completion. Failures raise; they are not swallowed."""


class ModelOutputError(Exception):
    """The model did not return a JSON object after the one repair attempt."""


class CassetteMiss(Exception):
    """Replay has no stored response for this request."""


def request_fingerprint(request: CompletionRequest) -> str:
    payload = request.model_dump(exclude={"trace_id"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def json_object(content: str) -> dict[str, object] | None:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


class ScriptedProvider:
    """Fake model. A script is returned in order; otherwise the last user message is echoed."""

    def __init__(self, contents: list[str] | None = None) -> None:
        self.contents = contents
        self.calls = 0

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        if self.contents is None:
            content = request.messages[-1]["content"]
        else:
            content = self.contents[self.calls]
        self.calls += 1
        return CompletionResponse(
            content=content,
            tool_calls=[],
            prompt_tokens=1,
            completion_tokens=1,
        )


class RecordingProvider:
    """Record or replay completions. Replay fails closed when the request is new."""

    def __init__(
        self,
        inner: ModelProvider,
        cassette: dict[str, dict[str, object]],
        *,
        mode: str,
    ) -> None:
        if mode not in {"record", "replay"}:
            raise ValueError("mode must be record or replay")
        self.inner = inner
        self.cassette = cassette
        self.mode = mode

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        key = request_fingerprint(request)
        if self.mode == "replay":
            stored = self.cassette.get(key)
            if stored is None:
                raise CassetteMiss(key)
            return CompletionResponse.model_validate(stored)
        response = self.inner.complete(request)
        self.cassette[key] = response.model_dump()
        return response


def complete_validated(
    provider: ModelProvider, request: CompletionRequest, state: AgentState
) -> CompletionResponse:
    """Call the model. One invalid JSON response is repaired; a second escalates."""

    with span("model.complete", trace_id=request.trace_id, prompt_version=request.prompt_version):
        response = provider.complete(request)
    if json_object(response.content) is not None:
        return response
    state["retry_count"] += 1
    if state["retry_count"] > 1:
        raise ModelOutputError(response.content)
    repair = request.model_copy(
        update={
            "messages": [
                *request.messages,
                {"role": "user", "content": "The previous output was not a JSON object."},
            ]
        }
    )
    with span("model.complete", trace_id=request.trace_id, prompt_version=request.prompt_version):
        second = provider.complete(repair)
    if json_object(second.content) is None:
        state["retry_count"] += 1
        raise ModelOutputError(second.content)
    return second
