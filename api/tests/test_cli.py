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


#: The exact top-level key set `forgeway discover --json` has always
#: emitted (one ComputeTarget's own fields, schema + computed). Pinned here
#: as its own regression test (WP2) so a future change to this shape — e.g.
#: accidentally returning a list, or adding a field meant for the new
#: `--all` mode — fails loudly instead of silently breaking the web app's
#: /import flow (web/components/import/import-panel.tsx), which parses
#: this as one object pasted in by hand.
_DISCOVER_JSON_SHAPE_KEYS = {
    "schema_version",
    "id",
    "vendor",
    "model",
    "tier",
    "location",
    "architecture",
    "memory_gb_per_device",
    "interconnect",
    "supported_precisions",
    "capacity_units_total",
    "capacity_units_allocated",
    "runtime_support",
    "price_per_hr_per_unit",
    "status",
    "unsupported_workload_classes",
    "notes",
    "observed_gpu_utilization_pct",
    "observed_memory_utilization_pct",
    "discovered_at",
    "free_capacity_units",
    "utilization_pct",
    "accelerator_count",
}


def test_discover_json_output_shape_is_pinned(monkeypatch, capsys):
    target = _fake_target()
    monkeypatch.setattr("app.cli.main.ADAPTERS", [_WorkingAdapter(target)])

    exit_code = main(["discover", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, dict)
    assert set(payload.keys()) == _DISCOVER_JSON_SHAPE_KEYS
    assert payload["schema_version"] == "forgeway/v0.1"


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
    """Before WP1 (adapter failure isolation), an adapter's discover()
    raising anything other than DiscoveryError propagated all the way to
    main()'s last-resort catch-all, printing "unexpected error". Now
    run_discovery() catches it as an AdapterError via discover_all() and
    reports a clean "no accelerator detected" message with the underlying
    failure folded in — still never a raw traceback, but no longer
    routed through the last-resort handler for a failure mode discovery
    itself is now expected to handle."""
    monkeypatch.setattr("app.cli.main.ADAPTERS", [_BrokenAdapter()])

    exit_code = main(["discover"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "No supported accelerator was detected" in captured.err
    assert "unexpected bug, not a DiscoveryError" in captured.err
    assert "Traceback" not in captured.err


# --------------------------------------------------------------------------
# `forgeway discover --all` (WP2) — additive, does not touch plain
# `forgeway discover`'s output shape (see the pinning test above).
# --------------------------------------------------------------------------


def test_discover_all_json_reports_every_target_and_every_error(monkeypatch, capsys):
    target_a = _fake_target(id="local-nvidia-a", model="GPU A")
    target_b = _fake_target(id="local-nvidia-b", model="GPU B")
    monkeypatch.setattr(
        "app.cli.main.ADAPTERS",
        [_WorkingAdapter(target_a), _BrokenAdapter(), _WorkingAdapter(target_b)],
    )

    exit_code = main(["discover", "--all", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "forgeway-discover-all/v0.1"
    assert [t["id"] for t in payload["targets"]] == ["local-nvidia-a", "local-nvidia-b"]
    assert len(payload["errors"]) == 1
    assert payload["errors"][0]["adapter"] == "Fake-Broken"
    assert payload["errors"][0]["stage"] == "discover"


def test_discover_all_human_output_lists_targets_and_errors(monkeypatch, capsys):
    target = _fake_target()
    monkeypatch.setattr("app.cli.main.ADAPTERS", [_WorkingAdapter(target), _BrokenAdapter()])

    exit_code = main(["discover", "--all"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Test GPU" in captured.out
    assert "Fake-Broken" in captured.out
    assert "--target-id" in captured.out


def test_discover_all_reports_failure_when_nothing_found(monkeypatch, capsys):
    monkeypatch.setattr("app.cli.main.ADAPTERS", [_UnavailableAdapter()])

    exit_code = main(["discover", "--all"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "No accelerators discovered" in captured.out


def test_discover_all_does_not_change_plain_discover_output(monkeypatch, capsys):
    """Same adapter list, both commands — confirms --all is a genuinely
    separate mode rather than a variant that leaks into plain discover."""
    target = _fake_target()
    monkeypatch.setattr("app.cli.main.ADAPTERS", [_WorkingAdapter(target)])

    main(["discover", "--json"])
    plain_payload = json.loads(capsys.readouterr().out)

    main(["discover", "--all", "--json"])
    all_payload = json.loads(capsys.readouterr().out)

    assert plain_payload == json.loads(target.model_dump_json())
    assert all_payload["schema_version"] == "forgeway-discover-all/v0.1"
    assert "targets" in all_payload and "schema_version" in plain_payload
    assert set(plain_payload.keys()) == _DISCOVER_JSON_SHAPE_KEYS  # unchanged single-object shape


def test_run_discovery_raises_discovery_error_directly_when_nothing_available():
    from app.cli.main import run_discovery

    with pytest.raises(DiscoveryError):
        run_discovery([_UnavailableAdapter()])
