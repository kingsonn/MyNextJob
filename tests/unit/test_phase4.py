"""Guardrails, admin roles, OCR, graph load, and crash recovery."""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from io import BytesIO

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from tests.support import loss_catalog

from services.admin.app import create_app, role_tokens
from services.catalog.store import Catalog
from services.contracts.envelope import ScopedToken
from services.contracts.provider import ScriptedProvider
from services.gateway.idempotency import MemoryIdempotency
from services.gateway.keys import request_hash
from services.guardrails.audit import AuditLog
from services.guardrails.pii import Vault
from services.guardrails.redteam import COUNTS, build_cases, run_suite
from services.guardrails.stack import check_output, check_plan, run_check
from services.ingestion.corpus import build_corpus
from services.ingestion.ocr import degrade, pdf_with_bitmap, read_pdf, recognize, render
from services.ingestion.pipeline import parse_pdf, word_error_rate
from services.knowledge.loader import RecordingSession, load_graph
from services.mcp.dispatch import call_tool
from services.mcp.payments_server.tools import adjuster_token, ledger_for
from services.orchestrator.graph import build_graph, freeze_state, initial_state

NOW = datetime(2026, 1, 1)
MESSAGE = "Please look at loss_outside_window for clm_000001 and tell me the outcome."


def _headers(role: str, *, csrf: bool = False) -> dict[str, str]:
    token = next(value for value, name in role_tokens().items() if name == role)
    headers = {"Authorization": "Bearer " + token}
    if csrf:
        headers["X-CSRF-Token"] = "csrf-phase4"
    return headers


def _admin_catalog() -> Catalog:
    return Catalog(
        {
            "customers": [
                {
                    "id": "cus_000001",
                    "tenant_id": "ten_01",
                    "name": "Ada Example",
                    "phone": "+1-555-0101",
                    "email": "ada@example.com",
                }
            ],
            "claims": [
                {
                    "id": "clm_000001",
                    "tenant_id": "ten_01",
                    "policy_id": "pol_000001",
                    "customer_id": "cus_000001",
                    "status": "submitted",
                    "loss_date": "2024-01-02",
                    "type": "collision",
                    "amount": 100,
                    "adjuster_id": "adj_01",
                    "provider_id": None,
                    "portal_note": None,
                    "submission_key": "sub",
                }
            ],
        }
    )


def test_guardrails_block_actions_and_fail_closed() -> None:
    assert check_plan("coverage", "payments.execute_payout").blocked is True
    assert check_output("the loss is covered", []).blocked is True
    assert check_output("the loss is covered", ["clause-1"]).blocked is False
    assert check_output("I guarantee payment", ["clause-1"]).blocked is True

    def broken() -> None:
        raise RuntimeError("checker down")

    financial = run_check("financial", broken)  # type: ignore[arg-type]
    harmless = run_check("read_only", broken)  # type: ignore[arg-type]
    assert financial.reason == "fail_closed"
    assert harmless.reason == "fail_open"
    vault = Vault()
    audit = AuditLog()
    masked = vault.mask("Call +1-555-0101 or ada@example.com")
    assert "+1-555-0101" not in masked and "@example.com" not in masked
    phone = vault.mask("+1-555-0199")
    assert (
        vault.reveal(phone, reason="customer asked", actor="adjuster", audit=audit) == "+1-555-0199"
    )
    assert audit.rows[0]["action"] == "unmask"
    try:
        vault.reveal("[phone:1]", reason="  ", actor="adjuster", audit=audit)
    except ValueError:
        return
    raise AssertionError("unmask without a reason was allowed")


def test_red_team_rates_and_dataset_counts() -> None:
    cases = build_cases()
    assert {name: sum(case["attack_class"] == name for case in cases) for name in COUNTS} == COUNTS
    from services.paths import repo_root

    stored = json.loads(
        (repo_root() / "data" / "redteam" / "cases.json").read_text(encoding="utf-8")
    )
    assert stored == cases
    report = run_suite(loss_catalog())
    assert report["block_rate"] >= 0.9
    assert report["false_positive_rate"] < 0.03
    assert report["by_class"]["direct"]["misses"]
    assert report["by_class"]["document"]["misses"]


