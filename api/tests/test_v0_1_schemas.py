"""Validation tests for the forgeway/v0.1 data contracts
(app.core.schemas.v0_1): ComputeTarget, AIWorkload, PerformanceEvidence,
PlacementDecision.

Three concerns:
  1. Every REAL fixture row loads into the versioned schema without loss —
     proving forgeway/v0.1 is compatible with the current demo's data.
  2. PerformanceEvidence.from_performance_profile() and
     PlacementDecision.from_candidates() correctly reflect the real
     decisions this demo already makes (cross-checked against the
     behavioral assertions in tests/test_engine.py).
  3. examples/*.json actually validate against these schemas, so they
     can't silently drift from what the code produces.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.engine.feasibility import evaluate_feasibility
from app.core.engine.ranking import normalize_and_weight
from app.core.engine.scoring import score_candidate
from app.core.schemas import CandidateEvaluation, PredictedOutcome
from app.core.schemas.v0_1 import (
    SCHEMA_VERSION,
    AIWorkload,
    ComputeTarget,
    PerformanceEvidence,
    PlacementDecision,
)
from app.data.loader import (
    get_performance_profile,
    get_workload,
    load_compute_targets,
    load_performance_profiles,
    load_workloads,
)

# --------------------------------------------------------------------------
# ComputeTarget / AIWorkload — every real fixture row loads cleanly.
# --------------------------------------------------------------------------


def test_every_fixture_compute_target_loads_as_v0_1():
    for target in load_compute_targets():
        assert target.schema_version == SCHEMA_VERSION
        assert target.accelerator_count == target.capacity_units_total
        assert target.runtime_support is None  # not known, not "known to be empty"


def test_every_fixture_workload_loads_as_v0_1_ai_workload():
    for workload in load_workloads():
        assert isinstance(workload, AIWorkload)
        assert workload.schema_version == SCHEMA_VERSION


def test_ai_workload_is_the_same_class_as_workload():
    from app.core.schemas import Workload

    assert AIWorkload is Workload


def test_compute_target_and_ai_workload_round_trip_through_json():
    target = load_compute_targets()[0]
    assert ComputeTarget.model_validate_json(target.model_dump_json()) == target

    workload = load_workloads()[0]
    assert AIWorkload.model_validate_json(workload.model_dump_json()) == workload


# --------------------------------------------------------------------------
# PerformanceEvidence
# --------------------------------------------------------------------------


def test_every_fixture_performance_profile_converts_to_evidence():
    for profile in load_performance_profiles():
        evidence = PerformanceEvidence.from_performance_profile(profile)
        assert evidence.schema_version == SCHEMA_VERSION
        assert evidence.compute_target_id == profile.target_id
        assert evidence.workload_id == profile.workload_id
        assert set(evidence.metrics) == {
            "throughput_tokens_per_s_per_replica",
            "p99_latency_ms_per_replica",
        }
        assert evidence.confidence == min(
            profile.throughput_tokens_per_s_per_replica.confidence,
            profile.p99_latency_ms_per_replica.confidence,
        )
        assert evidence.timestamp is None  # not recorded in today's fixtures
        assert evidence.benchmark_run_id is None


def test_evidence_provenance_is_the_weakest_link():
    profile = get_performance_profile("wl-llama70b-rt", "amd-mi300x")
    assert profile is not None
    assert profile.throughput_tokens_per_s_per_replica.provenance == "MODELED"

    evidence = PerformanceEvidence.from_performance_profile(profile)
    assert evidence.provenance == "MODELED"


def test_evidence_round_trips_through_json():
    profile = load_performance_profiles()[0]
    evidence = PerformanceEvidence.from_performance_profile(profile)
    assert PerformanceEvidence.model_validate_json(evidence.model_dump_json()) == evidence


# --------------------------------------------------------------------------
# PlacementDecision — built from the real core pipeline, real fixtures, for
# the same workload tests/test_engine.py already establishes behavior for.
# --------------------------------------------------------------------------


def _ranked_candidates(workload, *, min_confidence_pct: float | None = None):
    """Runs the same core steps app.engine.decision.run_decision() runs
    (feasibility -> scoring -> confidence gate -> ranking) directly against
    app.core.engine, independent of the product orchestrator, so this test
    proves the *core* pipeline's output is what PlacementDecision expects."""
    effective_min_confidence = (
        min_confidence_pct if min_confidence_pct is not None else workload.min_confidence_pct
    )
    targets = load_compute_targets()
    targets_by_id = {t.id: t for t in targets}
    candidates = []
    for target in targets:
        checks = evaluate_feasibility(workload, target)
        profile = get_performance_profile(workload.id, target.id)
        candidate = score_candidate(
            workload=workload,
            target=target,
            profile=profile,
            checks=checks,
            required_throughput=workload.slo.min_throughput_tokens_per_s,
            free_capacity_units=target.free_capacity_units,
        )
        candidates.append(candidate)

    slo_compliant = [c for c in candidates if c.feasible and c.predicted and c.predicted.meets_slo]
    for c in slo_compliant:
        c.meets_confidence_requirement = (c.confidence_pct or 0) >= effective_min_confidence
    qualifying = [c for c in slo_compliant if c.meets_confidence_requirement]
    normalize_and_weight(qualifying, workload, {}, targets_by_id)
    qualifying.sort(key=lambda c: c.weighted_score or 0.0, reverse=True)
    for rank, c in enumerate(qualifying, start=1):
        c.rank = rank
    return candidates


