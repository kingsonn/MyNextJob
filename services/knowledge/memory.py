"""Memory layers. Writes store facts, and the CRM wins a conflict."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from services.gateway.cache import SemanticCache

_INSTRUCTIONS = ("ignore previous", "approve the payout", "you are now", "system:")


def instruction_like(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _INSTRUCTIONS)


@dataclass
class MemoryItem:
    tenant_id: str
    customer_id: str
    layer: str
    field: str
    value: str
    source: str
    recorded_at: str
    confidence: float
    corrected: bool = False


class MemoryStore:
    def __init__(self) -> None:
        self.items: list[MemoryItem] = []

    def write(
        self,
        tenant_id: str,
        customer_id: str,
        layer: str,
        field: str,
        value: str,
        source: str,
        now: datetime,
        confidence: float,
    ) -> bool:
        if instruction_like(value):
            return False
        self.items.append(
            MemoryItem(
                tenant_id,
                customer_id,
                layer,
                field,
                value,
                source,
                now.isoformat(),
                confidence,
            )
        )
        return True

    def show(self, tenant_id: str, customer_id: str) -> list[dict[str, Any]]:
        return [
            {
                "layer": item.layer,
                "field": item.field,
                "value": item.value,
                "source": item.source,
                "recorded_at": item.recorded_at,
                "confidence": item.confidence,
                "corrected": item.corrected,
            }
            for item in self.items
            if item.tenant_id == tenant_id and item.customer_id == customer_id
        ]

    def delete(self, tenant_id: str, customer_id: str, cache: SemanticCache) -> int:
        before = len(self.items)
        self.items = [
            item
            for item in self.items
            if not (item.tenant_id == tenant_id and item.customer_id == customer_id)
        ]
        cache.purge_customer(tenant_id, customer_id)
        return before - len(self.items)

    def reconcile(self, tenant_id: str, customer_id: str, crm: dict[str, str]) -> int:
        corrected = 0
        for item in self.items:
            if item.tenant_id != tenant_id or item.customer_id != customer_id:
                continue
            crm_value = crm.get(item.field)
            if crm_value is not None and crm_value != item.value:
                item.value = crm_value
                item.source = "crm"
                item.corrected = True
                corrected += 1
        return corrected
