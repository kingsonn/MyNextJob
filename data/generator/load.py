"""Load a generated dataset into Postgres. Not imported by tests."""

from __future__ import annotations

import os
from datetime import date, datetime

from alembic import command
from alembic.config import Config
from sqlalchemy import Table, create_engine, insert, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError

from db.tables import (
    adjusters,
    claims,
    coverages,
    customers,
    endorsements,
    faq_pages,
    idempotency_keys,
    interactions,
    metadata,
    payments,
    planted_scenarios,
    policies,
    policy_documents,
    providers,
    tenants,
)
from generator.dataset import Dataset
from generator.localenv import load_local_env
from generator.paths import repo_root

_DATE_COLUMNS = {
    "customers": ("dob",),
    "policies": ("start_date", "end_date"),
    "endorsements": ("effective_date",),
    "claims": ("loss_date",),
    "payments": ("paid_on",),
    "interactions": ("occurred_on",),
}
_TIMESTAMP_COLUMNS = {"idempotency_keys": ("created_at", "updated_at", "lock_expires_at")}


def load_postgres(dataset: Dataset) -> None:
    load_local_env()
    url = os.environ.get("CLAIMPILOT_DATABASE_URL")
    if not url:
        raise SystemExit("CLAIMPILOT_DATABASE_URL is not set. See deploy/env.example.")
    _upgrade(url)
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            _replace(connection, dataset)
    except OperationalError:
        raise SystemExit(
            "Postgres is not accepting connections. Start the core stack with make up, "
            "then run make seed."
        ) from None
    finally:
        engine.dispose()


def _upgrade(url: str) -> None:
    config = Config(str(repo_root() / "db" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    try:
        command.upgrade(config, "head")
    except OperationalError:
        raise SystemExit(
            "Postgres is not accepting connections. Start the core stack with make up, "
            "then run make seed."
        ) from None


def _replace(connection: Connection, dataset: Dataset) -> None:
    table_names = ", ".join(table.name for table in reversed(metadata.sorted_tables))
    connection.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))
    batches: tuple[tuple[Table, list[dict[str, object]]], ...] = (
        (tenants, dataset.tenants),
        (adjusters, dataset.adjusters),
        (providers, dataset.providers),
        (customers, dataset.customers),
        (policies, dataset.policies),
        (coverages, dataset.coverages),
        (endorsements, dataset.endorsements),
        (claims, dataset.claims),
        (payments, dataset.payments),
        (interactions, dataset.interactions),
        (policy_documents, dataset.policy_documents),
        (faq_pages, dataset.faq_pages),
        (planted_scenarios, dataset.planted_scenarios),
        (idempotency_keys, dataset.idempotency_keys),
    )
    for table, rows in batches:
        prepared = [_prepare(table.name, row) for row in rows]
        for start in range(0, len(prepared), 2000):
            connection.execute(insert(table), prepared[start : start + 2000])


def _prepare(table_name: str, row: dict[str, object]) -> dict[str, object]:
    prepared = dict(row)
    for column in _DATE_COLUMNS.get(table_name, ()):
        value = prepared[column]
        if isinstance(value, str):
            prepared[column] = date.fromisoformat(value)
    for column in _TIMESTAMP_COLUMNS.get(table_name, ()):
        value = prepared[column]
        if isinstance(value, str):
            prepared[column] = datetime.fromisoformat(value)
    return prepared
