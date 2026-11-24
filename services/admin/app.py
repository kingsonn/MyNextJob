"""Admin routes. Role checks run on the server for every call."""

from __future__ import annotations

import html
import json
from collections.abc import Iterator
from datetime import datetime
from typing import Any, NoReturn, cast

from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from jinja2 import Environment
from starlette.datastructures import UploadFile

from services.catalog.store import Catalog
from services.gateway.agent_run import live_events
from services.gateway.cache import SemanticCache
from services.guardrails.audit import AuditLog
from services.guardrails.pii import Vault
from services.ingestion.adaptive import answer
from services.ingestion.corpus import CorpusFile
from services.ingestion.pipeline import Library, Rejected
from services.knowledge.retrieve import ChunkIndex
from services.paths import repo_root

_READ_CLAIMS = {"admin", "adjuster", "auditor", "engineer"}
_ADMIN = {"admin"}
_AUDIT_READ = {"admin", "auditor"}
_METRICS = {"admin", "engineer"}
_UNMASK = {"admin", "adjuster"}
NOW_LABEL = "2026-01-01T00:00:00"


def role_tokens() -> dict[str, str]:
    mapping = {
        "ADMIN_TOKEN": "admin",
        "ADJUSTER_TOKEN": "adjuster",
        "AUDITOR_TOKEN": "auditor",
        "ENGINEER_TOKEN": "engineer",
    }
    found: dict[str, str] = {}
    for line in (repo_root() / "deploy" / "env.example").read_text(encoding="utf-8").splitlines():
        for key, role in mapping.items():
            if line.startswith(key + "="):
                found[line.split("=", 1)[1].strip()] = role
    return found


