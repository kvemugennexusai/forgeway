"""Integration tests proving the (unmodified) decision engine already
handles NVIDIA and AMD MEASURED evidence coexisting for the same workload,
with no vendor-specific scoring anywhere in the pipeline.

None of app.core.engine, app.engine.decision, or app.core.schemas is
touched by the cross-vendor benchmark work — these tests exist to prove
that claim, using run_decision()'s existing `targets` and
`imported_evidence` parameters (both already used by `forgeway analyze`
and the web `/import` flow) to inject synthetic, fully-controlled NVIDIA
and AMD ComputeTargets + PerformanceEvidence, entirely independent of this
demo's fixture catalog.
"""
from __future__ import annotations

from app.core.schemas import (
    LATENCY_METRIC_KEY,
    THROUGHPUT_METRIC_KEY,
    SLO,
    ComputeTarget,
    CurrentPlacement,
    EnterprisePolicy,
    Metric,
    ObjectiveWeights,
    Workload,
)
from app.core.schemas.v0_1 import PerformanceEvidence
from app.engine.decision import run_decision
from app.models import ScenarioParams, ScenarioType

_WORKLOAD_ID = "wl-cross-vendor-test"


def _target(target_id: str, vendor: str, *, price_per_hr: float, capacity_units_total: int = 10) -> ComputeTarget:
    return ComputeTarget(
        id=target_id,
        vendor=vendor,
        model=f"Test {vendor.upper()} GPU",
        tier="lab",
        location="local (test-region)",
        architecture="test-arch",
        memory_gb_per_device=80.0,
        interconnect="not probed",
        supported_precisions=["bf16"],
        capacity_units_total=capacity_units_total,
        capacity_units_allocated=0,
        price_per_hr_per_unit=Metric(value=price_per_hr, confidence=90, provenance="MODELED", source="test"),
        status="healthy",
    )


def _evidence(target_id: str, *, latency_ms: float, throughput_tps: float) -> PerformanceEvidence:
    return PerformanceEvidence(
        compute_target_id=target_id,
        workload_id=_WORKLOAD_ID,
        metrics={
            LATENCY_METRIC_KEY: Metric(value=latency_ms, confidence=95, provenance="MEASURED", source="test"),
            THROUGHPUT_METRIC_KEY: Metric(value=throughput_tps, confidence=95, provenance="MEASURED", source="test"),
        },
        provenance="MEASURED",
        confidence=95.0,
        source="test",
        benchmark_run_id=f"run-{target_id}",
    )


def _workload(*, p99_latency_ms: float, min_throughput: float, objective_weights: ObjectiveWeights | None = None) -> Workload:
    return Workload(
        id=_WORKLOAD_ID,
        name="Cross-vendor test workload",
        model_family="Test Model",
        model_params_billion=8,
        workload_class="realtime-inference",
        precision="bf16",
        weights_footprint_gb=16,
        kv_cache_overhead_gb=4,
        baseline_concurrency=1,
        slo=SLO(p99_latency_ms=p99_latency_ms, min_throughput_tokens_per_s=min_throughput, availability_pct=99.9),
        policy=EnterprisePolicy(
            allowed_vendors=["nvidia", "amd"],
            denied_vendors=[],
            allowed_regions=["test-region"],
            budget_ceiling_per_hr=1000.0,
        ),
        current_placement=CurrentPlacement(
            target_id="nvidia-1",
            replica_count=1,
            measured_p99_latency_ms=100,
            measured_throughput_tokens_per_s_per_replica=200,
            cost_per_hr=2.0,
            provenance="MEASURED",
            source="test",
        ),
        objective_weights=objective_weights or ObjectiveWeights(),
        min_confidence_pct=70.0,
    )


def _run(workload: Workload, targets: list[ComputeTarget], evidence: list[PerformanceEvidence], **overrides):
    return run_decision(
        workload,
        record_id="rec-cross-vendor-test",
        scenario=ScenarioParams(type=ScenarioType.normal, label="Normal — baseline, no scenario applied"),
        effective_min_throughput=workload.slo.min_throughput_tokens_per_s,
        targets=targets,
        imported_evidence=evidence,
        **overrides,
    )


# --------------------------------------------------------------------------
# NVIDIA + AMD measured evidence coexist
# --------------------------------------------------------------------------


def test_nvidia_and_amd_measured_evidence_both_score_as_candidates():
    nvidia = _target("nvidia-1", "nvidia", price_per_hr=2.0)
    amd = _target("amd-1", "amd", price_per_hr=4.0)
    evidence = [
        _evidence("nvidia-1", latency_ms=100, throughput_tps=200),
        _evidence("amd-1", latency_ms=200, throughput_tps=100),
    ]
    workload = _workload(p99_latency_ms=250, min_throughput=100)

    record = _run(workload, [nvidia, amd], evidence)

    assert {c.target_id for c in record.candidates} == {"nvidia-1", "amd-1"}
    for c in record.candidates:
        assert c.feasible is True
        assert c.raw_prediction is not None  # real evidence was found and scored, not rejected


# --------------------------------------------------------------------------
# No hardcoded vendor preference — recommendation follows the numbers
# --------------------------------------------------------------------------


