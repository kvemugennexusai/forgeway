"""Gathers every PerformanceEvidence candidate available for a
(workload, target) pair — from this demo's fixtures and from any locally
saved `forgeway bench` runs (app.benchmark.store) — and selects the one
app.core.engine.evidence_selection.select_evidence says to score against.

This is the literal "connect real Forgeway PerformanceEvidence records to
the placement decision engine" seam (docs/decision-engine.md): a real
benchmark run saved by `forgeway bench` becomes a scoring candidate here
automatically, the moment its workload_id and compute_target_id match an
existing demo workload/target — no separate wiring per run, and nothing
here invents a match that isn't already exact.
"""
from __future__ import annotations

from typing import Iterable, Optional

from app.benchmark.store import list_runs
from app.core.engine.evidence_selection import select_evidence
from app.core.schemas import PerformanceEvidence
from app.data.loader import get_performance_profile


def fixture_evidence(workload_id: str, target_id: str) -> Optional[PerformanceEvidence]:
    """This demo's fixture data, wrapped as PerformanceEvidence — the same
    conversion app.core.schemas.v0_1 already offered as a standalone
    formalization; now it's also how fixture data enters the engine."""
    profile = get_performance_profile(workload_id, target_id)
    return PerformanceEvidence.from_performance_profile(profile) if profile is not None else None


def gather_evidence_candidates(
    workload_id: str,
    target_id: str,
    *,
    benchmark_runs: list[PerformanceEvidence],
) -> list[PerformanceEvidence]:
    """`benchmark_runs` is expected to be fetched once per decision (via
    app.benchmark.store.list_runs(), e.g. once per run_decision() call) and
    passed in here per target evaluated — re-reading and re-parsing every
    locally saved benchmark file for every target in the estate would be
    needless, repeated disk I/O for what run_decision() only needs once."""
    candidates: list[PerformanceEvidence] = []
    fixture = fixture_evidence(workload_id, target_id)
    if fixture is not None:
        candidates.append(fixture)
    candidates.extend(
        run
        for run in benchmark_runs
        if run.workload_id == workload_id and run.compute_target_id == target_id
    )
    return candidates


def resolve_evidence(
    workload_id: str,
    target_id: str,
    *,
    benchmark_runs: list[PerformanceEvidence],
    required_metrics: Iterable[str],
) -> Optional[PerformanceEvidence]:
    """Gather + select in one call — the single function decision.py's
    three evidence-consuming call sites (the main scoring loop, the
    greedy-split fallback, and the unmitigated-projection helper) all use,
    instead of each repeating the same two-step gather-then-select."""
    candidates = gather_evidence_candidates(workload_id, target_id, benchmark_runs=benchmark_runs)
    return select_evidence(candidates, required_metrics=required_metrics)
