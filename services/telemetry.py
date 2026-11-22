"""OpenTelemetry spans for graph nodes, model calls, and tool calls."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace


@contextmanager
def span(name: str, **attributes: str) -> Iterator[None]:
    tracer = trace.get_tracer("claimpilot")
    with tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            current.set_attribute(key, value)
        yield
