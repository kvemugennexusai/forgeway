"""Tests for the `forgeway` CLI (app.cli.main), independent of any real
adapter — a fake DiscoveryAdapter stands in for NVIDIA discovery so these
never touch subprocess or nvidia-smi at all.
"""
from __future__ import annotations

import json

import pytest

from app.cli.main import ComputeTarget, main
from app.core.schemas import Metric
from app.discovery.adapter import DiscoveryAdapter, DiscoveryError


def _fake_target(**overrides) -> ComputeTarget:
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
        notes="Discovered via nvidia-smi on test-host.",
        observed_gpu_utilization_pct=10.0,
        observed_memory_utilization_pct=5.0,
    )
    base.update(overrides)
    return ComputeTarget(**base)


class _UnavailableAdapter(DiscoveryAdapter):
    name = "Fake-Unavailable"

    def is_available(self) -> bool:
        return False

    def discover(self) -> ComputeTarget:  # pragma: no cover - never reached
        raise AssertionError("should not be called when unavailable")


class _WorkingAdapter(DiscoveryAdapter):
    name = "Fake-Working"

    def __init__(self, target: ComputeTarget):
        self._target = target

    def is_available(self) -> bool:
        return True

    def discover(self) -> ComputeTarget:
        return self._target


class _BrokenAdapter(DiscoveryAdapter):
    name = "Fake-Broken"

    def is_available(self) -> bool:
        return True

    def discover(self) -> ComputeTarget:
        raise RuntimeError("unexpected bug, not a DiscoveryError")


def test_discover_reports_no_accelerator_cleanly_when_none_available(monkeypatch, capsys):
    monkeypatch.setattr("app.cli.main.ADAPTERS", [_UnavailableAdapter()])

    exit_code = main(["discover"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "No supported accelerator was detected" in captured.err
    assert "Traceback" not in captured.err


def test_discover_json_emits_a_valid_compute_target(monkeypatch, capsys):
    target = _fake_target()
    monkeypatch.setattr("app.cli.main.ADAPTERS", [_WorkingAdapter(target)])

    exit_code = main(["discover", "--json"])

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "forgeway/v0.1"
    assert payload["vendor"] == "nvidia"
    parsed = ComputeTarget.model_validate(payload)
    assert parsed == target


def test_discover_human_output_contains_key_fields(monkeypatch, capsys):
    target = _fake_target()
    monkeypatch.setattr("app.cli.main.ADAPTERS", [_WorkingAdapter(target)])

    exit_code = main(["discover"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "nvidia" in captured.out
    assert "Test GPU" in captured.out
    assert "80.0 GB" in captured.out
    assert "hopper" in captured.out
    assert "10% GPU" in captured.out
    assert "--json" in captured.out  # the hint to run with --json


def test_unexpected_adapter_exception_never_surfaces_as_a_raw_traceback(monkeypatch, capsys):
    monkeypatch.setattr("app.cli.main.ADAPTERS", [_BrokenAdapter()])

    exit_code = main(["discover"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "unexpected error" in captured.err
    assert "Traceback" not in captured.err


def test_run_discovery_raises_discovery_error_directly_when_nothing_available():
    from app.cli.main import run_discovery

    with pytest.raises(DiscoveryError):
        run_discovery([_UnavailableAdapter()])
