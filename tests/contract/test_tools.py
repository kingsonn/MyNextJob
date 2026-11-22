"""Contract tests for the policy, CRM, and graph tools."""

from __future__ import annotations

import json

from tests.support import loss_catalog

from db.tables import crm_contact_updates, crm_notes
from services.contracts.envelope import ScopedToken
from services.knowledge.cypher import TEMPLATES
from services.mcp.dispatch import call_tool, tool_registry
from services.orchestrator.permissions import VERIFICATION_TOOLS


def _token(tenant_id: str = "ten_01") -> ScopedToken:
    names = list(tool_registry())
    return ScopedToken(
        tenant_id=tenant_id, task="contract", allowed_tools=names, trace_id="trace-contract"
    )


def test_tool_schemas_risk_and_idempotency() -> None:
    registry = tool_registry()
    assert "payments.execute" not in registry
    for name, spec in registry.items():
        schema = spec.json_schema()
        assert spec.description
        assert schema["type"] == "object"
        assert spec.risk_tier in {"read_only", "reversible_write", "financial"}
        if spec.idempotency == "required":
            assert spec.risk_tier in {"reversible_write", "financial"}
            assert "idempotency_key" in schema["required"]
        else:
            assert spec.idempotency == "not_applicable"
        assert name
    note_names = {constraint.name for constraint in crm_notes.constraints}
    contact_names = {constraint.name for constraint in crm_contact_updates.constraints}
    assert "crm_notes_tenant_idempotency_key" in note_names
    assert "crm_contact_updates_tenant_idempotency_key" in contact_names


def test_cross_tenant_matches_missing_and_bad_arguments_write_nothing() -> None:
    catalog = loss_catalog()
    foreign = call_tool(
        catalog,
        _token("ten_02"),
        "crm.find_customer",
        {"entity_id": "cus_000001"},
    )
    missing = call_tool(
        catalog,
        _token("ten_02"),
        "crm.find_customer",
        {"entity_id": "cus_missing"},
    )
    assert foreign.model_dump() == missing.model_dump()
    assert foreign.error is not None
    assert foreign.error.code == "not_found"
    assert foreign.data == {}
    invalid = call_tool(catalog, _token(), "policy.get_policy", {"entity_id": 12})
    assert invalid.error is not None
    assert invalid.error.code == "validation_error"
    denied = call_tool(
        catalog,
        ScopedToken(
            tenant_id="ten_01",
            task="verification",
            allowed_tools=VERIFICATION_TOOLS,
            trace_id="trace-contract",
        ),
        "crm.add_note",
        {"customer_id": "cus_000001", "body": "note", "idempotency_key": "note-1"},
    )
    assert denied.error is not None
    assert denied.error.code == "forbidden_tool"
    assert catalog.note_count == 0


def test_envelopes_are_untrusted_and_writes_replay_or_conflict() -> None:
    catalog = loss_catalog()
    token = _token()
    read = call_tool(
        token=token,
        catalog=catalog,
        name="policy.get_policy",
        arguments={"entity_id": "clm_000001"},
    )
    assert read.status == "ok"
    assert read.untrusted_content is True
    assert read.data["covered"] is False
    missing_key = call_tool(
        catalog,
        token,
        "crm.add_note",
        {"customer_id": "cus_000001", "body": "A synthetic note."},
    )
    assert missing_key.error is not None
    assert missing_key.error.code == "validation_error"
    assert catalog.note_count == 0
    first = call_tool(
        catalog,
        token,
        "crm.update_contact",
        {
            "customer_id": "cus_000001",
            "idempotency_key": "contact-1",
            "phone": "+1-555-0108",
        },
    )
    assert first.status == "ok"
    assert first.idempotency.replayed is False
    replay = call_tool(
        catalog,
        token,
        "crm.update_contact",
        {
            "customer_id": "cus_000001",
            "idempotency_key": "contact-1",
            "phone": "+1-555-0108",
        },
    )
    assert replay.idempotency.replayed is True
    assert catalog.contact_count == 1
    conflict = call_tool(
        catalog,
        token,
        "crm.update_contact",
        {
            "customer_id": "cus_000001",
            "idempotency_key": "contact-1",
            "phone": "+1-555-0109",
        },
    )
    assert conflict.error is not None
    assert conflict.error.code == "idempotency_conflict"
    assert catalog.customers["cus_000001"]["phone"] == "+1-555-0108"
    assert json.loads(read.model_dump_json())["untrusted_content"] is True


def test_cypher_templates_are_parameterised() -> None:
    for template in TEMPLATES.values():
        assert "$tenant_id" in template
        assert "f'" not in template
        assert 'f"' not in template
