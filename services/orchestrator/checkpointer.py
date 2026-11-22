"""Postgres checkpointer. Tests use the in-memory saver and do not connect."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager


def postgres_conninfo(url: str) -> str:
    prefix = "postgresql+psycopg://"
    if url.startswith(prefix):
        return "postgresql://" + url[len(prefix) :]
    if url.startswith("postgresql://"):
        return url
    raise ValueError("unsupported database url")


@contextmanager
def postgres_checkpointer(url: str) -> Iterator[object]:
    """Open LangGraph's Postgres saver and create its own checkpoint tables."""

    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(postgres_conninfo(url)) as saver:
        saver.setup()
        yield saver
