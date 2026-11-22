"""Repository paths that stay stable under an editable install."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    start = Path(__file__).resolve()
    for candidate in [Path.cwd(), *start.parents]:
        if (candidate / "pyproject.toml").is_file() and (candidate / "data" / "generator").is_dir():
            return candidate
    raise RuntimeError("Could not find the ClaimPilot repository root.")
