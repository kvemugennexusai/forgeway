"""Tests for app.benchmark.rocm_gpu_sampler — mocked subprocess.run, no
real rocm-smi or AMD GPU required. Mirrors test_benchmark_gpu_sampler.py's
structure for the NVIDIA sampler.
"""
from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

from app.benchmark.rocm_gpu_sampler import sample_gpu_once


def _run(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _card_json(**fields) -> str:
    return json.dumps({"card0": fields})


def test_sample_gpu_once_parses_power_and_memory():
    stdout = _card_json(**{
        "Average Graphics Package Power (W)": "250.5",
        "VRAM Total Used Memory (B)": str(20 * 1024**2),
    })
    with patch("app.benchmark.rocm_gpu_sampler.subprocess.run", return_value=_run(stdout=stdout)):
        sample = sample_gpu_once(device_index=0)

    assert sample is not None
    assert sample.power_draw_w == 250.5
    assert sample.memory_used_mb == 20.0


def test_sample_gpu_once_handles_different_key_casing():
    stdout = json.dumps({"card0": {
        "average graphics package power (w)": "100.0",
        "vram total used memory (b)": str(10 * 1024**2),
    }})
    with patch("app.benchmark.rocm_gpu_sampler.subprocess.run", return_value=_run(stdout=stdout)):
        sample = sample_gpu_once()

    assert sample is not None
    assert sample.power_draw_w == 100.0
    assert sample.memory_used_mb == 10.0


def test_sample_gpu_once_handles_missing_power_field():
    stdout = _card_json(**{"VRAM Total Used Memory (B)": str(5 * 1024**2)})
    with patch("app.benchmark.rocm_gpu_sampler.subprocess.run", return_value=_run(stdout=stdout)):
        sample = sample_gpu_once()

    assert sample is not None
    assert sample.power_draw_w is None  # not fabricated
    assert sample.memory_used_mb == 5.0


def test_sample_gpu_once_returns_none_when_binary_missing():
    with patch("app.benchmark.rocm_gpu_sampler.subprocess.run", side_effect=FileNotFoundError()):
        assert sample_gpu_once() is None


def test_sample_gpu_once_returns_none_on_timeout():
    with patch(
        "app.benchmark.rocm_gpu_sampler.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="rocm-smi", timeout=5.0),
    ):
        assert sample_gpu_once() is None


def test_sample_gpu_once_returns_none_on_nonzero_exit():
    with patch("app.benchmark.rocm_gpu_sampler.subprocess.run", return_value=_run(returncode=1)):
        assert sample_gpu_once() is None


def test_sample_gpu_once_returns_none_on_unparseable_json():
    with patch("app.benchmark.rocm_gpu_sampler.subprocess.run", return_value=_run(stdout="not json")):
        assert sample_gpu_once() is None


def test_sample_gpu_once_falls_back_to_first_card_when_index_key_absent():
    # e.g. rocm-smi's -d filter not narrowing the JSON the way expected —
    # should still find a card-shaped entry rather than returning None.
    stdout = json.dumps({"card3": {
        "Average Graphics Package Power (W)": "42.0",
        "VRAM Total Used Memory (B)": str(1024**2),
    }})
    with patch("app.benchmark.rocm_gpu_sampler.subprocess.run", return_value=_run(stdout=stdout)):
        sample = sample_gpu_once(device_index=0)

    assert sample is not None
    assert sample.power_draw_w == 42.0
    assert sample.memory_used_mb == 1.0
