"""CLI-level tests for `forgeway qualify`, `forgeway qualify-import`, and
`forgeway qualifications`. Discovery and the staged checker are mocked;
the databank is real filesystem I/O against a tmp_path via
FORGEWAY_QUALIFICATION_DIR — mirrors test_cli_bench_profile.py's
conventions.
"""
from __future__ import annotations

import json

from app.cli.main import ComputeTarget, main
from app.core.schemas import Metric
from app.core.schemas.v0_1.qualification import QualificationRecord, QualificationSubject
from app.discovery.adapter import DiscoveryError
from app.qualification import store

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


def _target(**overrides) -> ComputeTarget:
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


def _expected_subject(**overrides) -> QualificationSubject:
    base = dict(
        vendor="nvidia",
        hardware_model="Test GPU",
        architecture="hopper",
        runtime="vllm",
        runtime_version="0.9.0",
        backend="cuda",
        model="meta-llama/Llama-3.1-8B-Instruct",
        precision="bf16",
        deployment_config={"tensor_parallel_degree": 1},
        workload_class="realtime-inference",
    )
    base.update(overrides)
    return QualificationSubject(**base)


def _record(subject: QualificationSubject, **overrides) -> QualificationRecord:
    base = dict(state="smoke_tested", source="test", environment="test")
    base.update(overrides)
    return QualificationRecord.for_subject(subject, **base)


def _patch_common(monkeypatch, tmp_path, target=None):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path))
    monkeypatch.setattr("app.cli.main.resolve_bench_target", lambda target_id: target or _target())
    monkeypatch.setattr("app.cli.main._best_effort_vllm_version", lambda: "0.9.0")


# --------------------------------------------------------------------------
# forgeway qualify
# --------------------------------------------------------------------------


