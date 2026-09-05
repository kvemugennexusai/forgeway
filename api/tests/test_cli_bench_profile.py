"""CLI-level tests for `forgeway bench-profile` and `forgeway compare-runs`.
Everything below app.cli.main is mocked or real-but-isolated (discovery and
the benchmark runner are mocked; results are written to a tmp_path via the
FORGEWAY_BENCH_DIR override, never the real ~/.forgeway) — mirrors
test_cli_bench.py's conventions.
"""
from __future__ import annotations

import json

from app.benchmark.cross_vendor import (
    BenchmarkProfile,
    ComparabilityKey,
    CrossVendorEvidenceRecord,
    EnvironmentInfo,
)
from app.cli.main import ComputeTarget, main
from app.core.schemas import Metric
from app.core.schemas.v0_1 import PerformanceEvidence
from app.discovery.adapter import DiscoveryError

_PROFILE_YAML = """
profile_id: test-profile
profile_version: "0.1"
model: meta-llama/Llama-3.1-8B-Instruct
precision: bf16
input_tokens: 512
output_tokens: 128
concurrency: 1
batch_behavior: static single-request batches
warmup_runs: 1
measured_runs: 3
"""


def _fake_target(vendor: str = "nvidia") -> ComputeTarget:
    return ComputeTarget(
        id=f"local-{vendor}-test-host",
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
    )


