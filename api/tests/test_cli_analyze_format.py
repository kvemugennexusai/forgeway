"""Unit tests for app.cli.main.format_analyze_human — edge cases that are
awkward to reproduce through the full CLI + real fixtures path (a
recommendation costing *more* than the current placement; target labels
long enough to break fixed-width column alignment), tested directly
against synthetic Recommendation/PlacementDecision/ComputeTarget objects
instead.
"""
from __future__ import annotations

from app.cli.main import format_analyze_human
from app.core.schemas import SLO, CurrentPlacement, EnterprisePolicy, Metric, ObjectiveWeights, Workload
from app.core.schemas import ComputeTarget
from app.core.schemas.v0_1 import ImprovementVsCurrentPlacement, PlacementDecision, RejectedTarget
from app.models import Recommendation, ScenarioParams, ScenarioType


def _workload(**overrides) -> Workload:
    base = dict(
        id="wl-format-test",
        name="format test workload",
        model_family="Test",
        model_params_billion=7,
        workload_class="realtime-inference",
        precision="fp16",
        weights_footprint_gb=10,
        kv_cache_overhead_gb=2,
        baseline_concurrency=4,
        slo=SLO(p99_latency_ms=500, min_throughput_tokens_per_s=100, availability_pct=99.0),
        policy=EnterprisePolicy(
            allowed_vendors=["nvidia"], denied_vendors=[], allowed_regions=["us-east-1"], budget_ceiling_per_hr=100.0
        ),
        current_placement=CurrentPlacement(
            target_id="t-current",
            replica_count=1,
            measured_p99_latency_ms=400,
            measured_throughput_tokens_per_s_per_replica=150,
            cost_per_hr=5.00,
            provenance="MEASURED",
            source="test",
        ),
        objective_weights=ObjectiveWeights(),
        min_confidence_pct=70.0,
    )
    base.update(overrides)
    return Workload(**base)


def _target(target_id: str, model: str) -> ComputeTarget:
    return ComputeTarget(
        id=target_id,
        vendor="nvidia",
        model=model,
        tier="datacenter",
        location="us-east-1 (cloud)",
        architecture="test",
        memory_gb_per_device=80,
        interconnect="NVLink",
        supported_precisions=["fp16"],
        capacity_units_total=10,
        capacity_units_allocated=2,
        price_per_hr_per_unit=Metric(value=1.0, confidence=90, provenance="PUBLISHED", source="test"),
        status="healthy",
    )


def _recommendation(workload: Workload, **overrides) -> Recommendation:
    base = dict(
        id="rec-format-test",
        workload_id=workload.id,
        workload_name=workload.name,
        scenario=ScenarioParams(type=ScenarioType.normal, label="Normal"),
        slo=workload.slo,
        current_placement=workload.current_placement,
        effective_min_throughput_tokens_per_s=workload.slo.min_throughput_tokens_per_s,
        objective_weights=workload.objective_weights,
        min_confidence_pct=workload.min_confidence_pct,
        candidates=[],
        slo_met=True,
        confidence_pct=95,
        reasoning="Test reasoning sentence.",
    )
    base.update(overrides)
    return Recommendation(**base)


def _placement_decision(workload: Workload, **overrides) -> PlacementDecision:
    base = dict(
        workload_id=workload.id,
        workload_name=workload.name,
        slo=workload.slo,
        current_placement=workload.current_placement,
        evaluated_targets=["t-current"],
        feasible_targets=["t-current"],
        recommended_target_id="t-current",
        confidence=95.0,
    )
    base.update(overrides)
    return PlacementDecision(**base)


def test_improvement_line_reads_lower_cost_when_recommendation_is_cheaper():
    workload = _workload()
    decision = _placement_decision(
        workload,
        improvement_vs_current_placement=ImprovementVsCurrentPlacement(
            current_target_id="t-current", current_cost_per_hr=5.00, recommended_cost_per_hr=3.00,
            cost_savings_pct=40.0, slo_met=True,
        ),
    )
    output = format_analyze_human(workload, _recommendation(workload), decision, {"t-current": _target("t-current", "Test GPU")}, None)
    assert "40.0% lower cost" in output
    assert "higher cost" not in output


def test_improvement_line_reads_higher_cost_when_recommendation_is_pricier():
    """The reachable case a fixed-savings-only phrasing gets wrong: ranking
    picks the best weighted blend of cost/performance/headroom, not lowest
    cost alone, so a recommendation can legitimately cost more."""
    workload = _workload()
    decision = _placement_decision(
        workload,
        improvement_vs_current_placement=ImprovementVsCurrentPlacement(
            current_target_id="t-current", current_cost_per_hr=5.00, recommended_cost_per_hr=6.00,
            cost_savings_pct=-20.0, slo_met=True,
        ),
    )
    output = format_analyze_human(workload, _recommendation(workload), decision, {"t-current": _target("t-current", "Test GPU")}, None)
    assert "20.0% higher cost" in output
    assert "-20.0% lower cost" not in output
    assert "lower cost" not in output


def test_improvement_line_reads_same_cost_when_savings_are_exactly_zero():
    workload = _workload()
    decision = _placement_decision(
        workload,
        improvement_vs_current_placement=ImprovementVsCurrentPlacement(
            current_target_id="t-current", current_cost_per_hr=5.00, recommended_cost_per_hr=5.00,
            cost_savings_pct=0.0, slo_met=True,
        ),
    )
    output = format_analyze_human(workload, _recommendation(workload), decision, {"t-current": _target("t-current", "Test GPU")}, None)
    assert "the same cost" in output
    assert "lower cost" not in output
    assert "higher cost" not in output


def test_evaluated_table_stays_aligned_for_labels_longer_than_any_fixed_width():
    workload = _workload()
    long_label_target_id = "t-long"
    targets_by_id = {
        "t-current": _target("t-current", "Short"),
        long_label_target_id: _target(long_label_target_id, "A Very Long Compute Target Model Name Indeed"),
    }
    decision = _placement_decision(
        workload,
        evaluated_targets=["t-current", long_label_target_id],
        feasible_targets=["t-current"],
        recommended_target_id="t-current",
        rejected_targets=[
            RejectedTarget(target_id=long_label_target_id, target_label="A Very Long Compute Target Model Name Indeed", reasons=["out of memory"])
        ],
    )
    output = format_analyze_human(workload, _recommendation(workload), decision, targets_by_id, None)

    evaluated_lines = [
        line
        for line in output.splitlines()
        if "RECOMMENDED" in line or "REJECTED" in line or "FEASIBLE" in line
    ]
    assert len(evaluated_lines) == 2
    # Every status word must be preceded by whitespace — never glued
    # directly onto the label, regardless of how long the label is.
    for line in evaluated_lines:
        assert "  " in line  # at least a two-space gap survives before the status word
    # Real alignment, not just "some space": both status words start at the
    # same column.
    short_status_col = evaluated_lines[0].index("RECOMMENDED")
    long_status_col = evaluated_lines[1].index("REJECTED")
    assert short_status_col == long_status_col
