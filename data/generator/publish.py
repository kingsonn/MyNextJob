"""Write the reviewable answer key and the gitignored generated files."""

from __future__ import annotations

import json
from pathlib import Path

from generator.dataset import Dataset, canonical_bytes
from generator.paths import repo_root


def publish(dataset: Dataset) -> None:
    root = repo_root()
    golden_dir = root / "data" / "golden"
    golden_dir.mkdir(parents=True, exist_ok=True)
    for stale in golden_dir.glob("golden-*.json"):
        stale.unlink()
    for row in dataset.golden:
        golden_id = row["id"]
        if not isinstance(golden_id, str):
            raise TypeError("golden id is not a string")
        _write_json(golden_dir / f"{golden_id}.json", row)

    manifest_path = root / "data" / "manifest.json"
    _write_json(manifest_path, dataset.manifest())

    generated = root / "data" / "generated"
    documents = generated / "documents"
    documents.mkdir(parents=True, exist_ok=True)
    for artifact in dataset.documents:
        (documents / f"{artifact.document_id}.pdf").write_bytes(artifact.pdf_bytes)
        (documents / f"{artifact.document_id}.txt").write_text(
            artifact.text, encoding="utf-8", newline="\n"
        )
        _write_json(documents / f"{artifact.document_id}.json", artifact.sidecar)

    answer_key = generated / "answer_key"
    answer_key.mkdir(parents=True, exist_ok=True)
    lines = [canonical_bytes(row).decode("utf-8") for row in dataset.planted_scenarios]
    (answer_key / "planted.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )


def _write_json(path: Path, payload: object) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
