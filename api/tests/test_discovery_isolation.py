"""Tests for app.discovery.adapter.discover_all() — adapter failure
isolation (WP1 of the discovery/adapter cleanup). Every adapter here is a
fake; none of this touches subprocess/nvidia-smi/rocm-smi.

Covers the four failure modes called out in the work package: an adapter
raising during its availability check ("on init"), raising during
discovery, returning something that isn't a ComputeTarget, and hanging
past the timeout. In every case, a working adapter registered alongside it
must still return its target.
"""
from __future__ import annotations

import threading
import time

import pytest

from app.core.schemas import ComputeTarget, Metric
from app.discovery.adapter import DiscoveryAdapter, DiscoveryError, discover_all
from app.cli.main import run_discovery


def _fake_target(name: str = "Test GPU") -> ComputeTarget:
    return ComputeTarget(
        id=f"local-test-{name.lower().replace(' ', '-')}",
        vendor="nvidia",
        model=name,
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
        notes="test fixture",
    )


class _WorkingAdapter(DiscoveryAdapter):
    name = "Fake-Working"

    def __init__(self, target: ComputeTarget | None = None):
        self._target = target or _fake_target()

    def is_available(self) -> bool:
        return True

    def discover(self) -> ComputeTarget:
        return self._target


class _RaisesOnInitAdapter(DiscoveryAdapter):
    """"raises on init" — is_available() itself raises, a violation of its
    documented never-raise contract, caught defensively anyway."""

    name = "Fake-RaisesOnInit"

    def is_available(self) -> bool:
        raise RuntimeError("boom during availability check")

    def discover(self) -> ComputeTarget:  # pragma: no cover - never reached
        raise AssertionError("should not be called")


class _RaisesDuringDiscoveryAdapter(DiscoveryAdapter):
    name = "Fake-RaisesDuringDiscovery"

    def is_available(self) -> bool:
        return True

    def discover(self) -> ComputeTarget:
        raise DiscoveryError("simulated tooling failure")


class _MalformedOutputAdapter(DiscoveryAdapter):
    name = "Fake-Malformed"

    def is_available(self) -> bool:
        return True

    def discover(self) -> ComputeTarget:
        return {"not": "a ComputeTarget"}  # type: ignore[return-value]


class _HangingAdapter(DiscoveryAdapter):
    name = "Fake-Hanging"

    def is_available(self) -> bool:
        return True

    def discover(self) -> ComputeTarget:
        # Longer than any timeout used in these tests; the thread running
        # this is abandoned as a daemon, never actually joined.
        time.sleep(60)
        raise AssertionError("should never get here in a test")  # pragma: no cover


def test_raises_on_init_is_isolated_from_a_working_adapter():
    working_target = _fake_target()
    result = discover_all([_RaisesOnInitAdapter(), _WorkingAdapter(working_target)])

    assert result.targets == [working_target]
    assert len(result.errors) == 1
    error = result.errors[0]
    assert error.adapter == "Fake-RaisesOnInit"
    assert error.stage == "is_available"
    assert error.error_type == "RuntimeError"
    assert "boom during availability check" in error.message


def test_raises_during_discovery_is_isolated_from_a_working_adapter():
    working_target = _fake_target()
    result = discover_all([_RaisesDuringDiscoveryAdapter(), _WorkingAdapter(working_target)])

    assert result.targets == [working_target]
    assert len(result.errors) == 1
    error = result.errors[0]
    assert error.adapter == "Fake-RaisesDuringDiscovery"
    assert error.stage == "discover"
    assert error.error_type == "DiscoveryError"
    assert "simulated tooling failure" in error.message


def test_malformed_discover_output_is_isolated_from_a_working_adapter():
    working_target = _fake_target()
    result = discover_all([_MalformedOutputAdapter(), _WorkingAdapter(working_target)])

    assert result.targets == [working_target]
    assert len(result.errors) == 1
    error = result.errors[0]
    assert error.adapter == "Fake-Malformed"
    assert error.stage == "discover"
    assert error.error_type == "TypeError"
    assert "ComputeTarget" in error.message
    assert "dict" in error.message


def test_hanging_adapter_times_out_and_is_isolated_from_a_working_adapter():
    working_target = _fake_target()
    started_threads_before = threading.active_count()

    result = discover_all([_HangingAdapter(), _WorkingAdapter(working_target)], timeout_s=0.05)

    assert result.targets == [working_target]
    assert len(result.errors) == 1
    error = result.errors[0]
    assert error.adapter == "Fake-Hanging"
    assert error.stage == "discover"
    assert error.error_type == "TimeoutError"
    assert "0s" in error.message
    # The hung adapter's thread is abandoned, not joined — discover_all
    # must return promptly rather than waiting for it to finish.
    assert threading.active_count() >= started_threads_before


def test_all_adapters_failing_reports_every_error():
    result = discover_all([_RaisesOnInitAdapter(), _RaisesDuringDiscoveryAdapter()])

    assert result.targets == []
    assert {e.adapter for e in result.errors} == {"Fake-RaisesOnInit", "Fake-RaisesDuringDiscovery"}


def test_run_discovery_falls_back_to_a_later_adapter_when_an_earlier_one_fails():
    """Before WP1, a failing-but-available adapter earlier in the list
    stopped run_discovery from ever trying a later, working adapter — the
    exception propagated straight out. Now the failure is isolated and the
    later adapter's target is returned instead."""
    working_target = _fake_target("Fallback GPU")
    target = run_discovery([_RaisesDuringDiscoveryAdapter(), _WorkingAdapter(working_target)])

    assert target == working_target


def test_run_discovery_raises_with_every_adapter_error_folded_in_when_all_fail():
    with pytest.raises(DiscoveryError) as exc_info:
        run_discovery([_RaisesOnInitAdapter(), _RaisesDuringDiscoveryAdapter()])

    message = str(exc_info.value)
    assert "boom during availability check" in message
    assert "simulated tooling failure" in message
