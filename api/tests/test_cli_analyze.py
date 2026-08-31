"""CLI-level tests for `forgeway analyze` — using the real
examples/workload.yaml and examples/policy.yaml (the same files
README.md's end-to-end CLI flow walks through), not synthetic stand-ins,
so these tests double as regression coverage for the example files
themselves.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.cli.main import ComputeTarget, main
from app.core.schemas.v0_1 import PlacementDecision
from app.discovery.adapter import DiscoveryError

_EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"
_WORKLOAD_PATH = str(_EXAMPLES_DIR / "workload.yaml")
_POLICY_PATH = str(_EXAMPLES_DIR / "policy.yaml")


def _fake_discovered_target(target_id: str = "local-nvidia-test-host") -> ComputeTarget:
    from app.core.schemas import Metric

    return ComputeTarget(
        id=target_id,
        vendor="nvidia",
        model="Test Discovered GPU",
        tier="lab",
        location=f"local ({target_id})",
        architecture="hopper",
        memory_gb_per_device=80.0,
        interconnect="not probed",
        supported_precisions=[],
        capacity_units_total=1,
        capacity_units_allocated=0,
        price_per_hr_per_unit=Metric(value=0.0, confidence=0, provenance="MODELED", source="test"),
        status="healthy",
    )


def test_analyze_matches_the_known_baseline_with_skip_discovery(capsys):
    exit_code = main(["analyze", _WORKLOAD_PATH, "--skip-discovery"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "FORGEWAY PLACEMENT DECISION" in captured.out
    assert "MI300X 192GB" in captured.out  # the known baseline recommendation
    assert "Confidence:\n  MEDIUM" in captured.out
    assert "SLO status:\n  MET" in captured.out
    assert "REJECTED" in captured.out
    assert "FEASIBLE" in captured.out
    assert "discovered" not in captured.out.lower()  # --skip-discovery: no discovery note at all


def test_analyze_json_emits_a_valid_placement_decision(capsys):
    exit_code = main(["analyze", _WORKLOAD_PATH, "--skip-discovery", "--json"])

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "forgeway/v0.1"
    assert payload["recommended_target_id"] == "amd-mi300x"
    parsed = PlacementDecision.model_validate(payload)
    assert parsed.workload_id == "wl-llama70b-rt"
    # JSON mode must be exactly the JSON — no human-readable text mixed in.
    assert "FORGEWAY PLACEMENT DECISION" not in captured.out


def test_analyze_policy_override_changes_the_recommendation(capsys):
    exit_code = main(["analyze", _WORKLOAD_PATH, "--skip-discovery", "--policy", _POLICY_PATH])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "H100 80GB SXM5" in captured.out
    assert captured.out.count("RECOMMENDED") == 1
    recommended_line = next(line for line in captured.out.splitlines() if "RECOMMENDED" in line)
    assert "H100" in recommended_line


def test_analyze_reports_missing_workload_file_cleanly(capsys):
    exit_code = main(["analyze", "does-not-exist.yaml", "--skip-discovery"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "file not found" in captured.err
    assert "Traceback" not in captured.err


def test_analyze_reports_invalid_workload_cleanly(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("id: incomplete\n")

    exit_code = main(["analyze", str(bad), "--skip-discovery"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "not a valid AIWorkload" in captured.err
    assert "Traceback" not in captured.err


def test_analyze_includes_a_newly_discovered_target(monkeypatch, capsys):
    discovered = _fake_discovered_target()
    monkeypatch.setattr("app.cli.main.run_discovery", lambda: discovered)

    exit_code = main(["analyze", _WORKLOAD_PATH, "--json"])

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert discovered.id in payload["evaluated_targets"]


def test_analyze_skip_discovery_never_calls_discovery(monkeypatch, capsys):
    def _must_not_be_called():
        raise AssertionError("run_discovery should not be called when --skip-discovery is passed")

    monkeypatch.setattr("app.cli.main.run_discovery", _must_not_be_called)

    exit_code = main(["analyze", _WORKLOAD_PATH, "--skip-discovery", "--json"])

    assert exit_code == 0  # would have raised AssertionError above if discovery had been attempted


def test_analyze_handles_discovery_failure_gracefully(monkeypatch, capsys):
    def _raise():
        raise DiscoveryError("No supported accelerator was detected on this machine.")

    monkeypatch.setattr("app.cli.main.run_discovery", _raise)

    exit_code = main(["analyze", _WORKLOAD_PATH])

    assert exit_code == 0  # discovery failing is not fatal to analyze
    captured = capsys.readouterr()
    assert "No local hardware discovered" in captured.out
