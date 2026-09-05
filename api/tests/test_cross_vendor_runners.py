"""Tests for app.benchmark.cross_vendor's BenchmarkRunner implementations —
CudaVllmBenchmarkRunner / RocmVllmBenchmarkRunner. Only
app.benchmark.vllm_runner.run_vllm_bench_latency is mocked (no real vllm
subprocess); parsing, evidence-building, and environment capture all run
for real, proving normalization actually happens rather than being
asserted about a mock.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.benchmark.cross_vendor import (
    BenchmarkProfile,
    CrossVendorEvidenceRecord,
    CudaVllmBenchmarkRunner,
    ProfileError,
    RocmVllmBenchmarkRunner,
    runner_for_target,
)
from app.benchmark.gpu_sampler import GpuSample
from app.benchmark.vllm_runner import RawBenchmarkResult
from app.core.schemas import ComputeTarget, Metric


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
        tensor_parallel_degree=1,
    )
    base.update(overrides)
    return BenchmarkProfile(**base)


def _target(vendor: str, notes: str = "") -> ComputeTarget:
    return ComputeTarget(
        id=f"local-{vendor}-test",
        vendor=vendor,
        model=f"Test {vendor.upper()} GPU",
        tier="lab",
        location="local (test-host)",
        architecture="test-arch",
        memory_gb_per_device=80.0,
        interconnect="not probed",
        supported_precisions=[],
        capacity_units_total=1,
        capacity_units_allocated=0,
        price_per_hr_per_unit=Metric(value=0.0, confidence=0, provenance="MODELED", source="test"),
        status="healthy",
        notes=notes,
    )


_FAKE_RAW = RawBenchmarkResult(
    raw_json={"avg_latency": 0.5, "percentiles": {"50": 0.4, "99": 0.6}},
    gpu_samples=[GpuSample(power_draw_w=250.0, memory_used_mb=16000.0)],
    cmd=["vllm", "bench", "latency", "--model", "meta-llama/Llama-3.1-8B-Instruct"],
)


def test_cuda_runner_produces_measured_evidence_with_correct_schema():
    with patch("app.benchmark.cross_vendor.run_vllm_bench_latency", return_value=_FAKE_RAW) as mock_run:
        record = CudaVllmBenchmarkRunner().run(_profile(), _target("nvidia"), run_id="run-1")

    assert isinstance(record, CrossVendorEvidenceRecord)
    assert record.schema_version == "forgeway-cross-vendor/v0.1"
    assert record.target.vendor == "nvidia"
    assert record.performance_evidence.provenance == "MEASURED"
    assert record.performance_evidence.metrics["end_to_end_latency_ms"].value == 500.0
    assert record.raw_command == _FAKE_RAW.cmd
    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs["gpu_vendor"] == "nvidia"


def test_rocm_runner_produces_measured_evidence_with_correct_schema():
    with patch("app.benchmark.cross_vendor.run_vllm_bench_latency", return_value=_FAKE_RAW) as mock_run:
        record = RocmVllmBenchmarkRunner().run(_profile(), _target("amd"), run_id="run-2")

    assert record.target.vendor == "amd"
    assert record.performance_evidence.provenance == "MEASURED"
    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs["gpu_vendor"] == "amd"


def test_runner_passes_every_profile_field_that_maps_to_a_vllm_flag():
    profile = _profile(
        precision="bf16",
        tensor_parallel_degree=2,
        quantization="fp8",
        max_model_len=4096,
        input_tokens=256,
        output_tokens=64,
        concurrency=4,
        warmup_runs=2,
        measured_runs=5,
        env_vars={"HIP_VISIBLE_DEVICES": "0"},
    )
    with patch("app.benchmark.cross_vendor.run_vllm_bench_latency", return_value=_FAKE_RAW) as mock_run:
        CudaVllmBenchmarkRunner().run(profile, _target("nvidia"), run_id="run-3", device_index=1)

    kwargs = mock_run.call_args.kwargs
    assert kwargs["model"] == "meta-llama/Llama-3.1-8B-Instruct"
    assert kwargs["input_tokens"] == 256
    assert kwargs["output_tokens"] == 64
    assert kwargs["concurrency"] == 4
    assert kwargs["iterations"] == 5
    assert kwargs["warmup_iterations"] == 2
    assert kwargs["device_index"] == 1
    assert kwargs["dtype"] == "bfloat16"
    assert kwargs["tensor_parallel_size"] == 2
    assert kwargs["quantization"] == "fp8"
    assert kwargs["max_model_len"] == 4096
    assert kwargs["env"] == {"HIP_VISIBLE_DEVICES": "0"}


def test_dtype_omitted_for_unmapped_precision():
    profile = _profile(precision="int4-awq")
    with patch("app.benchmark.cross_vendor.run_vllm_bench_latency", return_value=_FAKE_RAW) as mock_run:
        CudaVllmBenchmarkRunner().run(profile, _target("nvidia"), run_id="run-4")
    assert mock_run.call_args.kwargs["dtype"] is None


def test_workload_id_is_threaded_through_to_evidence():
    with patch("app.benchmark.cross_vendor.run_vllm_bench_latency", return_value=_FAKE_RAW):
        record = CudaVllmBenchmarkRunner().run(
            _profile(), _target("nvidia"), run_id="run-5", workload_id="wl-llama70b-rt"
        )
    assert record.performance_evidence.workload_id == "wl-llama70b-rt"


def test_workload_id_defaults_to_model_when_omitted():
    with patch("app.benchmark.cross_vendor.run_vllm_bench_latency", return_value=_FAKE_RAW):
        record = CudaVllmBenchmarkRunner().run(_profile(), _target("nvidia"), run_id="run-6")
    assert record.performance_evidence.workload_id == "meta-llama/Llama-3.1-8B-Instruct"


def test_environment_capture_extracts_driver_version_from_target_notes():
    target = _target("nvidia", notes="Discovered via nvidia-smi. Driver version: 550.90.07. CUDA version: 12.4.")
    with patch("app.benchmark.cross_vendor.run_vllm_bench_latency", return_value=_FAKE_RAW):
        record = CudaVllmBenchmarkRunner().run(_profile(), target, run_id="run-7")
    assert record.environment.driver_version == "550.90.07"


def test_environment_capture_extracts_driver_version_from_real_captured_rocm_notes():
    # Verbatim notes text produced by app.discovery.rocm.RocmDiscoveryAdapter
    # against the real AMD Radeon RX 9070 XT machine (see
    # docs/discovery.md#verification-status) — a regression guard for the
    # "550.90.07" -> "550" truncation bug this test suite caught.
    real_notes = (
        "Discovered via rocm-smi on alloy-amd-01 "
        "(Linux-7.0.0-30-generic-x86_64-with-glibc2.43). Driver version: 7.0.0. "
        "Unique ID: 0x4fbbc7e605b44800. Free device memory — GPU 0: 15.6/15.9 GB free."
    )
    target = _target("amd", notes=real_notes)
    with patch("app.benchmark.cross_vendor.run_vllm_bench_latency", return_value=_FAKE_RAW):
        record = RocmVllmBenchmarkRunner().run(_profile(), target, run_id="run-real-amd")
    assert record.environment.driver_version == "7.0.0"


def test_environment_capture_handles_missing_driver_version_gracefully():
    target = _target("amd", notes="No driver info here.")
    with patch("app.benchmark.cross_vendor.run_vllm_bench_latency", return_value=_FAKE_RAW):
        record = CudaVllmBenchmarkRunner().run(_profile(), target, run_id="run-8")
    assert record.environment.driver_version is None


def test_comparability_key_matches_profile_fields():
    profile = _profile(precision="bf16", concurrency=4, tensor_parallel_degree=2)
    with patch("app.benchmark.cross_vendor.run_vllm_bench_latency", return_value=_FAKE_RAW):
        record = CudaVllmBenchmarkRunner().run(profile, _target("nvidia"), run_id="run-9")
    assert record.comparability_key.precision == "bf16"
    assert record.comparability_key.concurrency == 4
    assert record.comparability_key.tensor_parallel_degree == 2
    assert record.comparability_key.profile_id == profile.profile_id


def test_runner_for_target_dispatches_by_vendor():
    assert isinstance(runner_for_target(_target("nvidia")), CudaVllmBenchmarkRunner)
    assert isinstance(runner_for_target(_target("amd")), RocmVllmBenchmarkRunner)


def test_runner_for_target_raises_for_unsupported_vendor():
    with pytest.raises(ProfileError, match="no benchmark runner registered"):
        runner_for_target(_target("intel"))
