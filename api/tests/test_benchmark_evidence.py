"""Tests for app.benchmark.evidence — pure function, no mocking needed:
plain ParsedLatencyResult + GpuSample objects in, PerformanceEvidence out.
"""
from __future__ import annotations

from app.benchmark.evidence import build_performance_evidence
from app.benchmark.gpu_sampler import GpuSample
from app.benchmark.parser import ParsedLatencyResult
from app.core.schemas import ComputeTarget, Metric
from app.core.schemas.v0_1 import SCHEMA_VERSION


def _compute_target(**overrides) -> ComputeTarget:
    base = dict(
        id="local-nvidia-test-host",
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


def test_build_performance_evidence_computes_latency_and_derived_throughput():
    target = _compute_target()
    parsed = ParsedLatencyResult(avg_latency_s=2.0, percentiles_s={})

    evidence = build_performance_evidence(
        compute_target=target,
        model="meta-llama/Llama-3.1-8B-Instruct",
        input_tokens=512,
        output_tokens=128,
        concurrency=1,
        parsed=parsed,
        gpu_samples=[],
        run_id="bench-test0001",
    )

    assert evidence.schema_version == SCHEMA_VERSION
    assert evidence.provenance == "MEASURED"
    assert evidence.compute_target_id == "local-nvidia-test-host"
    assert evidence.workload_id == "meta-llama/Llama-3.1-8B-Instruct"
    assert evidence.benchmark_run_id == "bench-test0001"

    assert evidence.metrics["end_to_end_latency_ms"].value == 2000.0
    # output_tokens(128) * concurrency(1) / avg_latency_s(2.0) = 64 tok/s
    assert evidence.metrics["output_token_throughput_tokens_per_s"].value == 64.0
    # concurrency(1) / avg_latency_s(2.0) = 0.5 req/s
    assert evidence.metrics["request_throughput_requests_per_s"].value == 0.5

    assert "peak_gpu_memory_used_mb" not in evidence.metrics
    assert "avg_gpu_power_draw_w" not in evidence.metrics
    assert "p50_latency_ms" not in evidence.metrics


def test_build_performance_evidence_includes_percentiles_when_present():
    target = _compute_target()
    parsed = ParsedLatencyResult(avg_latency_s=1.0, percentiles_s={"50": 0.9, "99": 1.3})

    evidence = build_performance_evidence(
        compute_target=target,
        model="m",
        input_tokens=100,
        output_tokens=10,
        concurrency=1,
        parsed=parsed,
        gpu_samples=[],
        run_id="r",
    )

    assert evidence.metrics["p50_latency_ms"].value == 900.0
    assert evidence.metrics["p99_latency_ms"].value == 1300.0


def test_build_performance_evidence_aggregates_gpu_samples():
    target = _compute_target()
    parsed = ParsedLatencyResult(avg_latency_s=1.0, percentiles_s={})
    samples = [
        GpuSample(power_draw_w=100.0, memory_used_mb=1000.0),
        GpuSample(power_draw_w=200.0, memory_used_mb=2000.0),
        GpuSample(power_draw_w=None, memory_used_mb=1500.0),  # power unavailable this sample
    ]

    evidence = build_performance_evidence(
        compute_target=target,
        model="m",
        input_tokens=10,
        output_tokens=10,
        concurrency=1,
        parsed=parsed,
        gpu_samples=samples,
        run_id="r",
    )

    assert evidence.metrics["peak_gpu_memory_used_mb"].value == 2000.0
    # average of only the two non-None power samples: (100+200)/2 = 150
    assert evidence.metrics["avg_gpu_power_draw_w"].value == 150.0


def test_build_performance_evidence_omits_gpu_metrics_when_no_samples_succeeded():
    target = _compute_target()
    parsed = ParsedLatencyResult(avg_latency_s=1.0, percentiles_s={})
    samples = [GpuSample(power_draw_w=None, memory_used_mb=None)]

    evidence = build_performance_evidence(
        compute_target=target,
        model="m",
        input_tokens=10,
        output_tokens=10,
        concurrency=1,
        parsed=parsed,
        gpu_samples=samples,
        run_id="r",
    )

    assert "peak_gpu_memory_used_mb" not in evidence.metrics
    assert "avg_gpu_power_draw_w" not in evidence.metrics


def test_confidence_is_the_weakest_link_across_included_metrics():
    target = _compute_target()
    parsed = ParsedLatencyResult(avg_latency_s=1.0, percentiles_s={})
    samples = [GpuSample(power_draw_w=100.0, memory_used_mb=1000.0)]

    evidence = build_performance_evidence(
        compute_target=target,
        model="m",
        input_tokens=10,
        output_tokens=10,
        concurrency=1,
        parsed=parsed,
        gpu_samples=samples,
        run_id="r",
    )

    # power sampling has the lowest confidence convention (85) of anything included
    assert evidence.confidence == 85.0


def test_evidence_round_trips_through_json():
    target = _compute_target()
    parsed = ParsedLatencyResult(avg_latency_s=1.0, percentiles_s={"50": 0.9})
    evidence = build_performance_evidence(
        compute_target=target,
        model="m",
        input_tokens=10,
        output_tokens=10,
        concurrency=1,
        parsed=parsed,
        gpu_samples=[GpuSample(power_draw_w=100.0, memory_used_mb=1000.0)],
        run_id="r",
    )
    from app.core.schemas.v0_1 import PerformanceEvidence

    assert PerformanceEvidence.model_validate_json(evidence.model_dump_json()) == evidence
