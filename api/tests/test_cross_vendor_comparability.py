"""Tests for app.benchmark.cross_vendor.compare_evidence — the comparability
policy. Pure-function tests, plain Python objects only, no subprocess/GPU.
"""
from __future__ import annotations

from app.benchmark.cross_vendor import (
    BenchmarkProfile,
    ComparabilityKey,
    CrossVendorEvidenceRecord,
    EnvironmentInfo,
    compare_evidence,
    display_status,
)
from app.core.schemas import ComputeTarget, Metric
from app.core.schemas.v0_1 import PerformanceEvidence


def _profile(**overrides) -> BenchmarkProfile:
    base = dict(
        profile_id="test-profile",
        profile_version="0.1",
        model="meta-llama/Llama-3.1-8B-Instruct",
        precision="bf16",
        input_tokens=512,
        output_tokens=128,
        concurrency=1,
        batch_behavior="static single-request batches",
        warmup_runs=1,
        measured_runs=3,
    )
    base.update(overrides)
    return BenchmarkProfile(**base)


def _target(vendor: str = "nvidia", accelerator_count: int = 1, **overrides) -> ComputeTarget:
    base = dict(
        id=f"local-{vendor}-test",
        vendor=vendor,
        model=f"Test {vendor.upper()} GPU",
        tier="lab",
        location="local (test-host)",
        architecture="test-arch",
        memory_gb_per_device=80.0,
        interconnect="not probed",
        supported_precisions=[],
        capacity_units_total=accelerator_count,
        capacity_units_allocated=0,
        price_per_hr_per_unit=Metric(value=0.0, confidence=0, provenance="MODELED", source="test"),
        status="healthy",
    )
    base.update(overrides)
    return ComputeTarget(**base)


def _environment(**overrides) -> EnvironmentInfo:
    base = dict(
        runtime_version="0.9.0",
        torch_version="2.5.0",
        os="Linux",
        kernel="6.8.0",
        cpu_model="Test CPU",
        driver_version="550.90.07",
    )
    base.update(overrides)
    return EnvironmentInfo(**base)


def _evidence(target_id: str, **overrides) -> PerformanceEvidence:
    base = dict(
        compute_target_id=target_id,
        workload_id="wl-test",
        metrics={},
        provenance="MEASURED",
        confidence=95.0,
        source="test",
    )
    base.update(overrides)
    return PerformanceEvidence(**base)


def _record(
    *,
    vendor: str = "nvidia",
    profile: BenchmarkProfile | None = None,
    environment: EnvironmentInfo | None = None,
    target: ComputeTarget | None = None,
    evidence: PerformanceEvidence | None = None,
) -> CrossVendorEvidenceRecord:
    profile = profile or _profile()
    target = target or _target(vendor=vendor)
    return CrossVendorEvidenceRecord(
        run_id=f"run-{vendor}",
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
        target=target,
        environment=environment or _environment(),
        performance_evidence=evidence or _evidence(target.id),
        comparability_key=ComparabilityKey.from_profile(profile),
    )


# --------------------------------------------------------------------------
# COMPARABLE
# --------------------------------------------------------------------------


def test_identical_profile_and_environment_across_vendors_is_comparable():
    a = _record(vendor="nvidia")
    b = _record(vendor="amd")
    verdict = compare_evidence(a, b)
    assert verdict.status == "COMPARABLE"
    assert verdict.reasons == []
    assert display_status(verdict.status) == "DIRECTLY COMPARABLE"


# --------------------------------------------------------------------------
# NOT_COMPARABLE — critical dimension mismatches
# --------------------------------------------------------------------------


def test_precision_mismatch_is_not_comparable():
    a = _record(vendor="nvidia", profile=_profile(precision="bf16"))
    b = _record(vendor="amd", profile=_profile(precision="fp16"))
    verdict = compare_evidence(a, b)
    assert verdict.status == "NOT_COMPARABLE"
    assert any("precision differs" in r for r in verdict.reasons)


def test_concurrency_mismatch_is_not_comparable():
    a = _record(vendor="nvidia", profile=_profile(concurrency=8))
    b = _record(vendor="amd", profile=_profile(concurrency=32))
    verdict = compare_evidence(a, b)
    assert verdict.status == "NOT_COMPARABLE"
    assert any("concurrency differs" in r for r in verdict.reasons)


def test_tensor_parallel_degree_mismatch_is_not_comparable():
    a = _record(vendor="nvidia", profile=_profile(tensor_parallel_degree=1))
    b = _record(vendor="amd", profile=_profile(tensor_parallel_degree=2))
    verdict = compare_evidence(a, b)
    assert verdict.status == "NOT_COMPARABLE"
    assert any("tensor parallel degree differs" in r for r in verdict.reasons)


def test_quantization_mismatch_is_not_comparable():
    a = _record(vendor="nvidia", profile=_profile(quantization=None))
    b = _record(vendor="amd", profile=_profile(quantization="fp8"))
    verdict = compare_evidence(a, b)
    assert verdict.status == "NOT_COMPARABLE"
    assert any("quantization differs" in r for r in verdict.reasons)


def test_model_revision_presence_mismatch_is_not_comparable():
    a = _record(vendor="nvidia", profile=_profile(model_revision=None))
    b = _record(vendor="amd", profile=_profile(model_revision="abc123"))
    verdict = compare_evidence(a, b)
    assert verdict.status == "NOT_COMPARABLE"
    assert any("model revision differs" in r for r in verdict.reasons)


