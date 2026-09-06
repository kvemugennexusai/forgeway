"""Tests for app.qualification.checker — staged qualification checking.
Everything below the checker interface is mocked or fake (subprocess,
discovery adapters); no real hardware or vllm install required.
"""
from __future__ import annotations

from typing import Optional
from unittest.mock import patch

from app.benchmark.gpu_sampler import GpuSample
from app.benchmark.vllm_runner import RawBenchmarkResult
from app.core.schemas import ComputeTarget, Metric
from app.core.schemas.v0_1 import PerformanceEvidence
from app.core.schemas.v0_1.qualification import QualificationStageResult, QualificationSubject
from app.core.schemas.workload import SLO
from app.discovery.adapter import DiscoveryAdapter
from app.qualification.checker import RuntimeChecker, VllmRuntimeChecker, run_qualification_pipeline

_FAKE_RAW = RawBenchmarkResult(
    raw_json={"avg_latency": 0.1, "percentiles": {"50": 0.09, "99": 0.12}},
    gpu_samples=[GpuSample(power_draw_w=200.0, memory_used_mb=8000.0)],
    cmd=["vllm", "bench", "latency"],
)


def _subject(**overrides) -> QualificationSubject:
    base = dict(
        vendor="nvidia",
        hardware_model="Test GPU",
        architecture="hopper",
        runtime="vllm",
        model="meta-llama/Llama-3.1-8B-Instruct",
        precision="bf16",
        workload_class="realtime-inference",
    )
    base.update(overrides)
    return QualificationSubject(**base)


def _target(**overrides) -> ComputeTarget:
    base = dict(
        id="local-nvidia-test",
        vendor="nvidia",
        model="Test GPU",
        tier="lab",
        location="local (test-host)",
        architecture="hopper",
        memory_gb_per_device=80.0,
        interconnect="not probed",
        supported_precisions=[],
        capacity_units_total=1,
        capacity_units_allocated=0,
        price_per_hr_per_unit=Metric(value=0.0, confidence=0, provenance="MODELED", source="test"),
        status="healthy",
    )
    base.update(overrides)
    return ComputeTarget(**base)


class _WorkingAdapter(DiscoveryAdapter):
    name = "Fake-Working"

    def __init__(self, target: ComputeTarget):
        self._target = target

    def is_available(self) -> bool:
        return True

    def discover(self) -> ComputeTarget:
        return self._target


class _UnavailableAdapter(DiscoveryAdapter):
    name = "Fake-Unavailable"

    def is_available(self) -> bool:
        return False

    def discover(self) -> ComputeTarget:  # pragma: no cover - never reached
        raise AssertionError


# --------------------------------------------------------------------------
# VllmRuntimeChecker — each stage in isolation
# --------------------------------------------------------------------------


def test_runtime_present_true_when_vllm_available():
    with patch("app.qualification.checker.is_vllm_available", return_value=True):
        result = VllmRuntimeChecker().runtime_present()
    assert result.stage == "runtime_present"
    assert result.passed is True


def test_runtime_present_false_when_vllm_missing():
    with patch("app.qualification.checker.is_vllm_available", return_value=False):
        result = VllmRuntimeChecker().runtime_present()
    assert result.passed is False
    assert "not installed" in result.detail


def test_device_reachable_true_when_matching_vendor_discovered():
    checker = VllmRuntimeChecker(adapters=[_WorkingAdapter(_target())])
    result = checker.device_reachable(_subject(), _target())
    assert result.stage == "device_reachable"
    assert result.passed is True


def test_device_reachable_false_when_no_adapter_finds_anything():
    checker = VllmRuntimeChecker(adapters=[_UnavailableAdapter()])
    result = checker.device_reachable(_subject(), _target())
    assert result.passed is False


def test_device_reachable_false_when_only_a_different_vendor_is_found():
    checker = VllmRuntimeChecker(adapters=[_WorkingAdapter(_target(vendor="amd", id="local-amd-test"))])
    result = checker.device_reachable(_subject(vendor="nvidia"), _target(vendor="nvidia"))
    assert result.passed is False


def test_config_supported_fails_when_tensor_parallel_exceeds_device_count():
    checker = VllmRuntimeChecker()
    subject = _subject(deployment_config={"tensor_parallel_degree": 4})
    result = checker.config_supported(subject, _target(capacity_units_total=1))
    assert result.passed is False
    assert "tensor_parallel_degree=4" in result.detail


def test_config_supported_passes_for_a_known_precision_and_fitting_tensor_parallel():
    checker = VllmRuntimeChecker()
    result = checker.config_supported(_subject(precision="bf16"), _target(capacity_units_total=2))
    assert result.passed is True
    assert "does not guarantee runtime acceptance" in result.detail


def test_config_supported_passes_but_notes_unmapped_precision_honestly():
    checker = VllmRuntimeChecker()
    result = checker.config_supported(_subject(precision="int4-awq"), _target())
    assert result.passed is True
    assert "no known --dtype mapping" in result.detail


def test_smoke_test_succeeds_and_saves_real_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path))
    checker = VllmRuntimeChecker()
    with patch("app.qualification.checker.run_vllm_bench_latency", return_value=_FAKE_RAW):
        result, evidence = checker.smoke_test(_subject(), _target())

    assert result.passed is True
    assert evidence is not None
    assert evidence.provenance == "MEASURED"
    saved = list(tmp_path.glob("qual-smoke-*.json"))
    assert len(saved) == 1