def create_app(
    catalog: Catalog,
    library: Library | None = None,
    audit: AuditLog | None = None,
    vault: Vault | None = None,
    traces: dict[str, dict[str, Any]] | None = None,
) -> FastAPI:
    app = FastAPI()
    app.state.catalog = catalog
    app.state.library = library or Library()
    app.state.audit = audit or AuditLog()
    app.state.vault = vault or Vault()
    app.state.csrf = "csrf-phase4"
    app.state.failures = {}
    app.state.decisions = {}
    app.state.traces = traces or {}
    app.state.replay = _unavailable_replay

    @app.middleware("http")
    async def carry_session(request: Request, call_next: Any) -> Any:
        token = request.cookies.get("admin_session")
        if token and "authorization" not in request.headers:
            headers = list(request.scope["headers"])
            headers.append((b"authorization", f"Bearer {token}".encode()))
            request.scope["headers"] = headers
        return await call_next(request)

    def actor(authorization: str | None) -> str:
        if authorization is None or not authorization.startswith("Bearer "):
            _fail(app, "missing")
        token = authorization.removeprefix("Bearer ").strip()
        role = role_tokens().get(token)
        if role is None:
            _fail(app, token)
        app.state.failures[token] = 0
        return role

    def csrf_ok(request_token: str | None) -> None:
        if request_token != app.state.csrf:
            raise HTTPException(status_code=403, detail="csrf")

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        form = (
            "<form method='post' action='/admin/login'>"
            "<label>Token <input name='token'></label> "
            "<button>Open</button></form>"
            "<p>Paste the admin token from deploy/env.example. No model key is required.</p>"
            "<p><a href='/voice'>Speak or text about a claim</a></p>"
        )
        return _page("ClaimPilot", form)

    @app.post("/admin/login")
    def login(token: str = Form()) -> RedirectResponse:
        response = RedirectResponse("/admin/claims", status_code=303)
        response.set_cookie("admin_session", token, httponly=True)
        return response

    @app.get("/voice", response_class=HTMLResponse)
    def voice_page() -> str:
        return _page("Speak", _SPEAK)

    @app.post("/voice/turn")
    def voice_turn(
        body: dict[str, Any],
        authorization: str | None = Header(default=None),
    ) -> StreamingResponse:
        actor(authorization)
        transcript = str(body.get("transcript", "")).strip()
        raw_history = body.get("history")
        history = raw_history if isinstance(raw_history, list) else []
        chat = getattr(app.state, "live_chat", None)

        def chunks() -> Iterator[str]:
            for event in live_events(app.state.catalog, transcript, chat, history):
                yield json.dumps(event) + "\n"

        return StreamingResponse(chunks(), media_type="application/x-ndjson")

    @app.get("/admin/traces", response_class=HTMLResponse)
    def list_traces(authorization: str | None = Header(default=None)) -> str:
        _need(actor(authorization), _READ_CLAIMS)
        rows = "".join(
            f"<li><a href='/admin/traces/{html.escape(item['id'])}'>"
            f"{html.escape(item['id'])}</a></li>"
            for item in app.state.traces.values()
        )
        return _page("Traces", f"<ul>{rows}</ul>")

    @app.get("/admin/traces/{trace_id}", response_class=HTMLResponse)
    def trace_detail(trace_id: str, authorization: str | None = Header(default=None)) -> str:
        _need(actor(authorization), _READ_CLAIMS)
        item = app.state.traces.get(trace_id)
        if item is None:
            raise HTTPException(status_code=404, detail="missing")
        shown = _shown_trace(app, item)
        return _page(
            "Trace",
            f"<pre>{html.escape(shown)}</pre>"
            f"<p><a href='/admin/traces/{html.escape(trace_id)}/replay'>Replay</a></p>",
        )

    @app.get("/admin/traces/{trace_id}/replay", response_class=HTMLResponse)
    def trace_replay(trace_id: str, authorization: str | None = Header(default=None)) -> str:
        _need(actor(authorization), _READ_CLAIMS)
        item = app.state.traces.get(trace_id)
        if item is None:
            raise HTTPException(status_code=404, detail="missing")
        replay = app.state.replay
        outcome = replay(app.state.catalog, item)
        return _page("Replay", f"<pre>{html.escape(str(outcome))}</pre>")

    @app.get("/v1/traces/{trace_id}")
    def trace_json(
        trace_id: str, authorization: str | None = Header(default=None)
    ) -> dict[str, Any]:
        _need(actor(authorization), _READ_CLAIMS)
        item = app.state.traces.get(trace_id)
        if item is None:
            raise HTTPException(status_code=404, detail="missing")
        return {"trace_id": trace_id, "messages": _shown_trace(app, item)}

    @app.get("/admin/claims", response_class=HTMLResponse)
    def claims(authorization: str | None = Header(default=None)) -> str:
        _need(actor(authorization), _READ_CLAIMS)
        rows = "".join(
            f"<tr><td>{html.escape(str(row['id']))}</td><td>{html.escape(str(row['status']))}</td></tr>"
            for row in app.state.catalog.claims.values()
        )
        return _page("Claims", f"<table>{rows}</table>")

    @app.get("/admin/claims/{claim_id}", response_class=HTMLResponse)
    def claim_detail(claim_id: str, authorization: str | None = Header(default=None)) -> str:
        _need(actor(authorization), _READ_CLAIMS)
        row = app.state.catalog.claims.get(claim_id)
        if row is None:
            raise HTTPException(status_code=404, detail="missing")
        decision = app.state.decisions.get(claim_id, {})
        citations = "".join(
            f"<a href='#page-{item['page']}'>clause {html.escape(str(item['clause_id']))}</a>"
            for item in decision.get("citations", [])
        )
        phone = ""
        customer_id = str(row.get("customer_id", ""))
        customer = app.state.catalog.customers.get(customer_id)
        if customer is not None:
            phone = app.state.vault.mask(str(customer["phone"]))
        body = (
            f"<p>{html.escape(claim_id)}</p><p>{phone}</p><p>{citations}</p>"
            f"<p>trace:{html.escape(str(decision.get('trace_id', '')))}</p>"
        )
        return _page("Claim", body)

    @app.get("/admin/documents", response_class=HTMLResponse)
    def documents(authorization: str | None = Header(default=None)) -> str:
        _need(actor(authorization), _ADMIN | _AUDIT_READ)
        rows = "".join(
            "<li>"
            + html.escape(item.document_id)
            + " "
            + html.escape(item.version)
            + " "
            + html.escape(item.status)
            + "</li>"
            for item in app.state.library.versions.values()
        )
        return _page("Documents", f"<ul>{rows}</ul>")

    @app.post("/admin/documents")
    async def upload(
        request: Request,
        authorization: str | None = Header(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _need(actor(authorization), _ADMIN)
        csrf_ok(x_csrf_token)
        form = await request.form()
        upload_file = form["file"]
        if not isinstance(upload_file, UploadFile):
            raise HTTPException(status_code=400, detail="file required")
        data = await upload_file.read()
        sidecar = {
            "document_id": str(form["document_id"]),
            "version": str(form["version"]),
            "policy_id": str(form["policy_id"]),
            "effective_from": str(form["effective_from"]),
            "effective_to": str(form["effective_to"]),
            "pdf_class": "digital",
        }
        item = CorpusFile(sidecar["document_id"], "digital", False, data, sidecar)
        try:
            version = app.state.library.upload(item)
        except Rejected as exc:
            raise HTTPException(status_code=400, detail="rejected") from exc
        app.state.audit.append(
            actor="admin",
            action="upload",
            now=_now(),
            after={"document_id": version.document_id, "flags": version.flags},
        )
        return {"document_id": version.document_id, "flags": version.flags, "stored_as": "library"}

    @app.get("/admin/documents/{document_id}/ingestion")
    def ingestion(
        document_id: str, authorization: str | None = Header(default=None)
    ) -> dict[str, Any]:
        _need(actor(authorization), _ADMIN | _AUDIT_READ)
        version = _latest(app, document_id)
        return {"status": version.status, "pages": version.parsed["pages"], "flags": version.flags}

    @app.post("/admin/documents/{document_id}/review")
    def review(
        document_id: str,
        body: dict[str, Any],
        authorization: str | None = Header(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _need(actor(authorization), _ADMIN)
        csrf_ok(x_csrf_token)
        version = _latest(app, document_id)
        before = version.status
        app.state.library.review(document_id, version.version, str(body["decision"]))
        app.state.audit.append(
            actor="admin",
            action="review",
            now=_now(),
            before={"status": before},
            after={"status": version.status, "approved": version.approved},
        )
        return {"approved": version.approved}

    @app.post("/admin/documents/{document_id}/sandbox-query")
    def sandbox(
        document_id: str,
        body: dict[str, str],
        authorization: str | None = Header(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _need(actor(authorization), _ADMIN)
        csrf_ok(x_csrf_token)
        version = _latest(app, document_id)
        if version.status == "published":
            raise HTTPException(status_code=409, detail="sandbox is for a draft")
        rows = [
            {
                "tenant_id": "ten_01",
                "policy_id": version.policy_id,
                "document_id": version.document_id,
                "version": version.version,
                "clause_id": clause["id"],
                "page": clause["page"],
                "text": clause["text"],
                "effective_start": version.effective_from,
                "effective_end": version.effective_to,
            }
            for clause in version.parsed["clauses"]
        ]
        return answer(
            ChunkIndex(rows), "ten_01", version.policy_id, body["question"], body["on_date"]
        )

    @app.post("/admin/documents/{document_id}/publish")
    def publish(
        document_id: str,
        authorization: str | None = Header(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> dict[str, str]:
        return _lifecycle(app, actor(authorization), x_csrf_token, document_id, "publish")

    @app.post("/admin/documents/{document_id}/retire")
    def retire(
        document_id: str,
        authorization: str | None = Header(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> dict[str, str]:
        return _lifecycle(app, actor(authorization), x_csrf_token, document_id, "retire")

    @app.post("/admin/documents/{document_id}/rollback")
    def rollback(
        document_id: str,
        authorization: str | None = Header(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> dict[str, str]:
        return _lifecycle(app, actor(authorization), x_csrf_token, document_id, "rollback")

    @app.get("/admin/metrics/summary")
    def metrics(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _need(actor(authorization), _METRICS)
        counts: dict[str, int] = {}
        for row in app.state.catalog.claims.values():
            status = str(row["status"])
            counts[status] = counts.get(status, 0) + 1
        return {"claims_by_status": counts, "pending_approvals": 0, "shadow_cost_per_claim": 0}

    @app.get("/admin/audit")
    def audit_page(
        authorization: str | None = Header(default=None),
        actor_filter: str | None = None,
        claim_id: str | None = None,
    ) -> dict[str, Any]:
        _need(actor(authorization), _AUDIT_READ)
        return {"rows": app.state.audit.search(actor=actor_filter, claim_id=claim_id)}

    @app.post("/admin/unmask")
    def unmask(
        body: dict[str, str],
        authorization: str | None = Header(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> dict[str, str]:
        role = actor(authorization)
        _need(role, _UNMASK)
        csrf_ok(x_csrf_token)
        value = app.state.vault.reveal(
            body["token"], reason=body["reason"], actor=role, audit=app.state.audit
        )
        return {"value": value}

    return app


def _lifecycle(
    app: FastAPI, role: str, csrf: str | None, document_id: str, action: str
) -> dict[str, str]:
    _need(role, _ADMIN)
    if csrf != app.state.csrf:
        raise HTTPException(status_code=403, detail="csrf")
    version = _latest(app, document_id)
    before = version.status
    cache = SemanticCache()
    if action == "publish":
        app.state.library.publish(document_id, version.version, cache)
    elif action == "retire":
        app.state.library.retire(document_id, version.version)
    else:
        app.state.library.rollback(document_id, version.version, cache)
    app.state.audit.append(
        actor=role,
        action=action,
        now=_now(),
        before={"status": before},
        after={"status": version.status},
    )
    return {"status": version.status}


def _latest(app: FastAPI, document_id: str) -> Any:
    found = [
        item for item in app.state.library.versions.values() if item.document_id == document_id
    ]
    if not found:
        raise HTTPException(status_code=404, detail="missing")
    return found[-1]


def _need(role: str, allowed: set[str]) -> None:
    if role not in allowed:
        raise HTTPException(status_code=403, detail="forbidden")


def _fail(app: FastAPI, key: str) -> NoReturn:
    app.state.failures[key] = app.state.failures.get(key, 0) + 1
    if app.state.failures[key] >= 5:
        raise HTTPException(status_code=429, detail="throttled")
    raise HTTPException(status_code=401, detail="token required")


_PAGES = Environment(autoescape=True)


def _page(title: str, body: str) -> str:
    nav = (
        "<p><a href='/admin/claims'>Claims</a> "
        "<a href='/admin/traces'>Traces</a> "
        "<a href='/admin/documents'>Documents</a> "
        "<a href='/admin/audit'>Audit</a> "
        "<a href='/admin/metrics/summary'>Numbers</a></p>"
    )
    template = _PAGES.from_string(
        "<!doctype html><html><body><h1>{{ title }}</h1>"
        "{{ nav | safe }}{{ body | safe }}</body></html>"
    )
    return str(template.render(title=title, nav=nav, body=body))


def _now() -> datetime:
    return datetime(2026, 1, 1)


def _shown_trace(app: FastAPI, item: dict[str, Any]) -> str:
    return cast(str, app.state.vault.mask(str(item.get("messages", []))))


def _unavailable_replay(catalog: Catalog, item: dict[str, Any]) -> dict[str, Any]:
    return {"error": "replay is not configured"}


_SPEAK = """
<style>
#call { font-size: 1.3rem; padding: 0.8rem 1.6rem; border-radius: 999px; }
#send { font-size: 1.1rem; padding: 0.7rem 1.2rem; margin-left: 0.5rem; }
#log { list-style: none; padding: 0; max-width: 40rem; }
#log li { margin: 0.35rem 0; }
</style>
<p>Sign in first. Start a call to use the microphone, or keep typing in the box.
Text replies stay on the page and are not spoken. Each line shows the steps.</p>
<textarea id="said" rows="3" cols="60">what is the status of clm_000001</textarea>
<p><button type="button" id="call">Start call</button>
<button type="button" id="send">Send text</button></p>
<ul id="log"></ul>
<script>
const said = document.getElementById("said");
const log = document.getElementById("log");
const history = [];
let busy = false;
function add(text) {
  const item = document.createElement("li");
  item.textContent = text;
  log.appendChild(item);
  item.scrollIntoView({block: "nearest"});
}
function say(text) {
  if (!window.speechSynthesis) { return; }
  window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
}
async function run(transcript, aloud) {
  const text = transcript.trim();
  if (!text || busy) { return; }
  busy = true;
  add("You: " + text);
  if (aloud) {
    add("Agent: Let me pull that up.");
    say("Let me pull that up.");
  }
  const response = await fetch("/voice/turn", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({transcript: text, history: history})
  });
  if (!response.ok || !response.body) {
    add("Sign in on the home page, then come back.");
    busy = false;
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let spoken = [];
  while (true) {
    const chunk = await reader.read();
    if (chunk.done) { break; }
    buffer += decoder.decode(chunk.value, {stream: true});
    const lines = buffer.split("\\n");
    buffer = lines.pop();
    for (const line of lines) {
      if (!line) { continue; }
      const event = JSON.parse(line);
      if (event.type === "step") { add(event.text); }
      if (event.type === "done") {
        add("Provider: " + event.provider);
        spoken = event.spoken;
        for (const sentence of event.spoken) {
          add("Agent: " + sentence);
          if (aloud) { say(sentence); }
        }
      }
    }
  }
  history.push({role: "user", content: text});
  history.push({role: "assistant", content: spoken.join(" ")});
  if (!aloud) { said.value = ""; }
  busy = false;
}
document.getElementById("send").onclick = () => { run(said.value, false); };
said.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    run(said.value, false);
  }
});
document.getElementById("call").onclick = () => {
  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Speech) { run(said.value, true); return; }
  const rec = new Speech();
  rec.lang = "en-US";
  rec.onresult = (event) => { run(event.results[0][0].transcript, true); };
  rec.onerror = () => { run(said.value, true); };
  rec.start();
};
</script>
"""
