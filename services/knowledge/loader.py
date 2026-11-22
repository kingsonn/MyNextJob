"""Parameterised graph load. Tests record the statements and do not open Neo4j."""

from __future__ import annotations

from typing import Any, Protocol


class GraphSession(Protocol):
    def run(self, query: str, parameters: dict[str, Any]) -> None: ...


class RecordingSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run(self, query: str, parameters: dict[str, Any]) -> None:
        self.calls.append((query, parameters))


_CUSTOMER = "MERGE (n:Customer {id: $id, tenant_id: $tenant_id}) SET n.region = $region"
_POLICY = "MERGE (n:Policy {id: $id, tenant_id: $tenant_id}) SET n.status = $status"
_HOLDS = (
    "MATCH (c:Customer {id: $customer_id, tenant_id: $tenant_id}) "
    "MATCH (p:Policy {id: $policy_id, tenant_id: $tenant_id}) MERGE (c)-[:HOLDS]->(p)"
)
_ENDORSEMENT = "MERGE (n:Endorsement {id: $id, tenant_id: $tenant_id}) SET n.policy_id = $policy_id"


def load_graph(session: GraphSession, tables: dict[str, list[dict[str, Any]]]) -> None:
    for row in tables.get("customers", []):
        session.run(
            _CUSTOMER,
            {"id": row["id"], "tenant_id": row["tenant_id"], "region": row.get("region", "")},
        )
    for row in tables.get("policies", []):
        session.run(
            _POLICY,
            {"id": row["id"], "tenant_id": row["tenant_id"], "status": row.get("status", "")},
        )
        session.run(
            _HOLDS,
            {
                "customer_id": row["customer_id"],
                "policy_id": row["id"],
                "tenant_id": row["tenant_id"],
            },
        )
    for row in tables.get("endorsements", []):
        session.run(
            _ENDORSEMENT,
            {"id": row["id"], "tenant_id": row["tenant_id"], "policy_id": row["policy_id"]},
        )
