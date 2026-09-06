"""Tests for app.engine.qualification_check.evaluate_databank_qualification
— the additive, databank-backed feasibility check (WP5 of Phase 2's
qualification records work). Real filesystem I/O against a tmp_path via
FORGEWAY_QUALIFICATION_DIR; app.core.engine.feasibility itself is
untouched by this module (see test_core_isolation.py) and its own
"software: workload class qualified" check (unsupported_workload_classes)
is exercised alongside this one to confirm neither affects the other.
"""
from __future__ import annotations

from datetime import date

from app.core.engine.feasibility import evaluate_feasibility
from app.core.schemas import SLO, ComputeTarget, CurrentPlacement, EnterprisePolicy, Metric, Workload
from app.core.schemas.v0_1.qualification import QualificationRecord
from app.engine.qualification_check import ANY_MODEL, coarse_qualification_subject, evaluate_databank_qualification
from app.qualification import store


def _workload(**overrides) -> Workload:
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
            allowed_vendors=["aws"], denied_vendors=[], allowed_regions=["us-east-1"], budget_ceiling_per_hr=100.0
        ),
        current_placement=CurrentPlacement(
            target_id="t-a", replica_count=1, measured_p99_latency_ms=400,
            measured_throughput_tokens_per_s_per_replica=150, cost_per_hr=2.0, provenance="MEASURED", source="test",
        ),
    )
    base.update(overrides)
    return Workload(**base)


def _target(**overrides) -> ComputeTarget:
    base = dict(
        id="aws-trainium2",
        vendor="aws",
        model="Trainium2 (trn2)",
        tier="datacenter",
        location="us-east-1 (cloud)",
        architecture="trainium2",
        memory_gb_per_device=96,
        interconnect="NeuronLink",
        supported_precisions=["fp16", "bf16"],
        capacity_units_total=20,
        capacity_units_allocated=0,
        price_per_hr_per_unit=Metric(value=1.9, confidence=88, provenance="PUBLISHED", source="test"),
        status="healthy",
    )
    base.update(overrides)
    return ComputeTarget(**base)


def _record(workload: Workload, target: ComputeTarget, **overrides) -> QualificationRecord:
    subject = coarse_qualification_subject(workload, target)
    base = dict(state="unsupported", source="test source", environment="test")
    base.update(overrides)
    return QualificationRecord.for_subject(subject, **base)


# --------------------------------------------------------------------------
# coarse_qualification_subject()
# --------------------------------------------------------------------------


def test_coarse_subject_uses_the_any_model_wildcard():
    subject = coarse_qualification_subject(_workload(), _target())
    assert subject.model == ANY_MODEL
    assert subject.deployment_config == {}
    assert subject.slo is None


# --------------------------------------------------------------------------
# evaluate_databank_qualification()
# --------------------------------------------------------------------------


def test_no_record_passes_and_does_not_block(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path))
    check = evaluate_databank_qualification(_workload(), _target())
    assert check.passed is True
    assert "no qualification record" in check.detail


def test_unsupported_record_fails_and_quotes_its_own_source(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path))
    workload, target = _workload(), _target()
    store.save_qualification(_record(workload, target, state="unsupported", source="Real, citable constraint."))

    check = evaluate_databank_qualification(workload, target)

    assert check.passed is False
    assert check.detail.startswith("Real, citable constraint.")


def test_unknown_record_passes_and_does_not_block(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path))
    workload, target = _workload(), _target()
    store.save_qualification(_record(workload, target, state="unknown", source="nobody has checked"))

    check = evaluate_databank_qualification(workload, target)

    assert check.passed is True
    assert "not yet checked" in check.detail


def test_smoke_tested_record_is_a_passing_signal(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path))
    workload, target = _workload(), _target()
    store.save_qualification(_record(workload, target, state="smoke_tested", source="forgeway qualify"))

    check = evaluate_databank_qualification(workload, target)

    assert check.passed is True
    assert "smoke_tested" in check.detail


def test_stale_unsupported_record_still_fails_but_flags_staleness(tmp_path, monkeypatch):
    """The rule: a stale record means revalidate, never a silent
    rejection — but it also never silently flips an existing rejection
    into an acceptance. The boolean outcome is unchanged; only `detail`
    is annotated."""
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path))
    workload, target = _workload(), _target()
    store.save_qualification(
        _record(workload, target, state="unsupported", source="old claim", review_date=date(2020, 1, 1))
    )

    check = evaluate_databank_qualification(workload, target)

    assert check.passed is False
    assert "old claim" in check.detail
    assert "stale" in check.detail


def test_a_different_workload_class_on_the_same_target_is_not_matched(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path))
    workload, target = _workload(workload_class="realtime-inference"), _target()
    store.save_qualification(_record(workload, target, state="unsupported", source="realtime not qualified"))

    other_workload = _workload(workload_class="batch-inference")
    check = evaluate_databank_qualification(other_workload, target)

    assert check.passed is True


def test_a_config_specific_record_from_a_real_qualify_run_does_not_match_the_coarse_check(tmp_path, monkeypatch):
    """A record with a pinned model/deployment_config (what `forgeway
    qualify` actually produces) is a different, more specific subject —
    deliberately never consulted by this coarse check."""
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path))
    workload, target = _workload(), _target()
    subject = coarse_qualification_subject(workload, target).model_copy(
        update={"model": "meta-llama/Llama-3.1-70B-Instruct", "deployment_config": {"tensor_parallel_degree": 2}}
    )
    store.save_qualification(
        QualificationRecord.for_subject(subject, state="unsupported", source="specific run failed", environment="e")
    )

    check = evaluate_databank_qualification(workload, target)

    assert check.passed is True  # the coarse subject still has no matching record


# --------------------------------------------------------------------------
# Independence from the existing unsupported_workload_classes check
# --------------------------------------------------------------------------


def test_both_checks_run_independently_in_evaluate_feasibility(tmp_path, monkeypatch):
    """evaluate_feasibility() (app.core.engine.feasibility, unaffected by
    this work package) still only reads unsupported_workload_classes;
    evaluate_databank_qualification() is the separate, additive check a
    caller (app.engine.decision) appends to its result."""
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path))
    workload = _workload()
    target = _target(
        unsupported_workload_classes=[
            {"workload_class": "realtime-inference", "reason": "legacy free-text reason"}
        ]
    )

    core_checks = evaluate_feasibility(workload, target)
    databank_check = evaluate_databank_qualification(workload, target)

    legacy_check = next(c for c in core_checks if c.name == "software: workload class qualified")
    assert legacy_check.passed is False
    assert "legacy free-text reason" in legacy_check.detail
    # No databank record exists — the new check passes independently of
    # the legacy one's failure.
    assert databank_check.passed is True
