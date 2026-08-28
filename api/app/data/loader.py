"""Loads the JSON fixtures into typed models. This is the only place that
touches the filesystem — everything else works with in-memory objects."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.models import ComputeTarget, PerformanceProfile, Workload

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


@lru_cache(maxsize=1)
def load_compute_targets() -> list[ComputeTarget]:
    raw = json.loads((FIXTURES_DIR / "compute_targets.json").read_text())
    return [ComputeTarget.model_validate(item) for item in raw]


@lru_cache(maxsize=1)
def load_workloads() -> list[Workload]:
    raw = json.loads((FIXTURES_DIR / "workloads.json").read_text())
    return [Workload.model_validate(item) for item in raw]


@lru_cache(maxsize=1)
def load_performance_profiles() -> list[PerformanceProfile]:
    raw = json.loads((FIXTURES_DIR / "performance_profiles.json").read_text())
    return [PerformanceProfile.model_validate(item) for item in raw]


def get_compute_target(target_id: str) -> ComputeTarget | None:
    return next((t for t in load_compute_targets() if t.id == target_id), None)


def get_workload(workload_id: str) -> Workload | None:
    return next((w for w in load_workloads() if w.id == workload_id), None)


def get_performance_profile(workload_id: str, target_id: str) -> PerformanceProfile | None:
    return next(
        (
            p
            for p in load_performance_profiles()
            if p.workload_id == workload_id and p.target_id == target_id
        ),
        None,
    )
