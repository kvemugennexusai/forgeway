"""Unit tests for app.core.schemas.v0_1.qualification — pure data model,
no store/checker/CLI/engine involved yet (WP1 of Phase 2's qualification
records work).
"""
from __future__ import annotations

import pytest

from app.core.schemas.v0_1 import SCHEMA_VERSION
from app.core.schemas.v0_1.qualification import (
    QualificationRecord,
    QualificationStageResult,
    QualificationSubject,
)
from app.core.schemas.workload import SLO


def _subject(**overrides) -> QualificationSubject:
    base = dict(
        vendor="aws",
        hardware_model="Trainium2 (trn2)",
        architecture="trainium2",
        runtime="vllm",
        runtime_version="0.9.0",
        backend="neuron",
        model="meta-llama/Llama-3.1-70B-Instruct",
        precision="fp8",
        deployment_config={},
        workload_class="realtime-inference",
    )
    base.update(overrides)
    return QualificationSubject(**base)


def _slo() -> SLO:
    return SLO(p99_latency_ms=450, min_throughput_tokens_per_s=1800, availability_pct=99.9)


# --------------------------------------------------------------------------
# subject_key() — the databank's identity
# --------------------------------------------------------------------------


def test_subject_key_is_deterministic_for_identical_subjects():
    assert _subject().subject_key() == _subject().subject_key()


def test_subject_key_differs_on_any_field_change():
    base_key = _subject().subject_key()
    assert _subject(precision="bf16").subject_key() != base_key
    assert _subject(runtime_version="0.9.1").subject_key() != base_key
    assert _subject(deployment_config={"tensor_parallel_degree": 2}).subject_key() != base_key


def test_subject_key_treats_none_slo_and_a_set_slo_as_different_subjects():
    """A general 'does this run at all' claim (slo=None) and a
    'does it meet this exact SLO' claim (slo set) are different subjects
    by design — never conflated."""
    without_slo = _subject()
    with_slo = _subject(slo=_slo())
    assert without_slo.subject_key() != with_slo.subject_key()


# --------------------------------------------------------------------------
# QualificationRecord.for_subject() — deterministic id
# --------------------------------------------------------------------------


def test_for_subject_derives_id_from_subject_key():
    subject = _subject()
    record = QualificationRecord.for_subject(
        subject, state="unknown", source="nobody has checked yet", environment="n/a"
    )
    assert record.id == f"qual-{subject.subject_key()}"
    assert record.schema_version == SCHEMA_VERSION


def test_for_subject_is_stable_across_two_equivalent_subjects():
    record_a = QualificationRecord.for_subject(_subject(), state="unknown", source="s", environment="e")
    record_b = QualificationRecord.for_subject(_subject(), state="unknown", source="s", environment="e")
    assert record_a.id == record_b.id


# --------------------------------------------------------------------------
# measured_pass / measured_fail require slo + evidence_reference
# --------------------------------------------------------------------------


@pytest.mark.parametrize("state", ["measured_pass", "measured_fail"])
def test_measured_states_require_evidence_reference(state):
    with pytest.raises(ValueError, match="evidence_reference"):
        QualificationRecord.for_subject(
            _subject(slo=_slo()),
            state=state,
            source="smoke test run qual-run-1",
            environment="test",
        )


@pytest.mark.parametrize("state", ["measured_pass", "measured_fail"])
def test_measured_states_require_an_slo_on_the_subject(state):
    with pytest.raises(ValueError, match="subject.slo"):
        QualificationRecord.for_subject(
            _subject(),  # no slo
            state=state,
            source="smoke test run qual-run-1",
            environment="test",
            evidence_reference="qual-run-1",
        )


@pytest.mark.parametrize("state", ["measured_pass", "measured_fail"])
def test_measured_states_succeed_with_both_present(state):
    record = QualificationRecord.for_subject(
        _subject(slo=_slo()),
        state=state,
        source="smoke test run qual-run-1",
        environment="test",
        evidence_reference="qual-run-1",
    )
    assert record.state == state


@pytest.mark.parametrize("state", ["unknown", "unsupported", "smoke_tested"])
def test_non_measured_states_do_not_require_evidence_or_slo(state):
    record = QualificationRecord.for_subject(
        _subject(), state=state, source="s", environment="e"
    )
    assert record.evidence_reference is None
    assert record.subject.slo is None


# --------------------------------------------------------------------------
# Stages — reported in full, mirroring FeasibilityCheck's convention
# --------------------------------------------------------------------------


def test_record_carries_every_stage_result_not_just_the_first_failure():
    record = QualificationRecord.for_subject(
        _subject(),
        state="unsupported",
        source="vllm is not installed on this machine",
        environment="test",
        stages=[
            QualificationStageResult(stage="runtime_present", passed=False, detail="vllm not on PATH"),
        ],
    )
    assert record.stages[0].stage == "runtime_present"
    assert record.stages[0].passed is False


# --------------------------------------------------------------------------
# Round-trip
# --------------------------------------------------------------------------


def test_record_round_trips_through_json():
    record = QualificationRecord.for_subject(
        _subject(slo=_slo()),
        state="measured_pass",
        source="forgeway qualify",
        environment="local NVIDIA H100, driver 550.90.07",
        evidence_reference="qual-run-1",
        review_date="2027-01-01",
    )
    parsed = QualificationRecord.model_validate_json(record.model_dump_json())
    assert parsed == record
