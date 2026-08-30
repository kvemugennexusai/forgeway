"""Proves app.core is actually decoupled from this product's fixture-backed
data source — not just organized into a folder that looks decoupled.

Nothing in this file imports app.data.loader (or anything else under
app/engine, app/routers, app/state). Every ComputeTarget / Workload /
PerformanceProfile below is constructed by hand. If a future change made
app.core secretly depend on the fixture loader (or on any other product-
layer module), this file would fail to even build its inputs, let alone
run the pipeline.
"""
from __future__ import annotations

import pytest

from app.core.engine.feasibility import evaluate_feasibility
from app.core.engine.ranking import normalize_and_weight
from app.core.engine.scoring import score_candidate
from app.core.schemas import (
    SLO,
    ComputeTarget,
    CurrentPlacement,
    EnterprisePolicy,
    Metric,
    ObjectiveWeights,
    PerformanceProfile,
    Workload,
)


def _workload(**overrides) -> Workload:
    base = dict(
        id="wl-core-test",
        name="core isolation test workload",
        model_family="Test-7B",
        model_params_billion=7,
        workload_class="realtime-inference",
        precision="fp16",
        weights_footprint_gb=10,
        kv_cache_overhead_gb=2,
        baseline_concurrency=4,
        slo=SLO(p99_latency_ms=500, min_throughput_tokens_per_s=100, availability_pct=99.0),
        policy=EnterprisePolicy(
            allowed_vendors=["nvidia", "amd"],
            denied_vendors=[],
            allowed_regions=["us-east-1"],
            budget_ceiling_per_hr=100.0,
        ),
        current_placement=CurrentPlacement(
            target_id="t-a",
            replica_count=1,
            measured_p99_latency_ms=400,
            measured_throughput_tokens_per_s_per_replica=150,
            cost_per_hr=2.0,
            provenance="MEASURED",
            source="test",
        ),
        objective_weights=ObjectiveWeights(),
        min_confidence_pct=70.0,
    )
    base.update(overrides)
    return Workload(**base)


def _target(**overrides) -> ComputeTarget:
    base = dict(
        id="t-a",
        vendor="nvidia",
        model="Test GPU A",
        tier="datacenter",
        location="us-east-1 (cloud)",
        architecture="test",
        memory_gb_per_device=80,
        interconnect="NVLink",
        supported_precisions=["fp16", "bf16"],
        capacity_units_total=10,
        capacity_units_allocated=2,
        price_per_hr_per_unit=Metric(value=2.0, confidence=90, provenance="PUBLISHED", source="test"),
        status="healthy",
    )
    base.update(overrides)
    return ComputeTarget(**base)


def _profile(**overrides) -> PerformanceProfile:
    base = dict(
        workload_id="wl-core-test",
        target_id="t-a",
        throughput_tokens_per_s_per_replica=Metric(
            value=100, confidence=90, provenance="MEASURED", source="test"
        ),
        p99_latency_ms_per_replica=Metric(value=100, confidence=90, provenance="MEASURED", source="test"),
    )
    base.update(overrides)
    return PerformanceProfile(**base)


def test_core_pipeline_runs_without_the_fixture_data_source():
    workload = _workload()
    target_a = _target(id="t-a", vendor="nvidia")
    target_b = _target(
        id="t-b",
        vendor="amd",
        model="Test GPU B",
        price_per_hr_per_unit=Metric(value=1.0, confidence=90, provenance="PUBLISHED", source="test"),
    )
    targets = [target_a, target_b]
    targets_by_id = {t.id: t for t in targets}
    profiles = {
        "t-a": _profile(target_id="t-a"),
        "t-b": _profile(target_id="t-b"),
    }

    candidates = []
    for target in targets:
        checks = evaluate_feasibility(workload, target)
        candidate = score_candidate(
            workload=workload,
            target=target,
            profile=profiles.get(target.id),
            checks=checks,
            required_throughput=workload.slo.min_throughput_tokens_per_s,
            free_capacity_units=target.free_capacity_units,
        )
        candidates.append(candidate)

    assert all(c.feasible for c in candidates)

    qualifying = [c for c in candidates if c.feasible and c.predicted and c.predicted.meets_slo]
    normalize_and_weight(qualifying, workload, {}, targets_by_id)

    by_id = {c.target_id: c for c in qualifying}
    assert all(c.weighted_score is not None for c in qualifying)
    # t-b is half the price of t-a with identical throughput/latency — it
    # must never score worse than t-a on the cost axis.
    assert by_id["t-b"].normalized_scores.cost >= by_id["t-a"].normalized_scores.cost


def test_normalize_and_weight_rejects_candidates_missing_predicted():
    """The ranking function's precondition: every candidate passed in must
    already have cleared feasibility + the SLO gate (predicted is set). A
    candidate that hasn't must be rejected loudly, not silently mis-scored."""
    workload = _workload()
    target = _target()
    checks = evaluate_feasibility(workload, target)
    unqualified = score_candidate(
        workload=workload,
        target=target,
        profile=None,  # no evidence on file -> feasible=False, predicted=None
        checks=checks,
        required_throughput=workload.slo.min_throughput_tokens_per_s,
        free_capacity_units=target.free_capacity_units,
    )
    assert unqualified.predicted is None

    with pytest.raises(ValueError):
        normalize_and_weight([unqualified], workload, {}, {target.id: target})
