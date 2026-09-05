"""Unit tests for app.discovery.nvidia.NvidiaDiscoveryAdapter.

Every test here mocks nvidia-smi's output (subprocess.run, or the two
thin wrappers around it) so none of this requires an actual NVIDIA GPU —
this suite runs the same on a CI runner or a laptop with no GPU at all.
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.discovery.adapter import DiscoveryError
from app.discovery.nvidia import (
    NvidiaDiscoveryAdapter,
    _architecture_for,
    _parse_gpu_rows,
    _run_query_gpu,
)

_SINGLE_GPU_CSV = "0, NVIDIA H100 80GB HBM3, 81559, 2048, 79511, 12, 8, 550.90.07, 9.0\n"

_TWO_GPU_SAME_MODEL_CSV = (
    "0, NVIDIA H100 80GB HBM3, 81559, 2048, 79511, 12, 8, 550.90.07, 9.0\n"
    "1, NVIDIA H100 80GB HBM3, 81559, 4096, 77463, 20, 10, 550.90.07, 9.0\n"
)

_TWO_GPU_DIFFERENT_MODEL_CSV = (
    "0, NVIDIA H100 80GB HBM3, 81559, 2048, 79511, 12, 8, 550.90.07, 9.0\n"
    "1, NVIDIA A100 80GB PCIe, 81920, 1024, 80896, 5, 3, 550.90.07, 8.0\n"
)

_VERSION_BANNER = """Thu Aug 20 12:00:00 2026
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 550.90.07              Driver Version: 550.90.07      CUDA Version: 12.4      |
|-----------------------------------------+----------------------+----------------------+
"""


def _run(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# --------------------------------------------------------------------------
# is_available()
# --------------------------------------------------------------------------


def test_is_available_true_when_nvidia_smi_on_path():
    with patch("app.discovery.nvidia.shutil.which", return_value="/usr/bin/nvidia-smi"):
        assert NvidiaDiscoveryAdapter().is_available() is True


def test_is_available_false_when_nvidia_smi_missing():
    with patch("app.discovery.nvidia.shutil.which", return_value=None):
        assert NvidiaDiscoveryAdapter().is_available() is False


# --------------------------------------------------------------------------
# _run_query_gpu() — the subprocess boundary itself
# --------------------------------------------------------------------------


def test_run_query_gpu_raises_discovery_error_when_binary_missing():
    with patch("app.discovery.nvidia.subprocess.run", side_effect=FileNotFoundError()):
        with pytest.raises(DiscoveryError, match="not installed"):
            _run_query_gpu()


def test_run_query_gpu_raises_discovery_error_on_timeout():
    with patch(
        "app.discovery.nvidia.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=5.0),
    ):
        with pytest.raises(DiscoveryError, match="did not respond"):
            _run_query_gpu()


def test_run_query_gpu_raises_discovery_error_on_nonzero_exit():
    with patch(
        "app.discovery.nvidia.subprocess.run",
        return_value=_run(returncode=1, stderr="Failed to initialize NVML"),
    ):
        with pytest.raises(DiscoveryError, match="Failed to initialize NVML"):
            _run_query_gpu()


# --------------------------------------------------------------------------
# _parse_gpu_rows()
# --------------------------------------------------------------------------


def test_parse_gpu_rows_raises_on_malformed_line():
    with pytest.raises(DiscoveryError, match="unexpected nvidia-smi output shape"):
        _parse_gpu_rows("0, NVIDIA H100 80GB HBM3, 81559\n")


# --------------------------------------------------------------------------
# _architecture_for() — best-effort compute-capability mapping
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "compute_cap,expected",
    [
        ("12.1", "blackwell"),  # live-verified 2026-09-04 against a real NVIDIA GB10 (DGX Spark)
        ("9.0", "hopper"),
        ("8.9", "ada-lovelace"),
        ("8.0", "ampere"),
        ("7.5", "turing"),
        ("7.0", "volta"),
    ],
)
def test_architecture_for_known_compute_capabilities(compute_cap, expected):
    assert _architecture_for(compute_cap) == expected


def test_architecture_for_unknown_compute_capability_is_labeled_not_guessed():
    result = _architecture_for("99.9")
    assert "unknown" in result
    assert "99.9" in result


# --------------------------------------------------------------------------
# discover() — full adapter behavior, mocked at the query-function level
# --------------------------------------------------------------------------


def test_discover_single_gpu_maps_every_field():
    with (
        patch("app.discovery.nvidia._run_query_gpu", return_value=_SINGLE_GPU_CSV),
        patch("app.discovery.nvidia._run_version_banner", return_value=_VERSION_BANNER),
    ):
        target = NvidiaDiscoveryAdapter().discover()

    assert target.schema_version == "forgeway/v0.1"
    assert target.vendor == "nvidia"
    assert target.model == "NVIDIA H100 80GB HBM3"
    assert target.architecture == "hopper"
    assert target.tier == "lab"
    assert target.capacity_units_total == 1
    assert target.capacity_units_allocated == 0
    assert target.accelerator_count == 1
    assert target.memory_gb_per_device == pytest.approx(81559 / 1024, abs=0.1)
    assert target.observed_gpu_utilization_pct == 12.0
    assert target.observed_memory_utilization_pct == 8.0
    assert target.status == "healthy"
    assert target.supported_precisions == []
    assert target.runtime_support is None

    assert target.price_per_hr_per_unit.value == 0.0
    assert target.price_per_hr_per_unit.confidence == 0
    assert target.price_per_hr_per_unit.provenance == "MODELED"

    assert "550.90.07" in target.notes  # driver version
    assert "12.4" in target.notes  # CUDA version
    assert "GPU 0: 77.6/79.6 GB free" in target.notes  # memory.free/memory.total

    assert target.discovered_at is not None
    assert target.discovered_at.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - target.discovered_at).total_seconds()) < 5


def test_discover_multiple_gpus_same_model_aggregates():
    with (
        patch("app.discovery.nvidia._run_query_gpu", return_value=_TWO_GPU_SAME_MODEL_CSV),
        patch("app.discovery.nvidia._run_version_banner", return_value=""),
    ):
        target = NvidiaDiscoveryAdapter().discover()

    assert target.capacity_units_total == 2
    assert target.observed_gpu_utilization_pct == pytest.approx((12 + 20) / 2)
    assert target.observed_memory_utilization_pct == pytest.approx((8 + 10) / 2)
    assert "not discoverable" in target.notes  # CUDA version, since the banner was empty
    # Per-device free memory for both GPUs, not just an average or the first device.
    assert "GPU 0: 77.6/79.6 GB free" in target.notes
    assert "GPU 1: 75.6/79.6 GB free" in target.notes


def test_discover_heterogeneous_gpus_notes_the_limitation():
    with (
        patch("app.discovery.nvidia._run_query_gpu", return_value=_TWO_GPU_DIFFERENT_MODEL_CSV),
        patch("app.discovery.nvidia._run_version_banner", return_value=""),
    ):
        target = NvidiaDiscoveryAdapter().discover()

    assert target.capacity_units_total == 2  # both devices still counted
    assert target.model == "NVIDIA H100 80GB HBM3"  # first device's spec used
    assert "different GPU models" in target.notes
    assert "H100" in target.notes and "A100" in target.notes


def test_discover_raises_when_zero_gpus_reported():
    with patch("app.discovery.nvidia._run_query_gpu", return_value=""):
        with pytest.raises(DiscoveryError, match="zero GPUs"):
            NvidiaDiscoveryAdapter().discover()


# --------------------------------------------------------------------------
# Real hardware regression — a real NVIDIA GB10 (DGX Spark) unified-memory
# system, live-verified 2026-09-04 (docs/discovery.md's future NVIDIA
# section, once written, should cross-reference this the same way ROCm's
# does). Captured verbatim via
# `nvidia-smi --query-gpu=... --format=csv,noheader,nounits`.
# --------------------------------------------------------------------------

_REAL_GB10_CSV = "0, NVIDIA GB10, [N/A], [N/A], [N/A], 0, 0, 580.173.02, 12.1\n"


def test_discover_matches_real_gb10_hardware_unified_memory_not_fabricated():
    with (
        patch("app.discovery.nvidia._run_query_gpu", return_value=_REAL_GB10_CSV),
        patch("app.discovery.nvidia._run_version_banner", return_value=""),
    ):
        target = NvidiaDiscoveryAdapter().discover()

    assert target.vendor == "nvidia"
    assert target.model == "NVIDIA GB10"
    assert target.architecture == "blackwell"  # resolved from real compute_cap "12.1"
    # The schema requires a float here — 0.0 is unavoidable — but it must
    # never be presented as a real reading: this is the regression guard
    # for that fabrication.
    assert target.memory_gb_per_device == 0.0
    assert "NOT a real measurement" in target.notes
    assert "unified-memory" in target.notes
    assert "not reported by nvidia-smi" in target.notes
    assert "GB 0: not reported" not in target.notes  # sanity: not a mangled/half-written sentence