def test_smoke_test_reports_benchmark_error_without_crashing():
    from app.benchmark.errors import BenchmarkError

    checker = VllmRuntimeChecker()
    with patch("app.qualification.checker.run_vllm_bench_latency", side_effect=BenchmarkError("vllm crashed")):
        result, evidence = checker.smoke_test(_subject(), _target())

    assert result.passed is False
    assert "vllm crashed" in result.detail
    assert evidence is None


# --------------------------------------------------------------------------
# run_qualification_pipeline() — orchestration, via a fully controllable
# fake checker (decoupled from VllmRuntimeChecker's own stage logic).
# --------------------------------------------------------------------------


class _FakeChecker(RuntimeChecker):
    runtime = "fake"

    def __init__(self, *, fail_at: Optional[str] = None, evidence: Optional[PerformanceEvidence] = None):
        self._fail_at = fail_at
        self._evidence = evidence
        self.calls: list[str] = []

    def _result(self, stage: str) -> QualificationStageResult:
        self.calls.append(stage)
        return QualificationStageResult(stage=stage, passed=stage != self._fail_at, detail=f"{stage} attempted")

    def runtime_present(self) -> QualificationStageResult:
        return self._result("runtime_present")

    def device_reachable(self, subject, target) -> QualificationStageResult:
        return self._result("device_reachable")

    def config_supported(self, subject, target) -> QualificationStageResult:
        return self._result("config_supported")

    def smoke_test(self, subject, target):
        result = self._result("smoke_test_passed")
        return result, (self._evidence if result.passed else None)


def _evidence(**overrides) -> PerformanceEvidence:
    base = dict(
        compute_target_id="local-nvidia-test",
        workload_id="meta-llama/Llama-3.1-8B-Instruct",
        metrics={
            "end_to_end_latency_ms": Metric(value=100.0, confidence=95, provenance="MEASURED", source="test"),
            "output_token_throughput_tokens_per_s": Metric(
                value=200.0, confidence=95, provenance="MEASURED", source="test"
            ),
        },
        provenance="MEASURED",
        confidence=95.0,
        source="test",
        benchmark_run_id="qual-smoke-abc123",
    )
    base.update(overrides)
    return PerformanceEvidence(**base)


def test_pipeline_stops_at_first_failing_stage_runtime_present():
    checker = _FakeChecker(fail_at="runtime_present")
    record = run_qualification_pipeline(checker, _subject(), _target(), source="s", environment="e")
    assert record.state == "unknown"
    assert checker.calls == ["runtime_present"]
    assert len(record.stages) == 1


def test_pipeline_stops_at_first_failing_stage_device_reachable():
    checker = _FakeChecker(fail_at="device_reachable")
    record = run_qualification_pipeline(checker, _subject(), _target(), source="s", environment="e")
    assert record.state == "unknown"
    assert checker.calls == ["runtime_present", "device_reachable"]


def test_plugin_present_alone_does_not_reach_later_stages():
    """The user's explicit requirement: an installed plugin/entry point
    (here, a checker that reports runtime_present=True trivially) proves
    nothing about later stages — device_reachable is still run for real
    and can still fail the whole pipeline."""
    checker = _FakeChecker(fail_at="device_reachable")
    record = run_qualification_pipeline(checker, _subject(), _target(), source="s", environment="e")
    assert record.stages[0].stage == "runtime_present"
    assert record.stages[0].passed is True
    assert record.stages[1].stage == "device_reachable"
    assert record.stages[1].passed is False
    assert record.state == "unknown"


def test_pipeline_never_returns_unsupported_on_any_automated_failure():
    for stage in ["runtime_present", "device_reachable", "config_supported", "smoke_test_passed"]:
        checker = _FakeChecker(fail_at=stage)
        record = run_qualification_pipeline(checker, _subject(), _target(), source="s", environment="e")
        assert record.state != "unsupported"


def test_pipeline_reaches_smoke_tested_with_no_slo():
    checker = _FakeChecker(evidence=_evidence())
    record = run_qualification_pipeline(checker, _subject(), _target(), source="s", environment="e")
    assert record.state == "smoke_tested"
    assert record.evidence_reference is None


def test_pipeline_reaches_measured_pass_when_slo_is_met():
    slo = SLO(p99_latency_ms=200, min_throughput_tokens_per_s=100, availability_pct=99.0)
    checker = _FakeChecker(evidence=_evidence())
    record = run_qualification_pipeline(
        checker, _subject(slo=slo), _target(), source="s", environment="e"
    )
    assert record.state == "measured_pass"
    assert record.evidence_reference == "qual-smoke-abc123"


def test_pipeline_reaches_measured_fail_when_slo_is_not_met():
    slo = SLO(p99_latency_ms=50, min_throughput_tokens_per_s=1000, availability_pct=99.0)
    checker = _FakeChecker(evidence=_evidence())
    record = run_qualification_pipeline(
        checker, _subject(slo=slo), _target(), source="s", environment="e"
    )
    assert record.state == "measured_fail"
    assert record.evidence_reference == "qual-smoke-abc123"
