"""Load versioned local defaults without printing them."""

from __future__ import annotations

import os

from generator.paths import repo_root


def load_local_env() -> None:
    path = repo_root() / "deploy" / "env.example"
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)