def test_qualify_reports_no_accelerator_cleanly(monkeypatch, tmp_path, capsys):
    _patch_common(monkeypatch, tmp_path)
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(_PROFILE_YAML)

    def _raise(target_id):
        raise DiscoveryError("No supported accelerator was detected on this machine.")

    monkeypatch.setattr("app.cli.main.resolve_bench_target", _raise)
    exit_code = main(["qualify", str(profile_path), "--workload-class", "realtime-inference"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "No supported accelerator" in captured.err
    assert "Traceback" not in captured.err


def test_qualify_reports_bad_profile_cleanly(monkeypatch, tmp_path, capsys):
    _patch_common(monkeypatch, tmp_path)
    profile_path = tmp_path / "bad.yaml"
    profile_path.write_text("not: a: valid: profile\n")

    exit_code = main(["qualify", str(profile_path), "--workload-class", "realtime-inference"])

    assert exit_code == 1
    assert "Traceback" not in capsys.readouterr().err


def test_qualify_reports_existing_databank_record_without_rerunning(monkeypatch, tmp_path, capsys):
    _patch_common(monkeypatch, tmp_path)
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(_PROFILE_YAML)

    existing = _record(_expected_subject(), state="unknown", source="pre-seeded")
    store.save_qualification(existing)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("run_qualification_pipeline should not be called when already in databank")

    monkeypatch.setattr("app.cli.main.run_qualification_pipeline", _fail_if_called)

    exit_code = main(["qualify", str(profile_path), "--workload-class", "realtime-inference"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "already in databank" in captured.out
    assert "pre-seeded" in captured.out


def test_qualify_runs_pipeline_and_saves_when_nothing_in_databank(monkeypatch, tmp_path, capsys):
    _patch_common(monkeypatch, tmp_path)
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(_PROFILE_YAML)

    new_record = _record(_expected_subject(), state="smoke_tested", source="fresh check")
    monkeypatch.setattr("app.cli.main.run_qualification_pipeline", lambda *a, **k: new_record)

    exit_code = main(["qualify", str(profile_path), "--workload-class", "realtime-inference"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "already in databank" not in captured.out
    assert "smoke_tested" in captured.out
    assert store.get_qualification(_expected_subject()) == new_record


def test_qualify_force_reruns_even_when_already_in_databank(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path)
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(_PROFILE_YAML)

    store.save_qualification(_record(_expected_subject(), state="unknown", source="stale check"))
    fresh_record = _record(_expected_subject(), state="smoke_tested", source="forced re-check")
    monkeypatch.setattr("app.cli.main.run_qualification_pipeline", lambda *a, **k: fresh_record)

    exit_code = main(["qualify", str(profile_path), "--workload-class", "realtime-inference", "--force"])

    assert exit_code == 0
    assert store.get_qualification(_expected_subject()).source == "forced re-check"


def test_qualify_json_flag_emits_full_record(monkeypatch, tmp_path, capsys):
    _patch_common(monkeypatch, tmp_path)
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(_PROFILE_YAML)

    new_record = _record(_expected_subject())
    monkeypatch.setattr("app.cli.main.run_qualification_pipeline", lambda *a, **k: new_record)

    exit_code = main(["qualify", str(profile_path), "--workload-class", "realtime-inference", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == new_record.id
    parsed = QualificationRecord.model_validate(payload)
    assert parsed == new_record


def test_qualify_slo_from_pins_the_subjects_slo(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path)
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(_PROFILE_YAML)
    workload_path = tmp_path / "workload.yaml"
    workload_path.write_text(
        """
id: wl-test
name: test workload
model_family: Test-7B
model_params_billion: 7
workload_class: realtime-inference
precision: fp16
weights_footprint_gb: 10
kv_cache_overhead_gb: 2
baseline_concurrency: 4
slo:
  p99_latency_ms: 450
  min_throughput_tokens_per_s: 1800
  availability_pct: 99.9
policy:
  allowed_vendors: [nvidia]
  denied_vendors: []
  allowed_regions: [us-east-1]
  budget_ceiling_per_hr: 25.0
current_placement:
  target_id: t-a
  replica_count: 1
  measured_p99_latency_ms: 400
  measured_throughput_tokens_per_s_per_replica: 150
  cost_per_hr: 2.0
  provenance: MEASURED
  source: test
"""
    )

    seen_subjects = []

    def _capture(checker, subject, target, **kwargs):
        seen_subjects.append(subject)
        return _record(subject, state="measured_pass", source="s", evidence_reference="qual-smoke-1")

    monkeypatch.setattr("app.cli.main.run_qualification_pipeline", _capture)

    exit_code = main(
        [
            "qualify",
            str(profile_path),
            "--workload-class",
            "realtime-inference",
            "--slo-from",
            str(workload_path),
        ]
    )

    assert exit_code == 0
    assert seen_subjects[0].slo is not None
    assert seen_subjects[0].slo.p99_latency_ms == 450


# --------------------------------------------------------------------------
# forgeway qualify-import
# --------------------------------------------------------------------------


def test_qualify_import_saves_a_hand_authored_record(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path))
    record = _record(_expected_subject(), state="unknown", source="no verifiable source found")
    record_path = tmp_path / "record.json"
    record_path.write_text(record.model_dump_json())

    exit_code = main(["qualify-import", str(record_path)])

    assert exit_code == 0
    assert "Saved to the local qualification databank" in capsys.readouterr().out
    assert store.get_qualification(_expected_subject()) == record


def test_qualify_import_reports_invalid_json_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path))
    record_path = tmp_path / "bad.json"
    record_path.write_text("{not valid json")

    exit_code = main(["qualify-import", str(record_path)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "not a valid QualificationRecord" in captured.err
    assert "Traceback" not in captured.err


def test_qualify_import_reports_missing_file_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path))
    exit_code = main(["qualify-import", str(tmp_path / "does-not-exist.json")])

    assert exit_code == 1
    assert "file not found" in capsys.readouterr().err


# --------------------------------------------------------------------------
# forgeway qualifications
# --------------------------------------------------------------------------


def test_qualifications_reports_empty_databank(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path / "empty"))
    exit_code = main(["qualifications"])
    assert exit_code == 0
    assert "No qualification records found" in capsys.readouterr().out


def test_qualifications_lists_saved_records(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FORGEWAY_QUALIFICATION_DIR", str(tmp_path))
    store.save_qualification(_record(_expected_subject()))

    exit_code = main(["qualifications"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Test GPU" in captured.out
    assert "realtime-inference" in captured.out
    assert "smoke_tested" in captured.out