def _profile() -> BenchmarkProfile:
    return BenchmarkProfile(
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


def _fake_record(vendor: str = "nvidia", run_id: str = "run-1", **evidence_overrides) -> CrossVendorEvidenceRecord:
    profile = _profile()
    target = _fake_target(vendor)
    evidence_kwargs = dict(
        compute_target_id=target.id,
        workload_id=profile.model,
        metrics={
            "end_to_end_latency_ms": Metric(value=500.0, confidence=95, provenance="MEASURED", source="test"),
            "output_token_throughput_tokens_per_s": Metric(
                value=256.0, confidence=95, provenance="MEASURED", source="test"
            ),
        },
        provenance="MEASURED",
        confidence=95.0,
        source="test",
        benchmark_run_id=run_id,
    )
    evidence_kwargs.update(evidence_overrides)
    return CrossVendorEvidenceRecord(
        run_id=run_id,
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
        target=target,
        environment=EnvironmentInfo(runtime_version="0.9.0", driver_version="550.90.07"),
        performance_evidence=PerformanceEvidence(**evidence_kwargs),
        comparability_key=ComparabilityKey.from_profile(profile),
        raw_command=["vllm", "bench", "latency"],
    )


class _FakeRunner:
    def __init__(self, record: CrossVendorEvidenceRecord):
        self._record = record

    def run(
        self,
        profile,
        target,
        *,
        run_id,
        workload_id=None,
        device_index=0,
        gpu_memory_utilization=None,
        timeout_s=None,
        enforce_eager=False,
    ):
        return self._record.model_copy(update={"run_id": run_id})


def test_bench_profile_reports_no_accelerator_cleanly(monkeypatch, tmp_path, capsys):
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(_PROFILE_YAML)

    def _raise():
        raise DiscoveryError("No supported accelerator was detected on this machine.")

    monkeypatch.setattr("app.cli.main.run_discovery", lambda: _raise())
    exit_code = main(["bench-profile", str(profile_path)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "No supported accelerator" in captured.err
    assert "Traceback" not in captured.err


def test_bench_profile_reports_bad_profile_cleanly(tmp_path, capsys):
    profile_path = tmp_path / "bad.yaml"
    profile_path.write_text("not: a: valid: profile\n")
    exit_code = main(["bench-profile", str(profile_path)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err


def test_bench_profile_happy_path_saves_evidence_and_record(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path))
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(_PROFILE_YAML)

    record = _fake_record(vendor="nvidia", run_id="bench-profile-abc123")
    monkeypatch.setattr("app.cli.main.run_discovery", lambda: _fake_target("nvidia"))
    monkeypatch.setattr("app.cli.main.runner_for_target", lambda target: _FakeRunner(record))

    output_path = tmp_path / "results" / "nvidia-run.json"
    exit_code = main(["bench-profile", str(profile_path), "--output", str(output_path)])

    assert exit_code == 0
    assert output_path.exists()
    saved = json.loads(output_path.read_text())
    assert saved["schema_version"] == "forgeway-cross-vendor/v0.1"
    assert saved["target"]["vendor"] == "nvidia"

    # The plain PerformanceEvidence also landed where `forgeway analyze`
    # looks for it (app.benchmark.store), same as `forgeway bench`.
    evidence_files = list(tmp_path.glob("bench-profile-abc123.json"))
    assert len(evidence_files) == 1

    captured = capsys.readouterr()
    assert "Forgeway cross-vendor benchmark" in captured.out
    assert "nvidia" in captured.out


def test_bench_profile_json_flag_emits_full_record(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path))
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(_PROFILE_YAML)

    record = _fake_record(vendor="amd", run_id="bench-profile-xyz")
    monkeypatch.setattr("app.cli.main.run_discovery", lambda: _fake_target("amd"))
    monkeypatch.setattr("app.cli.main.runner_for_target", lambda target: _FakeRunner(record))

    exit_code = main(["bench-profile", str(profile_path), "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["target"]["vendor"] == "amd"
    assert payload["performance_evidence"]["provenance"] == "MEASURED"


def test_compare_runs_reports_missing_file_cleanly(tmp_path, capsys):
    exit_code = main(["compare-runs", str(tmp_path / "a.json"), str(tmp_path / "b.json")])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "file not found" in captured.err
    assert "Traceback" not in captured.err


def test_compare_runs_directly_comparable(tmp_path, capsys):
    a = _fake_record(vendor="nvidia", run_id="nvidia-run")
    b = _fake_record(vendor="amd", run_id="amd-run")
    a_path = tmp_path / "nvidia-run.json"
    b_path = tmp_path / "amd-run.json"
    a_path.write_text(a.model_dump_json())
    b_path.write_text(b.model_dump_json())

    exit_code = main(["compare-runs", str(a_path), str(b_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "FORGEWAY CROSS-VENDOR EVIDENCE COMPARISON" in captured.out
    assert "DIRECTLY COMPARABLE" in captured.out
    assert "NVIDIA" in captured.out and "AMD" in captured.out
    assert "500.00 ms" in captured.out
    # No vendor "winner" declared anywhere in the output.
    assert "winner" not in captured.out.lower()
    assert "recommend" in captured.out.lower()  # only as "does not recommend a placement"


def test_compare_runs_not_comparable_shows_reasons(tmp_path, capsys):
    profile_a = _profile()
    profile_b = _profile().model_copy(update={"precision": "fp16"})
    a = _fake_record(vendor="nvidia", run_id="nvidia-run")
    b = _fake_record(vendor="amd", run_id="amd-run")
    b = b.model_copy(update={"comparability_key": ComparabilityKey.from_profile(profile_b)})
    a_path = tmp_path / "a.json"
    b_path = tmp_path / "b.json"
    a_path.write_text(a.model_dump_json())
    b_path.write_text(b.model_dump_json())

    exit_code = main(["compare-runs", str(a_path), str(b_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "NOT COMPARABLE" in captured.out
    assert "precision differs" in captured.out


def test_compare_runs_shows_cost_not_available_by_default(tmp_path, capsys):
    a = _fake_record(vendor="nvidia", run_id="nvidia-run")
    b = _fake_record(vendor="amd", run_id="amd-run")
    a_path = tmp_path / "a.json"
    b_path = tmp_path / "b.json"
    a_path.write_text(a.model_dump_json())
    b_path.write_text(b.model_dump_json())

    exit_code = main(["compare-runs", str(a_path), str(b_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Cost: not compared" in captured.out