def test_placement_decision_matches_the_known_baseline_recommendation():
    """Cross-checked against tests/test_engine.py::test_baseline_recommends_mi300x_over_h100
    and test_hard_checks_reject_incompatible_targets_with_distinct_reasons."""
    workload = get_workload("wl-llama70b-rt")
    assert workload is not None
    candidates = _ranked_candidates(workload)

    decision = PlacementDecision.from_candidates(workload, candidates)

    assert decision.schema_version == SCHEMA_VERSION
    assert decision.workload_id == "wl-llama70b-rt"
    assert decision.recommended_target_id == "amd-mi300x"
    assert "amd-mi300x" in decision.feasible_targets
    assert "nvidia-h100-dc" in decision.feasible_targets

    rejected_by_id = {r.target_id: r for r in decision.rejected_targets}
    for target_id in ["intel-gaudi3", "aws-trainium2", "nvidia-l40s", "nvidia-jetson-thor", "local-nvidia-lab"]:
        assert target_id in rejected_by_id
        assert rejected_by_id[target_id].reasons

    assert "amd-mi300x" in decision.score_breakdown
    assert decision.confidence is not None and decision.confidence > 0

    assert decision.improvement_vs_current_placement is not None
    assert decision.improvement_vs_current_placement.current_target_id == "nvidia-h100-dc"
    assert decision.improvement_vs_current_placement.cost_savings_pct > 0

    assert decision.evidence_references


def test_placement_decision_withholds_recommendation_when_none_qualifies():
    """Mirrors test_engine.py's confidence-threshold behavior: raising the
    bar can leave no target ranked, and from_candidates() must reflect that
    with recommended_target_id=None rather than inventing one."""
    workload = get_workload("wl-llama70b-rt")
    assert workload is not None
    candidates = _ranked_candidates(workload, min_confidence_pct=99.9)

    decision = PlacementDecision.from_candidates(workload, candidates)
    assert decision.recommended_target_id is None
    assert decision.confidence is None
    assert decision.improvement_vs_current_placement is None


def _bare_qualifying_candidate(**overrides) -> CandidateEvaluation:
    base = dict(
        target_id="t-x",
        target_label="Test Target",
        vendor="test",
        feasible=True,
        checks=[],
        predicted=PredictedOutcome(
            replica_count=1,
            throughput_tokens_per_s_total=100,
            p99_latency_ms=100,
            cost_per_hr=1.0,
            meets_slo=True,
            provenance="MEASURED",
        ),
    )
    base.update(overrides)
    return CandidateEvaluation(**base)


def test_from_candidates_rejects_a_candidate_the_confidence_gate_never_ran_on():
    """A feasible, SLO-compliant candidate with meets_confidence_requirement
    still None means the caller skipped the confidence-gate step — that
    must fail loudly, not be silently read as "doesn't qualify"."""
    workload = get_workload("wl-llama70b-rt")
    assert workload is not None
    candidate = _bare_qualifying_candidate()  # meets_confidence_requirement left None

    with pytest.raises(ValueError, match="confidence gate"):
        PlacementDecision.from_candidates(workload, [candidate])


def test_from_candidates_rejects_a_qualifying_candidate_that_was_never_ranked():
    """A candidate that passed the confidence gate but has no rank means the
    caller skipped the ranking step — same treatment as above."""
    workload = get_workload("wl-llama70b-rt")
    assert workload is not None
    candidate = _bare_qualifying_candidate(meets_confidence_requirement=True)  # rank left None

    with pytest.raises(ValueError, match="ranking"):
        PlacementDecision.from_candidates(workload, [candidate])


def test_placement_decision_round_trips_through_json():
    workload = get_workload("wl-llama70b-rt")
    assert workload is not None
    candidates = _ranked_candidates(workload)
    decision = PlacementDecision.from_candidates(workload, candidates)
    assert PlacementDecision.model_validate_json(decision.model_dump_json()) == decision


# --------------------------------------------------------------------------
# examples/*.json — must actually validate, so they can't silently drift
# from what these schemas produce.
# --------------------------------------------------------------------------

_EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"


def test_examples_directory_exists():
    assert _EXAMPLES_DIR.is_dir(), f"expected {_EXAMPLES_DIR} to exist"


def test_compute_target_example_validates():
    raw = (_EXAMPLES_DIR / "compute_target.v0_1.json").read_text()
    target = ComputeTarget.model_validate_json(raw)
    assert target.schema_version == SCHEMA_VERSION
    assert target.id == "nvidia-h100-dc"


def test_ai_workload_example_validates():
    raw = (_EXAMPLES_DIR / "ai_workload.v0_1.json").read_text()
    workload = AIWorkload.model_validate_json(raw)
    assert workload.schema_version == SCHEMA_VERSION
    assert workload.id == "wl-llama70b-rt"


def test_performance_evidence_example_validates():
    raw = (_EXAMPLES_DIR / "performance_evidence.v0_1.json").read_text()
    evidence = PerformanceEvidence.model_validate_json(raw)
    assert evidence.schema_version == SCHEMA_VERSION
    assert evidence.provenance == "MEASURED"


def test_placement_decision_example_validates():
    raw = (_EXAMPLES_DIR / "placement_decision.v0_1.json").read_text()
    decision = PlacementDecision.model_validate_json(raw)
    assert decision.schema_version == SCHEMA_VERSION
    assert decision.recommended_target_id == "amd-mi300x"