def test_recommendation_follows_better_numbers_not_vendor_identity():
    workload = _workload(p99_latency_ms=250, min_throughput=100)

    # Scenario A: NVIDIA has the better price and latency.
    nvidia_better = _target("nvidia-1", "nvidia", price_per_hr=2.0)
    amd_worse = _target("amd-1", "amd", price_per_hr=4.0)
    evidence_a = [
        _evidence("nvidia-1", latency_ms=100, throughput_tps=200),
        _evidence("amd-1", latency_ms=200, throughput_tps=100),
    ]
    record_a = _run(workload, [nvidia_better, amd_worse], evidence_a)
    assert record_a.recommended_target_id == "nvidia-1"

    # Scenario B: identical setup, but the *same numbers* now sit on the AMD
    # target and the worse numbers on NVIDIA — nothing about the engine
    # changes, only which vendor label carries which physical result.
    nvidia_worse = _target("nvidia-1", "nvidia", price_per_hr=4.0)
    amd_better = _target("amd-1", "amd", price_per_hr=2.0)
    evidence_b = [
        _evidence("nvidia-1", latency_ms=200, throughput_tps=100),
        _evidence("amd-1", latency_ms=100, throughput_tps=200),
    ]
    record_b = _run(workload, [nvidia_worse, amd_better], evidence_b)
    assert record_b.recommended_target_id == "amd-1"

    # The winning candidate's weighted score is identical in both scenarios
    # — proof the engine scored the *numbers*, not the vendor string.
    best_a = next(c for c in record_a.candidates if c.target_id == record_a.recommended_target_id)
    best_b = next(c for c in record_b.candidates if c.target_id == record_b.recommended_target_id)
    assert best_a.weighted_score == best_b.weighted_score


# --------------------------------------------------------------------------
# Changing the SLO changes which vendor is recommended
# --------------------------------------------------------------------------


def test_tightening_slo_can_flip_which_vendor_qualifies():
    # NVIDIA: low latency, low per-replica throughput (needs more replicas
    # at scale). AMD: higher latency, much higher per-replica throughput
    # (cheaper at scale).
    nvidia = _target("nvidia-1", "nvidia", price_per_hr=3.0, capacity_units_total=10)
    amd = _target("amd-1", "amd", price_per_hr=3.0, capacity_units_total=10)
    evidence = [
        _evidence("nvidia-1", latency_ms=80, throughput_tps=100),
        _evidence("amd-1", latency_ms=180, throughput_tps=300),
    ]

    # Low volume, tight SLO: AMD's own latency (180ms) breaches a 100ms SLO
    # outright — NVIDIA is the only qualifier.
    tight = _workload(p99_latency_ms=100, min_throughput=100)
    record_tight = _run(tight, [nvidia, amd], evidence)
    assert record_tight.recommended_target_id == "nvidia-1"
    amd_candidate = next(c for c in record_tight.candidates if c.target_id == "amd-1")
    # "feasible" means hard compatibility + usable evidence — an SLO breach
    # is a separate, softer rejection captured in slo_violations/status,
    # not a hard-compatibility failure. See app.core.engine.scoring.
    assert amd_candidate.status == "rejected"
    assert amd_candidate.predicted is not None and amd_candidate.predicted.meets_slo is False
    assert any("exceeds" in r for r in amd_candidate.slo_violations)

    # High volume, loose SLO: both meet latency, but NVIDIA now needs 3
    # replicas (ceil(280/100)) at $3 each = $9/hr vs. AMD's 1 replica at
    # $3/hr — AMD's cost advantage at this scale flips the recommendation.
    loose_high_volume = _workload(p99_latency_ms=200, min_throughput=280)
    record_loose = _run(loose_high_volume, [nvidia, amd], evidence)
    assert record_loose.recommended_target_id == "amd-1"


# --------------------------------------------------------------------------
# Changing objective weights changes the ranking
# --------------------------------------------------------------------------


def test_objective_weights_change_ranking_between_identical_candidates():
    expensive_fast = _target("nvidia-1", "nvidia", price_per_hr=5.0)
    cheap_slow = _target("amd-1", "amd", price_per_hr=1.0)
    evidence = [
        _evidence("nvidia-1", latency_ms=50, throughput_tps=500),
        _evidence("amd-1", latency_ms=150, throughput_tps=500),
    ]
    workload = _workload(p99_latency_ms=200, min_throughput=100)

    cost_heavy = ObjectiveWeights(cost=0.9, performance=0.05, headroom=0.05)
    record_cost = _run(workload, [expensive_fast, cheap_slow], evidence, objective_weights=cost_heavy)
    assert record_cost.recommended_target_id == "amd-1"

    performance_heavy = ObjectiveWeights(cost=0.05, performance=0.9, headroom=0.05)
    record_perf = _run(workload, [expensive_fast, cheap_slow], evidence, objective_weights=performance_heavy)
    assert record_perf.recommended_target_id == "nvidia-1"


# --------------------------------------------------------------------------
# Recommendation withheld when evidence is insufficient
# --------------------------------------------------------------------------


def test_recommendation_withheld_when_no_evidence_on_file():
    nvidia = _target("nvidia-1", "nvidia", price_per_hr=2.0)
    workload = _workload(p99_latency_ms=200, min_throughput=100)

    record = _run(workload, [nvidia], evidence=[])  # no PerformanceEvidence at all

    assert record.recommended_target_id is None
    assert record.recommended is None
    candidate = record.candidates[0]
    assert candidate.feasible is False
    assert candidate.rejection_reason is not None
    assert "evidence" in candidate.rejection_reason.lower()
    assert "No feasible target was found" in record.reasoning
