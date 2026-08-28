"""The estate Insight panel must always reflect a workload's stable
canonical baseline — never whatever recommendation a user most recently
computed by poking at /analyze or a scenario. This is the fix for the
regression where testing the app until the last computed record had no
solo `recommended_target_id` made the dashboard's opportunity disappear."""
from __future__ import annotations

from app.data.loader import get_workload
from app.engine.decision import run_decision
from app.engine.estate import compute_estate_summary
from app.models import ScenarioParams, ScenarioType
from app.state import DecisionStore


def _seed_canonical(store: DecisionStore, workload) -> None:
    record = run_decision(
        workload,
        record_id=store.next_id(),
        scenario=ScenarioParams(type=ScenarioType.normal, label="Normal — baseline, no scenario applied"),
        effective_min_throughput=workload.slo.min_throughput_tokens_per_s,
    )
    store.put(record)
    store.set_canonical(workload.id, record.id)


def test_estate_summary_shows_the_opportunity_on_a_fresh_store():
    store = DecisionStore()
    workload = get_workload("wl-llama70b-rt")
    _seed_canonical(store, workload)

    summary = compute_estate_summary(store)
    insight = next((i for i in summary.insights if i.workload_id == workload.id), None)

    assert insight is not None
    assert insight.current_target_id == "nvidia-h100-dc"
    assert insight.recommended_target_id == "amd-mi300x"
    assert insight.savings_pct > 0
    assert insight.slo_met is True


def test_estate_summary_ignores_later_non_canonical_records():
    store = DecisionStore()
    workload = get_workload("wl-llama70b-rt")
    _seed_canonical(store, workload)

    # Simulate a user later running a scenario whose outcome has no solo
    # recommended_target_id (e.g. strict_confidence_policy withholding one,
    # or a demand-spike split) — this becomes the *latest* record for the
    # workload, but must never become what the dashboard shows.
    spike_effective_throughput = workload.slo.min_throughput_tokens_per_s * 3.5
    later = run_decision(
        workload,
        record_id=store.next_id(),
        scenario=ScenarioParams(type=ScenarioType.demand_spike, label="3.5x demand spike"),
        effective_min_throughput=spike_effective_throughput,
    )
    store.put(later)
    assert later.recommended_target_id is None  # confirms this record is the kind that used to break it

    summary = compute_estate_summary(store)
    insight = next((i for i in summary.insights if i.workload_id == workload.id), None)

    assert insight is not None
    assert insight.recommended_target_id == "amd-mi300x"
    assert insight.recommendation_id != later.id
