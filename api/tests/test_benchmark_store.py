"""Tests for app.benchmark.store — real filesystem I/O against a tmp_path,
isolated via the FORGEWAY_BENCH_DIR environment variable override."""
from __future__ import annotations

import json

from app.benchmark.store import list_runs, results_dir, save_run
from app.core.schemas import ComputeTarget, Metric
from app.core.schemas.v0_1 import PerformanceEvidence


def _evidence(run_id: str, **overrides) -> PerformanceEvidence:
    base = dict(
        compute_target_id="local-nvidia-test-host",
        workload_id="meta-llama/Llama-3.1-8B-Instruct",
        metrics={"end_to_end_latency_ms": Metric(value=100.0, confidence=95, provenance="MEASURED", source="test")},
        provenance="MEASURED",
        confidence=95.0,
        source="test",
        benchmark_run_id=run_id,
    )
    base.update(overrides)
    return PerformanceEvidence(**base)


def test_results_dir_respects_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path / "custom"))
    assert results_dir() == tmp_path / "custom"


def test_results_dir_defaults_to_home_dot_forgeway(monkeypatch):
    monkeypatch.delenv("FORGEWAY_BENCH_DIR", raising=False)
    assert str(results_dir()).endswith(".forgeway/benchmarks")


def test_save_run_writes_evidence_json(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path))
    evidence = _evidence("bench-abc123")

    path = save_run(evidence)

    assert path == tmp_path / "bench-abc123.json"
    assert path.exists()
    assert PerformanceEvidence.model_validate_json(path.read_text()) == evidence


def test_save_run_also_writes_raw_output_when_given(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path))
    evidence = _evidence("bench-abc123")

    save_run(evidence, raw_output={"avg_latency": 0.1})

    raw_path = tmp_path / "bench-abc123.raw_vllm_output.json"
    assert raw_path.exists()
    assert json.loads(raw_path.read_text()) == {"avg_latency": 0.1}


def test_list_runs_returns_empty_list_when_directory_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path / "does-not-exist"))
    assert list_runs() == []


def test_list_runs_finds_saved_runs_and_skips_raw_output_files(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path))
    e1 = _evidence("bench-001")
    e2 = _evidence("bench-002")
    save_run(e1, raw_output={"avg_latency": 0.1})
    save_run(e2)

    runs = list_runs()

    assert len(runs) == 2
    assert {r.benchmark_run_id for r in runs} == {"bench-001", "bench-002"}


def test_list_runs_skips_unparseable_files_instead_of_crashing(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path))
    save_run(_evidence("bench-good"))
    (tmp_path / "not-evidence.json").write_text("{not valid json")

    runs = list_runs()

    assert len(runs) == 1
    assert runs[0].benchmark_run_id == "bench-good"
