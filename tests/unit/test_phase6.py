"""Phase 6 trace page and the offline walkthrough. No network."""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.support import loss_catalog

from services.admin.app import create_app, role_tokens
from services.demo.rehearse import rehearse
from services.demo.traces import record_trace, replay_trace


def _token(role: str) -> str:
    for token, name in role_tokens().items():
        if name == role:
            return token
    raise RuntimeError("missing role token")


def test_walkthrough_beats_pass() -> None:
    report = rehearse()
    assert report["voice"] is True
    assert report["trace"] is True
    assert report["approval"] is True
    assert report["idempotency"] is True
    assert report["crash"] is True
    assert report["injection"] is True
    assert report["portal"] is True
    assert report["failover"] is True


def test_trace_page_masks_and_replays_without_a_model() -> None:
    catalog = loss_catalog()
    trace = record_trace(catalog)
    trace["messages"].append({"role": "tool", "content": "call +1-555-0101"})
    app = create_app(catalog, traces={trace["id"]: trace})
    app.state.replay = replay_trace
    client = TestClient(app)
    assert client.get("/admin/traces").status_code == 401
    admin = {"Authorization": "Bearer " + _token("admin")}
    page = client.get("/admin/traces/demo-trace", headers=admin)
    assert page.status_code == 200
    assert "+1-555-0101" not in page.text
    assert "[phone:" in page.text
    replayed = client.get("/admin/traces/demo-trace/replay", headers=admin)
    assert "False" in replayed.text
    missing = client.get("/v1/traces/missing", headers=admin)
    assert missing.status_code == 404
    opened = client.post("/admin/login", data={"token": _token("auditor")}, follow_redirects=False)
    assert opened.status_code == 303
    client.cookies.update(opened.cookies)
    listed = client.get("/admin/traces")
    assert listed.status_code == 200
