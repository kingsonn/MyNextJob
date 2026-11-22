"""CRM MCP tools. Writes require an idempotency key."""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, ConfigDict, model_validator

from services.catalog.store import Catalog
from services.contracts.envelope import ScopedToken, ToolEnvelope, error_envelope, ok_envelope
from services.mcp.policy_server.tools import EntityQuery
from services.mcp.spec import ToolSpec


class NoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str
    body: str
    idempotency_key: str


class ContactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str
    idempotency_key: str
    phone: str | None = None
    email: str | None = None
    address: str | None = None

    @model_validator(mode="after")
    def one_field(self) -> ContactInput:
        if self.phone is None and self.email is None and self.address is None:
            raise ValueError("contact update needs a field")
        return self


def _missing(tool: str, token: ScopedToken) -> ToolEnvelope:
    return error_envelope(tool, token.trace_id, "not_found", "No matching record.", retryable=False)


def _find(catalog: Catalog, token: ScopedToken, arguments: BaseModel) -> ToolEnvelope:
    query = cast(EntityQuery, arguments)
    data = catalog.find_customer(token.tenant_id, query.entity_id)
    if data is None:
        return _missing("crm.find_customer", token)
    return ok_envelope("crm.find_customer", token.trace_id, data)


def _verify(catalog: Catalog, token: ScopedToken, arguments: BaseModel) -> ToolEnvelope:
    query = cast(EntityQuery, arguments)
    data = catalog.verify_identity(token.tenant_id, query.entity_id)
    if data is None:
        return _missing("crm.verify_identity", token)
    return ok_envelope("crm.verify_identity", token.trace_id, data)


def _interactions(catalog: Catalog, token: ScopedToken, arguments: BaseModel) -> ToolEnvelope:
    query = cast(EntityQuery, arguments)
    data = catalog.list_interactions(token.tenant_id, query.entity_id)
    if data is None:
        return _missing("crm.list_interactions", token)
    return ok_envelope("crm.list_interactions", token.trace_id, data)


def _note(catalog: Catalog, token: ScopedToken, arguments: BaseModel) -> ToolEnvelope:
    query = cast(NoteInput, arguments)
    result = catalog.add_note(token.tenant_id, query.customer_id, query.body, query.idempotency_key)
    return _write_result("crm.add_note", token, query.idempotency_key, result)


def _contact(catalog: Catalog, token: ScopedToken, arguments: BaseModel) -> ToolEnvelope:
    query = cast(ContactInput, arguments)
    result = catalog.update_contact(
        token.tenant_id,
        query.customer_id,
        query.idempotency_key,
        phone=query.phone,
        email=query.email,
        address=query.address,
    )
    return _write_result("crm.update_contact", token, query.idempotency_key, result)


def _write_result(
    tool: str,
    token: ScopedToken,
    key: str,
    result: tuple[dict[str, Any], bool] | str,
) -> ToolEnvelope:
    if result == "missing":
        return _missing(tool, token)
    if result == "conflict":
        return error_envelope(
            tool,
            token.trace_id,
            "idempotency_conflict",
            "This idempotency key was already used for a different request.",
            retryable=False,
            key=key,
        )
    if isinstance(result, str):
        return error_envelope(
            tool, token.trace_id, "validation_error", result, retryable=False, key=key
        )
    data, replayed = result
    return ok_envelope(tool, token.trace_id, data, key=key, replayed=replayed)


CRM_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "crm.find_customer",
        "Read the CRM customer. The CRM phone wins over a conflicting conversation.",
        "read_only",
        "not_applicable",
        EntityQuery,
        _find,
        "crm",
    ),
    ToolSpec(
        "crm.verify_identity",
        "Read whether the customer's identity is verified.",
        "read_only",
        "not_applicable",
        EntityQuery,
        _verify,
        "crm",
    ),
    ToolSpec(
        "crm.list_interactions",
        "Count the customer's recorded interactions.",
        "read_only",
        "not_applicable",
        EntityQuery,
        _interactions,
        "crm",
    ),
    ToolSpec(
        "crm.add_note",
        "Add a CRM note. Requires an idempotency key.",
        "reversible_write",
        "required",
        NoteInput,
        _note,
        "crm",
    ),
    ToolSpec(
        "crm.update_contact",
        "Update a phone, email, or address. Requires an idempotency key.",
        "reversible_write",
        "required",
        ContactInput,
        _contact,
        "crm",
    ),
)
