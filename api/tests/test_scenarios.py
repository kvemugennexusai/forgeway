"""Tests for the six named scenario presets.

Each scenario is checked for: the exact parameter values specified (20->70
req/s, 50% H100 loss, 70% weights, 95% confidence), that it never mutates
fixture/production state, and that the BEFORE/AFTER/change-explanation
triple is coherent. No LLM, no ML — every assertion is on a deterministically
computed value.
"""
from __future__ import annotations

import copy

from app.data.loader import get_compute_target, get_workload, load_compute_targets, load_workloads
from app.engine.scenarios import CATALOG, apply_scenario, run_scenario
from app.models import ScenarioType

ALL_SCENARIOS = [
    ScenarioType.normal,
    ScenarioType.demand_spike,
    ScenarioType.h100_capacity_loss,
    ScenarioType.cost_priority,
    ScenarioType.performance_priority,
    ScenarioType.strict_confidence_policy,
]


def test_catalog_lists_exactly_the_six_required_scenarios():
    names = {entry.name for entry in CATALOG}
    assert names == set(ALL_SCENARIOS)


def test_scenarios_never_mutate_fixture_state():
    workload = get_workload("wl-llama70b-rt")
    targets_before = copy.deepcopy(load_compute_targets())
    workloads_before = copy.deepcopy(load_workloads())

    for name in ALL_SCENARIOS:
        run_scenario(workload, name, before_id=f"mut-b-{name.value}", after_id=f"mut-a-{name.value}")

    assert load_compute_targets() == targets_before
    assert load_workloads() == workloads_before
    # And the workload passed in is untouched too.
    assert get_workload("wl-llama70b-rt") == workload


def test_demand_spike_is_exactly_20_to_70_requests_per_second():
    workload = get_workload("wl-llama70b-rt")
    application = apply_scenario(workload, ScenarioType.demand_spike)

    before_rps = workload.slo.min_throughput_tokens_per_s / workload.tokens_per_request
    after_rps = application.effective_min_throughput / workload.tokens_per_request

    assert before_rps == 20
    assert after_rps == 70
    assert "20" in application.scenario.label and "70" in application.scenario.label


def test_h100_capacity_loss_is_exactly_50_percent():
    workload = get_workload("wl-llama70b-rt")
    h100_before = get_compute_target("nvidia-h100-dc")
    application = apply_scenario(workload, ScenarioType.h100_capacity_loss)

    assert application.capacity_overrides["nvidia-h100-dc"] == h100_before.free_capacity_units // 2


def test_cost_priority_sets_cost_weight_to_70_percent():
    workload = get_workload("wl-llama70b-rt")
    application = apply_scenario(workload, ScenarioType.cost_priority)
    assert round(application.objective_weights.cost, 2) == 0.7
    # the other two axes shrink but keep their relative order
    assert application.objective_weights.performance > application.objective_weights.headroom


def test_performance_priority_sets_performance_weight_to_70_percent():
    workload = get_workload("wl-llama70b-rt")
    application = apply_scenario(workload, ScenarioType.performance_priority)
    assert round(application.objective_weights.performance, 2) == 0.7


def test_strict_confidence_policy_sets_minimum_confidence_to_95():
    workload = get_workload("wl-llama70b-rt")
    application = apply_scenario(workload, ScenarioType.strict_confidence_policy)
    assert application.min_confidence_pct == 95.0


def test_strict_confidence_policy_withholds_recommendation_rather_than_split_unconfidently():
    """Neither H100 (92%) nor MI300X (78%) reaches a 95% bar — the engine
    must not silently fall back to splitting across them anyway."""
    workload = get_workload("wl-llama70b-rt")
    comparison = run_scenario(
        workload, ScenarioType.strict_confidence_policy, before_id="sc-b", after_id="sc-a"
    )

    assert comparison.after.recommended_target_id is None
    assert comparison.after.split_allocation == []
    assert comparison.after.slo_met is False
    assert "confidence" in comparison.change_explanation.lower()


def test_normal_scenario_reproduces_baseline():
    workload = get_workload("wl-llama70b-rt")
    comparison = run_scenario(workload, ScenarioType.normal, before_id="n-b", after_id="n-a")

    assert comparison.before.recommended_target_id == comparison.after.recommended_target_id == "amd-mi300x"
    assert comparison.before.confidence_pct == comparison.after.confidence_pct


def test_demand_spike_scenario_produces_before_event_after_and_explains_the_change():
    workload = get_workload("wl-llama70b-rt")
    comparison = run_scenario(workload, ScenarioType.demand_spike, before_id="ds-b", after_id="ds-a")

    assert comparison.before.recommended_target_id == "amd-mi300x"
    assert comparison.after.recommended_target_id is None  # split, not a sole winner
    assert {a.target_id for a in comparison.after.split_allocation} == {"amd-mi300x", "nvidia-h100-dc"}
    assert comparison.event.name == ScenarioType.demand_spike
    assert "70" in comparison.event.label
    assert "amd-mi300x" in comparison.change_explanation


def test_each_scenario_response_carries_independent_before_and_after_ids():
    workload = get_workload("wl-llama70b-rt")
    for name in ALL_SCENARIOS:
        comparison = run_scenario(workload, name, before_id=f"id-b-{name.value}", after_id=f"id-a-{name.value}")
        assert comparison.before.id == f"id-b-{name.value}"
        assert comparison.after.id == f"id-a-{name.value}"
        assert comparison.after.derived_from_id == comparison.before.id
        assert comparison.workload_id == workload.id
