"""Tool specification shared by the servers and the dispatcher."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from services.catalog.store import Catalog
from services.contracts.envelope import ScopedToken, ToolEnvelope

ToolHandler = Callable[[Catalog, ScopedToken, BaseModel], ToolEnvelope]


class ToolSpec:
    def __init__(
        self,
        name: str,
        description: str,
        risk_tier: str,
        idempotency: str,
        input_model: type[BaseModel],
        handler: ToolHandler,
        server: str,
    ) -> None:
        self.name = name
        self.description = description
        self.risk_tier = risk_tier
        self.idempotency = idempotency
        self.input_model = input_model
        self.handler = handler
        self.server = server

    def json_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()
