"""Admin routes. Role checks run on the server for every call."""

from __future__ import annotations

import html
import json
from collections.abc import Iterator
from datetime import datetime
from typing import Any, NoReturn, cast

from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from starlette.datastructures import UploadFile

from services.admin.pages import customer_page, login_page, staff_page
from services.catalog.store import Catalog
from services.gateway.agent_run import live_events
from services.gateway.cache import SemanticCache
from services.gateway.speech import transcript_from_turn
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

    @app.get("/")
    def home() -> HTMLResponse:
        return _desk()

    @app.get("/admin", response_class=HTMLResponse)
    def admin_home(authorization: str | None = Header(default=None)) -> str:
        role = _peek(authorization)
        if role is None:
            return login_page()
        return _overview(app, role)

    @app.post("/admin/login")
    def login(token: str = Form()) -> RedirectResponse:
        response = RedirectResponse("/admin", status_code=303)
        response.set_cookie("admin_session", token, httponly=True)
        return response

    @app.get("/voice")
    def voice_page() -> HTMLResponse:
        return _desk()

    @app.get("/voice/desk.js")
    def desk_script() -> Response:
        return _script("desk.js")

    @app.get("/voice/vad-worklet.js")
    def vad_script() -> Response:
        return _script("vad-worklet.js")

    @app.post("/voice/turn")
    def voice_turn(
        request: Request,
        body: dict[str, Any],
        authorization: str | None = Header(default=None),
    ) -> StreamingResponse:
        if request.cookies.get("customer_session") != "desk":
            actor(authorization)
        transcript = transcript_from_turn(body, getattr(app.state, "transcribe", None))
        raw_history = body.get("history")
        history = raw_history if isinstance(raw_history, list) else []
        chat = getattr(app.state, "live_chat", None)
        audio = isinstance(body.get("audio_wav_base64"), str) and bool(body.get("audio_wav_base64"))

        def chunks() -> Iterator[str]:
            if not transcript:
                yield json.dumps({"type": "step", "text": "No words recognised"}) + "\n"
                yield (
                    json.dumps(
                        {
                            "type": "done",
                            "spoken": ["I didn't catch that."],
                            "provider": "scripted",
                            "events": ["fast"],
                            "end_call": False,
                        }
                    )
                    + "\n"
                )
                return
            if audio:
                yield json.dumps({"type": "step", "text": "Heard: " + transcript[:180]}) + "\n"
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
        return _page("Traces", f"<h1>Traces</h1><ul>{rows}</ul>")

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
    def claims(request: Request, authorization: str | None = Header(default=None)) -> str:
        _need(actor(authorization), _READ_CLAIMS)
        query = request.query_params.get("q", "").strip().lower()
        matched = [
            row
            for row in app.state.catalog.claims.values()
            if not query
            or query in str(row["id"]).lower()
            or query in str(row.get("status", "")).lower()
            or query in str(row.get("type", "")).lower()
        ]
        shown = matched[:40]
        body_rows = "".join(
            "<tr>"
            f"<td><a href='/admin/claims/{html.escape(str(row['id']))}'>"
            f"{html.escape(str(row['id']))}</a></td>"
            f"<td>{html.escape(str(row.get('status', '')))}</td>"
            f"<td>{html.escape(str(row.get('type', '')))}</td>"
            f"<td>{html.escape(str(row.get('amount', '')))}</td>"
            f"<td>{html.escape(str(row.get('loss_date', '')))}</td>"
            f"<td>{html.escape(str(row.get('policy_id', '')))}</td>"
            "</tr>"
            for row in shown
        )
        return _page(
            "Claims",
            "<h1>Claims</h1>"
            f"<p>{len(matched)} match the filter. Showing {len(shown)}.</p>"
            "<form method='get'><label>Search "
            f"<input name='q' value='{html.escape(query)}'></label> "
            "<button>Find</button></form>"
            "<table><tr><th>Claim</th><th>Status</th><th>Type</th>"
            f"<th>Amount</th><th>Loss date</th><th>Policy</th></tr>{body_rows}</table>",
        )

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
            f"<h1>{html.escape(claim_id)}</h1>"
            "<table>"
            f"<tr><th>Status</th><td>{html.escape(str(row.get('status', '')))}</td></tr>"
            f"<tr><th>Type</th><td>{html.escape(str(row.get('type', '')))}</td></tr>"
            f"<tr><th>Amount</th><td>{html.escape(str(row.get('amount', '')))}</td></tr>"
            f"<tr><th>Loss date</th><td>{html.escape(str(row.get('loss_date', '')))}</td></tr>"
            f"<tr><th>Policy</th><td>{html.escape(str(row.get('policy_id', '')))}</td></tr>"
            f"<tr><th>Phone</th><td>{html.escape(phone)}</td></tr>"
            f"<tr><th>Citations</th><td>{citations}</td></tr>"
            f"<tr><th>Trace</th><td>{html.escape(str(decision.get('trace_id', '')))}</td></tr>"
            "</table>"
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
        form = (
            "<h2>Add a policy PDF</h2>"
            "<form class='stack' method='post' action='/admin/documents' "
            "enctype='multipart/form-data'>"
            "<input type='hidden' name='csrf' value='csrf-phase4'>"
            "<input type='hidden' name='respond' value='html'>"
            "<label>Document id <input name='document_id' required></label>"
            "<label>Version <input name='version' value='v1' required></label>"
            "<label>Policy id <input name='policy_id' required></label>"
            "<label>Effective from <input name='effective_from' value='2023-01-01'></label>"
            "<label>Effective to <input name='effective_to' value='2024-01-01'></label>"
            "<label>PDF <input type='file' name='file' accept='application/pdf' required></label>"
            "<button>Upload</button></form>"
            "<h2>Ask a draft</h2>"
            "<form class='stack' id='sandbox'>"
            "<label>Document id <input id='sandbox-id' required></label>"
            "<label>Question <input id='sandbox-q' required></label>"
            "<label>On date <input id='sandbox-date' value='2023-06-01'></label>"
            "<button type='submit'>Ask the draft</button></form>"
            "<pre id='sandbox-out'></pre>"
            "<script>"
            "document.getElementById('sandbox').onsubmit = async (event) => {"
            "event.preventDefault();"
            "const id = document.getElementById('sandbox-id').value;"
            "const response = await fetch('/admin/documents/' + id + '/sandbox-query', {"
            "method: 'POST',"
            "headers: {'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf-phase4'},"
            "body: JSON.stringify({question: document.getElementById('sandbox-q').value,"
            "on_date: document.getElementById('sandbox-date').value})});"
            "document.getElementById('sandbox-out').textContent = await response.text();"
            "};</script>"
        )
        return _page(
            "Policies",
            "<h1>Policies and documents</h1>"
            "<p>Upload, then review and publish from the API actions already on this server. "
            "The customer desk answers from the seeded book. "
            "A draft is queried here and is not live until you publish it.</p>"
            f"<ul>{rows}</ul>{form}",
        )

    @app.post("/admin/documents")
    async def upload(
        request: Request,
        authorization: str | None = Header(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> Any:
        _need(actor(authorization), _ADMIN)
        form = await request.form()
        posted = form.get("csrf")
        csrf_ok(x_csrf_token or (str(posted) if posted else None))
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
        payload = {
            "document_id": version.document_id,
            "flags": version.flags,
            "stored_as": "library",
        }
        if str(form.get("respond", "")) == "html":
            return RedirectResponse("/admin/documents", status_code=303)
        return payload

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

    @app.get("/admin/audit-log", response_class=HTMLResponse)
    def audit_log(authorization: str | None = Header(default=None)) -> str:
        _need(actor(authorization), _AUDIT_READ)
        rows = app.state.audit.search()
        body = "".join(
            "<tr>"
            f"<td>{html.escape(str(row.get('actor', '')))}</td>"
            f"<td>{html.escape(str(row.get('action', '')))}</td>"
            f"<td>{html.escape(str(row.get('at', row.get('now', ''))))}</td>"
            "</tr>"
            for row in rows
        )
        return _page(
            "Audit",
            "<h1>Audit log</h1><table><tr><th>Actor</th><th>Action</th><th>When</th></tr>"
            f"{body}</table>",
        )

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


def _script(name: str) -> Response:
    path = repo_root() / "services" / "admin" / name
    return Response(path.read_bytes(), media_type="text/javascript")


def _desk() -> HTMLResponse:
    response = HTMLResponse(customer_page())
    response.set_cookie("customer_session", "desk", httponly=True, samesite="lax")
    return response


def _peek(authorization: str | None) -> str | None:
    if authorization is None or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    return role_tokens().get(token)


def _overview(app: FastAPI, role: str) -> str:
    counts: dict[str, int] = {}
    for row in app.state.catalog.claims.values():
        status = str(row["status"])
        counts[status] = counts.get(status, 0) + 1
    cards = "".join(
        f"<div class='card'><strong>{count}</strong>{html.escape(status)}</div>"
        for status, count in sorted(counts.items())
    )
    return staff_page(
        "Overview",
        f"<h1>Overview</h1><p>Signed in as {html.escape(role)}. "
        "Numbers are the synthetic book in this process.</p>"
        f"<div class='cards'>{cards}</div>"
        "<p><a href='/admin/metrics/summary'>Raw metrics</a></p>",
    )


def _page(title: str, body: str) -> str:
    return staff_page(title, body)


def _now() -> datetime:
    return datetime(2026, 1, 1)


def _shown_trace(app: FastAPI, item: dict[str, Any]) -> str:
    return cast(str, app.state.vault.mask(str(item.get("messages", []))))


def _unavailable_replay(catalog: Catalog, item: dict[str, Any]) -> dict[str, Any]:
    return {"error": "replay is not configured"}