def test_model_mismatch_is_not_comparable():
    a = _record(vendor="nvidia", profile=_profile(model="meta-llama/Llama-3.1-8B-Instruct"))
    b = _record(vendor="amd", profile=_profile(model="Qwen/Qwen2.5-7B-Instruct"))
    verdict = compare_evidence(a, b)
    assert verdict.status == "NOT_COMPARABLE"
    assert any(r.startswith("model differs") for r in verdict.reasons)


def test_token_count_mismatch_is_not_comparable():
    a = _record(vendor="nvidia", profile=_profile(input_tokens=512))
    b = _record(vendor="amd", profile=_profile(input_tokens=1024))
    verdict = compare_evidence(a, b)
    assert verdict.status == "NOT_COMPARABLE"
    assert any("input token count differs" in r for r in verdict.reasons)


def test_different_profile_id_is_not_comparable():
    a = _record(vendor="nvidia", profile=_profile(profile_id="profile-a"))
    b = _record(vendor="amd", profile=_profile(profile_id="profile-b"))
    verdict = compare_evidence(a, b)
    assert verdict.status == "NOT_COMPARABLE"
    assert any("benchmark profile id differs" in r for r in verdict.reasons)


def test_multiple_critical_mismatches_are_all_reported():
    a = _record(vendor="nvidia", profile=_profile(precision="bf16", concurrency=1))
    b = _record(vendor="amd", profile=_profile(precision="fp16", concurrency=8))
    verdict = compare_evidence(a, b)
    assert verdict.status == "NOT_COMPARABLE"
    assert len(verdict.reasons) == 2
    assert any("precision" in r for r in verdict.reasons)
    assert any("concurrency" in r for r in verdict.reasons)


# --------------------------------------------------------------------------
# PARTIALLY_COMPARABLE — soft dimension mismatches only
# --------------------------------------------------------------------------


def test_runtime_version_mismatch_alone_is_partially_comparable():
    a = _record(vendor="nvidia", environment=_environment(runtime_version="0.9.0"))
    b = _record(vendor="amd", environment=_environment(runtime_version="0.9.2"))
    verdict = compare_evidence(a, b)
    assert verdict.status == "PARTIALLY_COMPARABLE"
    assert any("runtime" in r and "version differs" in r for r in verdict.reasons)
    assert display_status(verdict.status) == "PARTIALLY COMPARABLE"


def test_driver_version_mismatch_alone_is_partially_comparable():
    a = _record(vendor="nvidia", environment=_environment(driver_version="550.90.07"))
    b = _record(vendor="amd", environment=_environment(driver_version="551.00.01"))
    verdict = compare_evidence(a, b)
    assert verdict.status == "PARTIALLY_COMPARABLE"
    assert any("driver version differs" in r for r in verdict.reasons)


def test_accelerator_count_mismatch_alone_is_partially_comparable():
    a = _record(vendor="nvidia", target=_target(vendor="nvidia", accelerator_count=1))
    b = _record(vendor="amd", target=_target(vendor="amd", accelerator_count=2))
    verdict = compare_evidence(a, b)
    assert verdict.status == "PARTIALLY_COMPARABLE"
    assert any("accelerator count differs" in r for r in verdict.reasons)


def test_critical_mismatch_takes_precedence_over_soft_mismatch():
    """A profile-level (critical) mismatch is reported as NOT_COMPARABLE
    even when a soft dimension also differs — soft reasons are only
    computed once every critical dimension already matches."""
    a = _record(
        vendor="nvidia",
        profile=_profile(precision="bf16"),
        environment=_environment(driver_version="550.90.07"),
    )
    b = _record(
        vendor="amd",
        profile=_profile(precision="fp16"),
        environment=_environment(driver_version="551.00.01"),
    )
    verdict = compare_evidence(a, b)
    assert verdict.status == "NOT_COMPARABLE"
    assert not any("driver version" in r for r in verdict.reasons)


# --------------------------------------------------------------------------
# Evidence quality: missing metrics and provenance preserved, never guessed
# --------------------------------------------------------------------------


def test_missing_metric_on_one_side_does_not_change_comparability():
    a = _record(vendor="nvidia", evidence=_evidence("local-nvidia-test", metrics={
        "end_to_end_latency_ms": Metric(value=100.0, confidence=95, provenance="MEASURED", source="test"),
        "avg_gpu_power_draw_w": Metric(value=300.0, confidence=85, provenance="MEASURED", source="test"),
    }))
    b = _record(vendor="amd", evidence=_evidence("local-amd-test", metrics={
        "end_to_end_latency_ms": Metric(value=110.0, confidence=95, provenance="MEASURED", source="test"),
        # no avg_gpu_power_draw_w on this side — e.g. power telemetry unavailable
    }))
    verdict = compare_evidence(a, b)
    assert verdict.status == "COMPARABLE"
    assert "avg_gpu_power_draw_w" not in b.performance_evidence.metrics  # preserved as missing, not fabricated


def test_provenance_is_preserved_as_measured():
    record = _record(vendor="nvidia", evidence=_evidence("local-nvidia-test", provenance="MEASURED"))
    assert record.performance_evidence.provenance == "MEASURED"
    assert record.to_performance_evidence().provenance == "MEASURED"


def test_cost_basis_defaults_to_not_available():
    record = _record(vendor="nvidia")
    assert record.cost_basis == "not_available"
