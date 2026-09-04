"""Unit tests for app.discovery.rocm.RocmDiscoveryAdapter.

Every test here mocks rocm-smi's output (subprocess.run, or the two thin
wrappers around it) so none of this requires an actual AMD GPU — this suite
runs the same on a CI runner or a laptop with no GPU at all. See
app/discovery/rocm.py's module docstring for why field lookups here are
case-insensitive: rocm-smi's JSON key casing has varied across ROCm releases
in the wild, unlike nvidia-smi's long-stable CSV schema.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.discovery.adapter import DiscoveryError
from app.discovery.rocm import (
    RocmDiscoveryAdapter,
    _architecture_for,
    _extract_driver_version,
    _lookup,
    _parse_show_output,
)

_SINGLE_CARD_JSON = json.dumps(
    {
        "card0": {
            "Card series": "Instinct MI300X",
            "Unique ID": "0x1234567890abcdef",
            "VRAM Total Memory (B)": "206158430208",  # 192 GiB
            "VRAM Total Used Memory (B)": "2147483648",  # 2 GiB
            "GPU use (%)": "15",
        }
    }
)

_TWO_CARD_SAME_MODEL_JSON = json.dumps(
    {
        "card0": {
            "Card series": "Instinct MI300X",
            "VRAM Total Memory (B)": "206158430208",
            "VRAM Total Used Memory (B)": "2147483648",
            "GPU use (%)": "10",
        },
        "card1": {
            "Card series": "Instinct MI300X",
            "VRAM Total Memory (B)": "206158430208",
            "VRAM Total Used Memory (B)": "4294967296",  # 4 GiB
            "GPU use (%)": "20",
        },
    }
)

_TWO_CARD_DIFFERENT_MODEL_JSON = json.dumps(
    {
        "card0": {
            "Card series": "Instinct MI300X",
            "VRAM Total Memory (B)": "206158430208",
            "VRAM Total Used Memory (B)": "2147483648",
            "GPU use (%)": "10",
        },
        "card1": {
            "Card series": "Radeon RX 7900 XT",
            "VRAM Total Memory (B)": "21458059264",
            "VRAM Total Used Memory (B)": "1073741824",
            "GPU use (%)": "5",
        },
    }
)

# Real-world casing has varied ("Card Series" with a capital S has also been
# observed) — this proves the adapter isn't brittle to that.
_DIFFERENT_CASING_JSON = json.dumps(
    {
        "card0": {
            "Card Series": "Instinct MI300X",
            "VRAM Total Memory (B)": "206158430208",
            "VRAM Total Used Memory (B)": "0",
            "GPU use (%)": "0",
        }
    }
)

_DRIVER_VERSION_JSON = json.dumps({"system": {"Driver version": "6.7.0"}})


def _run(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# --------------------------------------------------------------------------
# is_available()
# --------------------------------------------------------------------------


def test_is_available_true_when_rocm_smi_on_path():
    with patch("app.discovery.rocm.shutil.which", return_value="/usr/bin/rocm-smi"):
        assert RocmDiscoveryAdapter().is_available() is True


def test_is_available_false_when_rocm_smi_missing():
    with patch("app.discovery.rocm.shutil.which", return_value=None):
        assert RocmDiscoveryAdapter().is_available() is False


# --------------------------------------------------------------------------
# _run_show_query() — the subprocess boundary itself
# --------------------------------------------------------------------------


def test_run_show_query_raises_discovery_error_when_binary_missing():
    from app.discovery.rocm import _run_show_query

    with patch("app.discovery.rocm.subprocess.run", side_effect=FileNotFoundError()):
        with pytest.raises(DiscoveryError, match="not installed"):
            _run_show_query()


def test_run_show_query_raises_discovery_error_on_timeout():
    from app.discovery.rocm import _run_show_query

    with patch(
        "app.discovery.rocm.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="rocm-smi", timeout=5.0),
    ):
        with pytest.raises(DiscoveryError, match="did not respond"):
            _run_show_query()


def test_run_show_query_raises_discovery_error_on_nonzero_exit():
    from app.discovery.rocm import _run_show_query

    with patch(
        "app.discovery.rocm.subprocess.run",
        return_value=_run(returncode=1, stderr="Unable to open kfd device"),
    ):
        with pytest.raises(DiscoveryError, match="Unable to open kfd device"):
            _run_show_query()


# --------------------------------------------------------------------------
# _parse_show_output()
# --------------------------------------------------------------------------


def test_parse_show_output_raises_on_unparseable_json():
    with pytest.raises(DiscoveryError, match="unparseable JSON"):
        _parse_show_output("not json")


def test_parse_show_output_raises_on_non_object_json():
    with pytest.raises(DiscoveryError, match="expected a JSON object"):
        _parse_show_output("[1, 2, 3]")


def test_parse_show_output_raises_when_no_card_keys():
    with pytest.raises(DiscoveryError, match="zero GPUs"):
        _parse_show_output(json.dumps({"system": {"Driver version": "6.7.0"}}))


# --------------------------------------------------------------------------
# _lookup() — case-insensitive field access
# --------------------------------------------------------------------------


def test_lookup_is_case_insensitive():
    assert _lookup({"Card Series": "MI300X"}, "card series") == "MI300X"
    assert _lookup({"card series": "MI300X"}, "Card Series") == "MI300X"
    assert _lookup({}, "Card series") is None


# --------------------------------------------------------------------------
# _architecture_for() — best-effort product-name mapping
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model,expected",
    [
        ("Instinct MI300X", "cdna3"),
        ("Instinct MI250X", "cdna2"),
        ("Instinct MI100", "cdna"),
        ("Radeon RX 7900 XT", "rdna3"),
        ("Radeon RX 6800", "rdna2"),
    ],
)
def test_architecture_for_known_models(model, expected):
    assert _architecture_for(model) == expected


def test_architecture_for_unknown_model_is_labeled_not_guessed():
    result = _architecture_for("Some Future GPU 9000")
    assert "unknown" in result
    assert "Some Future GPU 9000" in result


# --------------------------------------------------------------------------
# _extract_driver_version() — best-effort, never raises
# --------------------------------------------------------------------------


def test_extract_driver_version_finds_versioned_field():
    assert _extract_driver_version(_DRIVER_VERSION_JSON) == "6.7.0"


def test_extract_driver_version_returns_empty_on_unparseable_input():
    assert _extract_driver_version("not json") == ""
    assert _extract_driver_version("") == ""


def test_extract_driver_version_returns_empty_when_no_driver_field():
    assert _extract_driver_version(json.dumps({"card0": {"GPU use (%)": "0"}})) == ""


# --------------------------------------------------------------------------
# discover() — full adapter behavior, mocked at the query-function level
# --------------------------------------------------------------------------


def test_discover_single_card_maps_every_field():
    with (
        patch("app.discovery.rocm._run_show_query", return_value=_SINGLE_CARD_JSON),
        patch("app.discovery.rocm._run_driver_version_query", return_value=_DRIVER_VERSION_JSON),
    ):
        target = RocmDiscoveryAdapter().discover()

    assert target.schema_version == "forgeway/v0.1"
    assert target.vendor == "amd"
    assert target.model == "Instinct MI300X"
    assert target.architecture == "cdna3"
    assert target.tier == "lab"
    assert target.capacity_units_total == 1
    assert target.capacity_units_allocated == 0
    assert target.accelerator_count == 1
    assert target.memory_gb_per_device == pytest.approx(206158430208 / 1024**3, abs=0.1)
    assert target.observed_gpu_utilization_pct == 15.0
    assert target.observed_memory_utilization_pct == pytest.approx(
        2147483648 / 206158430208 * 100, abs=0.1
    )
    assert target.status == "healthy"
    assert target.supported_precisions == []
    assert target.runtime_support is None

    assert target.price_per_hr_per_unit.value == 0.0
    assert target.price_per_hr_per_unit.confidence == 0
    assert target.price_per_hr_per_unit.provenance == "MODELED"

    assert "6.7.0" in target.notes  # driver version
    assert "0x1234567890abcdef" in target.notes  # unique id
    assert "GPU 0:" in target.notes and "GB free" in target.notes

    assert target.discovered_at is not None
    assert target.discovered_at.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - target.discovered_at).total_seconds()) < 5


def test_discover_handles_different_key_casing():
    with (
        patch("app.discovery.rocm._run_show_query", return_value=_DIFFERENT_CASING_JSON),
        patch("app.discovery.rocm._run_driver_version_query", return_value=""),
    ):
        target = RocmDiscoveryAdapter().discover()

    assert target.model == "Instinct MI300X"
    assert "not discoverable" in target.notes  # driver version, since the query returned nothing


def test_discover_multiple_cards_same_model_aggregates():
    with (
        patch("app.discovery.rocm._run_show_query", return_value=_TWO_CARD_SAME_MODEL_JSON),
        patch("app.discovery.rocm._run_driver_version_query", return_value=""),
    ):
        target = RocmDiscoveryAdapter().discover()

    assert target.capacity_units_total == 2
    assert target.observed_gpu_utilization_pct == pytest.approx((10 + 20) / 2)
    assert "GPU 0:" in target.notes and "GPU 1:" in target.notes


def test_discover_heterogeneous_cards_notes_the_limitation():
    with (
        patch("app.discovery.rocm._run_show_query", return_value=_TWO_CARD_DIFFERENT_MODEL_JSON),
        patch("app.discovery.rocm._run_driver_version_query", return_value=""),
    ):
        target = RocmDiscoveryAdapter().discover()

    assert target.capacity_units_total == 2  # both devices still counted
    assert target.model == "Instinct MI300X"  # first device's spec used
    assert "different GPU models" in target.notes
    assert "MI300X" in target.notes and "RX 7900 XT" in target.notes


def test_discover_raises_when_zero_cards_reported():
    with patch("app.discovery.rocm._run_show_query", return_value=json.dumps({})):
        with pytest.raises(DiscoveryError, match="zero GPUs"):
            RocmDiscoveryAdapter().discover()


def test_discover_raises_on_malformed_card_entry():
    malformed = json.dumps({"card0": {"GPU use (%)": "0"}})  # missing Card series / VRAM fields
    with patch("app.discovery.rocm._run_show_query", return_value=malformed):
        with pytest.raises(DiscoveryError, match="unexpected rocm-smi JSON shape"):
            RocmDiscoveryAdapter().discover()
