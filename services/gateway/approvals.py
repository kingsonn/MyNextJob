"""Approval interrupt and the minimal adjuster page."""

from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict

from services.contracts.state import AgentState
from services.mcp.payments_server.tools import adjuster_token

DecisionName = Literal["approve", "reject", "edit"]


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: DecisionName
    edits: dict[str, Any] | None = None
    reason: str | None = None


class ApprovalBook:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def open(self, state: AgentState, summary: str) -> str:
        approval_id = "apr_" + uuid4().hex[:12]
        self.items[approval_id] = {
            "id": approval_id,
            "status": "pending",
            "summary": summary,
            "decision": None,
            "state": state,
        }
        return approval_id

    def decide(self, approval_id: str, decision: Decision) -> dict[str, Any]:
        item = self.items[approval_id]
        item["status"] = decision.decision
        item["decision"] = decision.model_dump()
        state: AgentState = item["state"]
        state["approval"] = {
            "status": decision.decision,
            "approval_id": approval_id,
            "edits": decision.edits,
            "reason": decision.reason,
        }
        return item


def require_adjuster(authorization: str | None) -> None:
    expected = "Bearer " + adjuster_token()
    if authorization != expected:
        raise HTTPException(status_code=401, detail="adjuster token required")


def create_app(book: ApprovalBook | None = None) -> FastAPI:
    app = FastAPI()
    app.state.book = book or ApprovalBook()

    @app.get("/v1/approvals", response_class=HTMLResponse)
    def page(authorization: str | None = Header(default=None)) -> str:
        require_adjuster(authorization)
        rows = "".join(
            f"<li>{item['id']}: {item['status']} — {item['summary']}</li>"
            for item in app.state.book.items.values()
        )
        return f"<!doctype html><html><body><h1>Approvals</h1><ul>{rows}</ul></body></html>"

    @app.post("/v1/approvals/{approval_id}/decision")
    def decide(
        approval_id: str,
        body: Decision,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_adjuster(authorization)
        item = app.state.book.items.get(approval_id)
        if item is None:
            raise HTTPException(status_code=404, detail="approval not found")
        decided = app.state.book.decide(approval_id, body)
        return {"approval": decided["state"]["approval"]}

    return app
