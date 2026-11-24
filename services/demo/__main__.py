"""Start the local demo. Live model keys are read from .env and never printed."""

from __future__ import annotations

import os

import uvicorn

from generator.build import generate
from generator.config import load_config
from services.admin.app import create_app
from services.catalog.load import catalog_from_dataset
from services.demo.traces import record_trace, replay_trace
from services.paths import repo_root


def _load_env() -> None:
    path = repo_root() / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"'))


def main() -> None:
    _load_env()
    catalog = catalog_from_dataset(generate(load_config()))
    trace = record_trace(catalog)
    app = create_app(catalog, traces={trace["id"]: trace})
    app.state.replay = replay_trace
    uvicorn.run(app, host="127.0.0.1", port=8080)


if __name__ == "__main__":
    main()
