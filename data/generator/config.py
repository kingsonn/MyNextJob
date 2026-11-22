"""Load the versioned generator config."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from generator import GENERATOR_VERSION
from generator.paths import repo_root


class Volumes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenants: int
    customers: int
    policies: int
    coverages: int
    endorsements: int
    claims: int
    payments: int
    providers: int
    adjusters: int
    interactions: int
    policy_documents: int
    faq_pages: int


class ScenarioCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loss_outside_window: int
    rider_timing: int
    duplicate_claim: int
    shared_contact_ring: int
    provider_cluster: int
    payout_above_authority: int
    conflicting_records: int
    identity_failure: int
    document_injection: int
    portal_injection: int
    ambiguous_coverage: int
    multilingual: int
    long_history: int


class GeneratorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int
    generator_version: str
    watermark: str
    injection_text: str
    adjuster_authority_limit: int
    normal_payment_max: int
    planted_payout_amount: int
    long_history_min_interactions: int
    ring_size: int
    cluster_size: int
    volumes: Volumes
    planted: ScenarioCounts
    golden_allocation: ScenarioCounts

    @model_validator(mode="after")
    def check_counts(self) -> GeneratorConfig:
        if self.generator_version != GENERATOR_VERSION:
            raise ValueError(
                f"config generator_version {self.generator_version} "
                f"does not match {GENERATOR_VERSION}"
            )
        if self.volumes.coverages != self.volumes.policies * 5:
            raise ValueError("coverages must be exactly 5 per policy")
        if self.planted_payout_amount <= self.adjuster_authority_limit:
            raise ValueError("planted payout must exceed adjuster authority")
        if self.normal_payment_max >= self.adjuster_authority_limit:
            raise ValueError("normal payments must sit under adjuster authority")
        golden_total = sum(self.golden_allocation.model_dump().values())
        if golden_total != 30:
            raise ValueError(f"golden allocation sums to {golden_total}, expected 30")
        for name, count in self.golden_allocation.model_dump().items():
            planted_count = getattr(self.planted, name)
            if not isinstance(planted_count, int) or count > planted_count:
                raise ValueError(f"golden allocation for {name} exceeds planted rows")
        return self


def load_config() -> GeneratorConfig:
    path = repo_root() / "data" / "generator" / "config.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise TypeError(f"generator config must be a mapping, got {type(loaded).__name__}")
    return GeneratorConfig.model_validate(loaded)


def config_file() -> Path:
    return repo_root() / "data" / "generator" / "config.yaml"
