"""CLI-level tests for `forgeway bench` and `forgeway runs` — everything
below app.cli.main is mocked (discovery, the vllm runner, the parser
receives real but tiny canned JSON), and results are written to a tmp_path
via the FORGEWAY_BENCH_DIR override, never the real ~/.forgeway.
"""
from __future__ import annotations

import json

from app.benchmark.gpu_sampler import GpuSample
from app.benchmark.vllm_runner import RawBenchmarkResult
from app.cli.main import ComputeTarget, main
from app.core.schemas import Metric
from app.core.schemas.v0_1 import PerformanceEvidence
from app.discovery.adapter import DiscoveryError


def _fake_target() -> ComputeTarget:
    return ComputeTarget(
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


def test_bench_reports_no_accelerator_cleanly(monkeypatch, capsys):
    def _raise_discovery_error():
        raise DiscoveryError("No supported accelerator was detected on this machine.")

    monkeypatch.setattr("app.cli.main.run_discovery", lambda: _raise_discovery_error())
    exit_code = main(["bench", "--model", "m"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "No supported accelerator" in captured.err
    assert "Traceback" not in captured.err


def test_bench_reports_benchmark_error_cleanly(monkeypatch, capsys):
    monkeypatch.setattr("app.cli.main.run_discovery", lambda: _fake_target())

    from app.benchmark.errors import BenchmarkError

    def _raise(**kwargs):
        raise BenchmarkError("vllm is not installed or not on PATH.")

    monkeypatch.setattr("app.cli.main.run_vllm_bench_latency", _raise)

    exit_code = main(["bench", "--model", "m"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "vllm is not installed" in captured.err
    assert "Traceback" not in captured.err


def test_bench_json_emits_valid_performance_evidence(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path))
    monkeypatch.setattr("app.cli.main.run_discovery", lambda: _fake_target())
    monkeypatch.setattr(
        "app.cli.main.run_vllm_bench_latency",
        lambda **kwargs: RawBenchmarkResult(
            raw_json={"avg_latency": 0.5, "percentiles": {"50": 0.4, "99": 0.6}},
            gpu_samples=[GpuSample(power_draw_w=150.0, memory_used_mb=8000.0)],
        ),
    )

    exit_code = main(
        [
            "bench",
            "--model",
            "meta-llama/Llama-3.1-8B-Instruct",
            "--input-tokens",
            "512",
            "--output-tokens",
            "128",
            "--concurrency",
            "1",
            "--json",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "forgeway/v0.1"
    assert payload["provenance"] == "MEASURED"
    assert payload["workload_id"] == "meta-llama/Llama-3.1-8B-Instruct"
    assert payload["metrics"]["end_to_end_latency_ms"]["value"] == 500.0

    parsed = PerformanceEvidence.model_validate(payload)
    saved_files = list(tmp_path.glob("*.json"))
    assert len(saved_files) == 2  # the evidence record + the raw vllm output
    assert any(f.name == f"{parsed.benchmark_run_id}.json" for f in saved_files)


def test_bench_human_output_mentions_ttft_is_not_measured(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path))
    monkeypatch.setattr("app.cli.main.run_discovery", lambda: _fake_target())
    monkeypatch.setattr(
        "app.cli.main.run_vllm_bench_latency",
        lambda **kwargs: RawBenchmarkResult(raw_json={"avg_latency": 0.5}, gpu_samples=[]),
    )

    exit_code = main(["bench", "--model", "m"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "TTFT: not measured" in captured.out
    assert "End-to-end latency" in captured.out
    assert "Saved to" in captured.out


def test_runs_reports_empty_directory(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path / "empty"))
    exit_code = main(["runs"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "No benchmark runs found" in captured.out


def test_runs_lists_saved_runs(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path))
    monkeypatch.setattr("app.cli.main.run_discovery", lambda: _fake_target())
    monkeypatch.setattr(
        "app.cli.main.run_vllm_bench_latency",
        lambda **kwargs: RawBenchmarkResult(raw_json={"avg_latency": 0.5}, gpu_samples=[]),
    )
    main(["bench", "--model", "meta-llama/Llama-3.1-8B-Instruct"])
    capsys.readouterr()  # discard the bench command's own output

    exit_code = main(["runs"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "meta-llama/Llama-3.1-8B-Instruct" in captured.out
    assert "local-nvidia-test-host" in captured.out
    assert "500.0" in captured.out  # end-to-end latency in ms
