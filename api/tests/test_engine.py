"""Unit tests for the Forgeway decision engine.

Two kinds of test here, deliberately:

- Isolated tests (test_insufficient_memory_rejects_target and friends) build
  minimal synthetic Workload/ComputeTarget objects so a single hard
  constraint can be proven in isolation, independent of the real fixture
  numbers ever drifting.
- Behavioral tests (the objective-weight / confidence-threshold / demand-spike
  ones) run the full pipeline against the real fixtures, because "does
  changing a weight change the ranking" is only meaningful with more than one
  real candidate in play.

No LLM, no machine learning, nothing non-deterministic — every test asserts
on values computed the same way every run.
"""
from __future__ import annotations

from app.data.loader import get_workload
from app.engine.decision import run_decision
from app.engine.feasibility import evaluate_feasibility
from app.engine.scoring import score_candidate
from app.models import (
    ComputeTarget,
    CurrentPlacement,
    EnterprisePolicy,
    Metric,
    ObjectiveWeights,
    PerformanceProfile,
    SLO,
    ScenarioParams,
    ScenarioType,
    Workload,
)

# --------------------------------------------------------------------------
# Synthetic fixtures for isolated hard-constraint tests
# --------------------------------------------------------------------------


def make_workload(**overrides) -> Workload:
    base = dict(
        id="wl-test",
        name="test workload",
        model_family="Test-7B",
        model_params_billion=7,
        workload_class="realtime-inference",
        precision="fp16",
        weights_footprint_gb=10,
        kv_cache_overhead_gb=2,
        baseline_concurrency=4,
        slo=SLO(p99_latency_ms=500, min_throughput_tokens_per_s=100, availability_pct=99.0),
        policy=EnterprisePolicy(
            allowed_vendors=["nvidia"],
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
        reanalyze=False,
    )
    base.update(overrides)
    return Workload(**base)


def make_target(**overrides) -> ComputeTarget:
    base = dict(
        id="t-a",
        vendor="nvidia",
        model="Test GPU",
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


def make_profile(**overrides) -> PerformanceProfile:
    base = dict(
        workload_id="wl-test",
        target_id="t-a",
        throughput_tokens_per_s_per_replica=Metric(
            value=100, confidence=90, provenance="MEASURED", source="test"
        ),
        p99_latency_ms_per_replica=Metric(value=100, confidence=90, provenance="MEASURED", source="test"),
    )
    base.update(overrides)
    return PerformanceProfile(**base)


# --------------------------------------------------------------------------
# Hard constraints — step 3 (feasibility) and step 6 (SLO). Each must reject
# outright, never just lower a score.
# --------------------------------------------------------------------------


def test_insufficient_memory_rejects_target():
    workload = make_workload(weights_footprint_gb=90, kv_cache_overhead_gb=10)  # needs 100 GB
    target = make_target(memory_gb_per_device=80)  # only 80 GB/device

    checks = evaluate_feasibility(workload, target)

    memory_check = next(c for c in checks if c.name.startswith("memory"))
    assert memory_check.passed is False
    assert not all(c.passed for c in checks)


def test_unsupported_precision_rejects_target():
    workload = make_workload(precision="fp8")
    target = make_target(supported_precisions=["fp16", "bf16"])  # no fp8

    checks = evaluate_feasibility(workload, target)

    precision_check = next(c for c in checks if "precision" in c.name)
    assert precision_check.passed is False
    assert not all(c.passed for c in checks)


def test_policy_mismatch_rejects_target():
    workload = make_workload(
        policy=EnterprisePolicy(
            allowed_vendors=["amd"],
            denied_vendors=[],
            allowed_regions=["us-east-1"],
            budget_ceiling_per_hr=100.0,
        )
    )
    target = make_target(vendor="nvidia")  # not in the allowed-vendor policy

    checks = evaluate_feasibility(workload, target)

    vendor_check = next(c for c in checks if "vendor" in c.name)
    assert vendor_check.passed is False
    assert not all(c.passed for c in checks)


def test_latency_slo_violation_rejects_target():
    workload = make_workload(
        slo=SLO(p99_latency_ms=200, min_throughput_tokens_per_s=50, availability_pct=99.0)
    )
    target = make_target()
    profile = make_profile(
        p99_latency_ms_per_replica=Metric(value=500, confidence=90, provenance="MEASURED", source="test")
    )

    checks = evaluate_feasibility(workload, target)
    assert all(c.passed for c in checks)  # hard compatibility is fine on its own

    candidate = score_candidate(
        workload=workload,
        target=target,
        profile=profile,
        checks=checks,
        required_throughput=workload.slo.min_throughput_tokens_per_s,
        free_capacity_units=target.free_capacity_units,
    )

    assert candidate.feasible is True  # compatible hardware/software — just too slow
    assert candidate.slo_violations  # explicit, hard rejection from the SLO check
    assert candidate.predicted is not None
    assert candidate.predicted.meets_slo is False


def test_hard_constraints_are_never_folded_into_the_weighted_score():
    """A candidate that fails a hard constraint must never receive a
    normalized/weighted score — hard constraints reject, they don't get
    outweighed by a favorable objective weight."""
    workload = make_workload(precision="fp8")
    target = make_target(supported_precisions=["fp16"])
    checks = evaluate_feasibility(workload, target)

    candidate = score_candidate(
        workload=workload,
        target=target,
        profile=make_profile(),
        checks=checks,
        required_throughput=workload.slo.min_throughput_tokens_per_s,
        free_capacity_units=target.free_capacity_units,
    )

    assert candidate.feasible is False
    assert candidate.weighted_score is None
    assert candidate.normalized_scores is None


# --------------------------------------------------------------------------
# Behavioral tests — run the full pipeline against the real fixtures, where
# more than one real candidate exists to rank.
# --------------------------------------------------------------------------


def _baseline_llama(**run_decision_overrides):
    workload = get_workload("wl-llama70b-rt")
    assert workload is not None
    record = run_decision(
        workload,
        record_id="rec-test-baseline",
        scenario=ScenarioParams(type=ScenarioType.normal, label="Normal — baseline, no scenario applied"),
        effective_min_throughput=workload.slo.min_throughput_tokens_per_s,
        **run_decision_overrides,
    )
    return workload, record


def test_baseline_recommends_mi300x_over_h100():
    _, record = _baseline_llama()
    assert record.recommended_target_id == "amd-mi300x"
    assert record.slo_met is True
    assert record.recommended is not None
    assert record.recommended.cost_per_hr < 8.20  # cheaper than the current H100 placement


def test_hard_checks_reject_incompatible_targets_with_distinct_reasons():
    _, record = _baseline_llama()
    by_id = {c.target_id: c for c in record.candidates}

    assert by_id["intel-gaudi3"].feasible is False
    assert "runtime" in by_id["intel-gaudi3"].rejection_reason.lower()

    assert by_id["aws-trainium2"].feasible is False
    assert "neuron" in by_id["aws-trainium2"].rejection_reason.lower()

    assert by_id["nvidia-l40s"].feasible is False
    assert "gb" in by_id["nvidia-l40s"].rejection_reason.lower()

    assert by_id["nvidia-jetson-thor"].feasible is False
    assert by_id["local-nvidia-lab"].feasible is False

    # step 4: every failing check is captured, not just the first one shown.
    assert len(by_id["nvidia-l40s"].rejection_reasons) >= 1
    assert all(reason for reason in by_id["nvidia-l40s"].rejection_reasons)


def test_modeled_evidence_never_labeled_measured():
    _, record = _baseline_llama()
    mi300x_evidence = [e for e in record.evidence if "MI300X" in e.label]
    assert mi300x_evidence
    perf_evidence = [
        e for e in mi300x_evidence if "throughput" in e.label.lower() or "latency" in e.label.lower()
    ]
    assert perf_evidence
    assert all(e.metric.provenance == "MODELED" for e in perf_evidence)


def test_changing_cost_weight_changes_ranking():
    _, cost_heavy = _baseline_llama(
        objective_weights=ObjectiveWeights(cost=1.0, performance=0.0, headroom=0.0)
    )
    _, headroom_heavy = _baseline_llama(
        objective_weights=ObjectiveWeights(cost=0.0, performance=0.0, headroom=1.0)
    )

    assert cost_heavy.recommended_target_id == "amd-mi300x"  # cheaper on $/throughput
    assert headroom_heavy.recommended_target_id == "nvidia-h100-dc"  # far more spare capacity
    assert cost_heavy.recommended_target_id != headroom_heavy.recommended_target_id


def test_changing_confidence_threshold_can_change_recommendation():
    _, permissive = _baseline_llama(min_confidence_pct=50)
    _, strict = _baseline_llama(min_confidence_pct=85)

    by_id = {c.target_id: c for c in permissive.candidates}
    assert by_id["amd-mi300x"].confidence_pct < 85  # MODELED prediction, below the strict bar

    assert permissive.recommended_target_id == "amd-mi300x"
    assert strict.recommended_target_id == "nvidia-h100-dc"  # only the MEASURED candidate clears 85%


def _spike(workload, baseline, multiplier: float, record_id: str):
    """A demand-spike recompute at an arbitrary multiplier, via the same
    run_decision() primitive the named `demand_spike` scenario preset (fixed
    at 3.5x) is built on. Kept here to prove the underlying mechanism is
    general, not hardcoded to that one preset value — the six-scenario
    catalog itself is covered end-to-end in tests/test_scenarios.py."""
    return run_decision(
        workload,
        record_id=record_id,
        scenario=ScenarioParams(type=ScenarioType.demand_spike, demand_multiplier=multiplier, label=f"{multiplier:g}x demand spike"),
        effective_min_throughput=workload.slo.min_throughput_tokens_per_s * multiplier,
        prior=baseline,
    )


def test_demand_spike_can_change_recommendation():
    workload, baseline = _baseline_llama()
    assert baseline.recommended_target_id == "amd-mi300x"

    spike = _spike(workload, baseline, 1.8, "rec-test-spike")

    assert spike.recommended_target_id == "nvidia-h100-dc"  # MI300X can't cover 1.8x alone
    assert spike.recommended_target_id != baseline.recommended_target_id


def test_larger_demand_spike_breaches_slo_and_recommends_split():
    workload, baseline = _baseline_llama()
    spike = _spike(workload, baseline, 3.5, "rec-test-spike-large")

    assert spike.recommended_target_id is None  # no single target covers it alone
    assert len(spike.split_allocation) >= 2
    target_ids = {a.target_id for a in spike.split_allocation}
    assert "amd-mi300x" in target_ids
    assert "nvidia-h100-dc" in target_ids

    assert spike.unmitigated_projection is not None
    assert spike.unmitigated_projection.slo_violated is True


def test_split_allocation_shares_sum_to_roughly_100_when_no_shortfall():
    workload, baseline = _baseline_llama()
    spike = _spike(workload, baseline, 3.5, "rec-test-shares")
    if spike.shortfall_tokens_per_s <= 0 and spike.split_allocation:
        total_share = sum(a.throughput_share_pct for a in spike.split_allocation)
        assert 99.0 <= total_share <= 101.0
