"""Offline tests for the seeded generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from generator.build import generate
from generator.config import GeneratorConfig, load_config
from generator.dataset import Dataset
from generator.paths import repo_root
from generator.validate import hygiene_problems, integrity_problems, planted_problems


@pytest.fixture(scope="session")
def config() -> GeneratorConfig:
    return load_config()


@pytest.fixture(scope="session")
def dataset(config: GeneratorConfig) -> Dataset:
    return generate(config)


def test_same_seed_is_deterministic(dataset: Dataset, config: GeneratorConfig) -> None:
    again = generate(config)
    assert dataset.canonical() == again.canonical()
    assert [item.pdf_bytes for item in dataset.documents] == [
        item.pdf_bytes for item in again.documents
    ]
    assert dataset.golden == again.golden
    assert dataset.manifest()["checksum"] == again.manifest()["checksum"]


def test_referential_integrity(dataset: Dataset, config: GeneratorConfig) -> None:
    assert integrity_problems(dataset, config) == []


def test_planted_outcomes(dataset: Dataset, config: GeneratorConfig) -> None:
    assert planted_problems(dataset, config) == []


def test_hygiene(dataset: Dataset, config: GeneratorConfig) -> None:
    assert hygiene_problems(dataset, config) == []


def test_committed_golden_and_manifest(dataset: Dataset) -> None:
    root = repo_root()
    golden_paths = sorted((root / "data" / "golden").glob("golden-*.json"))
    assert [path.name for path in golden_paths] == [
        f"golden-{index:03d}.json" for index in range(1, 31)
    ]
    for path, row in zip(golden_paths, dataset.golden, strict=True):
        assert json.loads(path.read_text(encoding="utf-8")) == row
    manifest = json.loads((root / "data" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest == dataset.manifest()
    assert manifest["seed"] == dataset.seed


def test_repo_root_is_this_checkout() -> None:
    assert (repo_root() / "pyproject.toml").is_file()
    assert Path(repo_root() / "data" / "generator" / "config.yaml").is_file()