def test_admin_roles_upload_sandbox_and_audit() -> None:
    catalog = _admin_catalog()
    app = create_app(catalog)
    client = TestClient(app)
    assert client.get("/admin/claims").status_code == 401
    assert client.get("/admin/claims", headers=_headers("engineer")).status_code == 200
    detail = client.get("/admin/claims/clm_000001", headers=_headers("auditor"))
    assert detail.status_code == 200
    assert "+1-555-0101" not in detail.text
    assert "[phone:" in detail.text
    assert client.post("/admin/documents", headers=_headers("adjuster")).status_code == 403
    assert client.get("/admin/audit", headers=_headers("engineer")).status_code == 403
    assert (
        client.get("/admin/metrics/summary", headers=_headers("admin")).json()["claims_by_status"][
            "submitted"
        ]
        == 1
    )
    for _ in range(5):
        denied = client.get("/admin/claims", headers={"Authorization": "Bearer wrong"})
    assert denied.status_code == 429

    sample = next(item for item in build_corpus() if item.document_id == "doc_digital_0000")
    hostile = next(
        item for item in build_corpus() if item.pdf_class == "hostile" and not item.holdout
    )
    rejected = client.post(
        "/admin/documents",
        headers=_headers("admin", csrf=True),
        data=_meta("doc_bad", "v1", "pol_bad"),
        files={"file": ("note.txt", b"not a pdf", "text/plain")},
    )
    assert rejected.status_code == 400
    missing_csrf = client.post(
        "/admin/documents",
        headers=_headers("admin"),
        data=_meta(sample.document_id, "v1", "pol_p3_0000"),
        files={"file": ("policy.pdf", sample.pdf, "application/pdf")},
    )
    assert missing_csrf.status_code == 403
    uploaded = client.post(
        "/admin/documents",
        headers=_headers("admin", csrf=True),
        data=_meta(sample.document_id, "v1", "pol_p3_0000"),
        files={"file": ("policy.pdf", sample.pdf, "application/pdf")},
    )
    assert uploaded.status_code == 200
    assert "pdf" not in uploaded.json()
    progress = client.get(
        f"/admin/documents/{sample.document_id}/ingestion", headers=_headers("admin")
    )
    assert progress.json()["pages"]
    hostile_upload = client.post(
        "/admin/documents",
        headers=_headers("admin", csrf=True),
        data=_meta(hostile.document_id, "v1", str(hostile.sidecar["policy_id"])),
        files={"file": ("hostile.pdf", hostile.pdf, "application/pdf")},
    )
    assert "hostile_instruction" in hostile_upload.json()["flags"]
    sandbox = client.post(
        f"/admin/documents/{sample.document_id}/sandbox-query",
        headers=_headers("admin", csrf=True),
        json={"question": "collision insured", "on_date": "2023-06-01"},
    )
    assert sandbox.status_code == 200 and sandbox.json()["escalated"] is False
    assert (
        client.post(
            f"/admin/documents/{sample.document_id}/publish",
            headers=_headers("auditor", csrf=True),
        ).status_code
        == 403
    )
    client.post(
        f"/admin/documents/{sample.document_id}/review",
        headers=_headers("admin", csrf=True),
        json={"decision": "approve"},
    )
    published = client.post(
        f"/admin/documents/{sample.document_id}/publish",
        headers=_headers("admin", csrf=True),
    )
    assert published.json()["status"] == "published"
    live = app.state.library.active("pol_p3_0000", "2023-06-01")
    assert live is not None and live.status == "published"
    revised = client.post(
        "/admin/documents",
        headers=_headers("admin", csrf=True),
        data=_meta("doc_digital_0000b", "v2", "pol_p3_0000"),
        files={"file": ("policy.pdf", sample.pdf + b"\n% v2\n", "application/pdf")},
    )
    assert revised.status_code == 200
    client.post(
        "/admin/documents/doc_digital_0000b/review",
        headers=_headers("admin", csrf=True),
        json={"decision": "approve"},
    )
    client.post("/admin/documents/doc_digital_0000b/publish", headers=_headers("admin", csrf=True))
    rolled = client.post(
        "/admin/documents/doc_digital_0000b/rollback", headers=_headers("admin", csrf=True)
    )
    assert rolled.status_code == 200
    restored = app.state.library.active("pol_p3_0000", "2023-06-01")
    assert restored is not None and restored.version == "v1"
    actions = [
        row["action"]
        for row in client.get("/admin/audit", headers=_headers("auditor")).json()["rows"]
    ]
    assert "publish" in actions and "rollback" in actions
    assert client.put("/admin/audit", headers=_headers("admin")).status_code == 405
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("synthetic")
    buffer = BytesIO()
    writer.write(buffer)
    encrypted = client.post(
        "/admin/documents",
        headers=_headers("admin", csrf=True),
        data=_meta("doc_locked", "v1", "pol_locked"),
        files={"file": ("locked.pdf", buffer.getvalue(), "application/pdf")},
    )
    assert encrypted.status_code == 400


