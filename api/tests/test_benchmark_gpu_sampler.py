"""Tests for app.benchmark.gpu_sampler — mocked subprocess.run, no real
nvidia-smi or GPU required.
"""
from __future__ import annotations

import subprocess
from unittest.mock import patch

from app.benchmark.gpu_sampler import sample_gpu_once


def _run(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_sample_gpu_once_parses_power_and_memory():
    with patch(
        "app.benchmark.gpu_sampler.subprocess.run",
        return_value=_run(stdout="123.45, 20480\n"),
    ):
        sample = sample_gpu_once(device_index=0)

    assert sample is not None
    assert sample.power_draw_w == 123.45
    assert sample.memory_used_mb == 20480.0


def test_sample_gpu_once_handles_not_available_power_draw():
    with patch(
        "app.benchmark.gpu_sampler.subprocess.run",
        return_value=_run(stdout="[N/A], 20480\n"),
    ):
        sample = sample_gpu_once()

    assert sample is not None
    assert sample.power_draw_w is None  # not fabricated as 0
    assert sample.memory_used_mb == 20480.0


def test_sample_gpu_once_returns_none_when_binary_missing():
    with patch("app.benchmark.gpu_sampler.subprocess.run", side_effect=FileNotFoundError()):
        assert sample_gpu_once() is None


def test_sample_gpu_once_returns_none_on_timeout():
    with patch(
        "app.benchmark.gpu_sampler.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=5.0),
    ):
        assert sample_gpu_once() is None


def test_sample_gpu_once_returns_none_on_nonzero_exit():
    with patch("app.benchmark.gpu_sampler.subprocess.run", return_value=_run(returncode=1)):
        assert sample_gpu_once() is None


def test_sample_gpu_once_returns_none_on_malformed_output():
    with patch("app.benchmark.gpu_sampler.subprocess.run", return_value=_run(stdout="garbage\n")):
        assert sample_gpu_once() is None