def test_ocr_reports_each_degradation_and_reads_a_clean_page() -> None:
    rows = render("CLAUSE 1")
    parsed = parse_pdf(pdf_with_bitmap(rows), use_ocr=True)
    assert parsed["text"].strip() == "CLAUSE 1"
    assert parsed["pages"][0]["confidence"] == 1.0
    rates = {
        level: word_error_rate("CLAUSE 1", recognize(degrade(rows, level, 3))[0])
        for level in ("skew", "noise", "low_resolution")
    }
    assert set(rates) == {"skew", "noise", "low_resolution"}
    assert rates["skew"] > 0
    assert read_pdf(pdf_with_bitmap(rows))[0] == "CLAUSE 1"


def test_graph_load_keeps_values_in_parameters() -> None:
    session = RecordingSession()
    tables = {
        "customers": [{"id": "cus_000001", "tenant_id": "ten_01", "region": "us-east"}],
        "policies": [
            {
                "id": "pol_000001",
                "tenant_id": "ten_01",
                "customer_id": "cus_000001",
                "status": "active",
            }
        ],
        "endorsements": [{"id": "end_000001", "tenant_id": "ten_01", "policy_id": "pol_000001"}],
    }
    load_graph(session, tables)
    assert session.calls
    for query, parameters in session.calls:
        assert "cus_000001" not in query
        assert "pol_000001" not in query
        assert parameters
    assert any(parameters.get("id") == "end_000001" for _, parameters in session.calls)


def test_fifty_crash_trials_leave_one_payout() -> None:
    rng = random.Random(20261122)
    for trial in range(50):
        machine = MemoryIdempotency()
        writes = {"n": 0}

        def effect(box: dict[str, int] = writes) -> dict[str, str]:
            box["n"] += 1
            return {"payment_id": "pay"}

        body = request_hash({"trial": trial})
        mode = rng.randrange(3)
        if mode == 0:
            machine.crash_after_effect(
                "ten_01", "k", body, NOW, timedelta(seconds=30), {"payment_id": "pay"}
            )
            writes["n"] = 1
        elif mode == 1:
            machine.hold("ten_01", "k", body, NOW, timedelta(seconds=1))
        else:
            machine.execute("ten_01", "k", body, NOW, timedelta(seconds=30), effect)
        machine.execute(
            "ten_01", "k", body, NOW + timedelta(seconds=5), timedelta(seconds=30), effect
        )
        assert writes["n"] == 1
    graph = build_graph(loss_catalog(), ScriptedProvider(), interrupt_before=["finish"])
    for trial in range(50):
        config = {"configurable": {"thread_id": f"crash-{trial}"}}
        paused = freeze_state(graph.invoke(initial_state(MESSAGE, f"crash-{trial}"), config))
        resumed = freeze_state(graph.invoke(None, config))
        assert resumed["step_count"] > paused["step_count"]


def test_unapproved_payout_still_writes_nothing() -> None:
    catalog = Catalog(
        {
            "claims": [
                {
                    "id": "clm_000191",
                    "tenant_id": "ten_01",
                    "policy_id": "pol_000191",
                    "loss_date": "2023-05-01",
                    "type": "collision",
                    "amount": 800000,
                    "status": "submitted",
                    "adjuster_id": "adj_02",
                    "provider_id": None,
                    "portal_note": None,
                    "submission_key": "sub",
                }
            ],
            "adjusters": [
                {
                    "id": "adj_02",
                    "tenant_id": "ten_01",
                    "name": "Synthetic",
                    "authority_limit": 500000,
                }
            ],
        }
    )
    token = ScopedToken(
        tenant_id="ten_01",
        task="payments",
        allowed_tools=["payments.execute_payout"],
        trace_id="bypass",
    )
    refused = call_tool(
        catalog,
        token,
        "payments.execute_payout",
        {"claim_id": "clm_000191", "amount": 800000, "idempotency_key": "bypass"},
    )
    assert refused.error is not None and refused.error.code == "approval_required"
    assert ledger_for(catalog).writes == 0
    assert adjuster_token()


def _meta(document_id: str, version: str, policy_id: str) -> dict[str, str]:
    return {
        "document_id": document_id,
        "version": version,
        "policy_id": policy_id,
        "effective_from": "2023-01-01",
        "effective_to": "2024-01-01",
    }
