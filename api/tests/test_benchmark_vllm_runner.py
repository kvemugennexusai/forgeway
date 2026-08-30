"""Tests for app.benchmark.vllm_runner — the orchestration layer.
subprocess.Popen is replaced with a fake that never touches a real
process, nvidia-smi sampling is stubbed via sample_gpu_once, and
time.sleep/time.monotonic are patched so nothing here actually waits.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.benchmark.errors import BenchmarkError
from app.benchmark.gpu_sampler import GpuSample
from app.benchmark.vllm_runner import is_vllm_available, run_vllm_bench_latency


def _fake_popen_class(
    *,
    poll_sequence: list,
    returncode: int = 0,
    stderr_text: str = "",
    write_output: bool = True,
    output_json: dict | None = None,
):
    class _FakePopen:
        def __init__(self, cmd, stdout=None, stderr=None):
            self.cmd = cmd
            self.returncode = returncode
            self._poll_sequence = list(poll_sequence)
            if write_output:
                idx = cmd.index("--output-json")
                Path(cmd[idx + 1]).write_text(json.dumps(output_json if output_json is not None else {"avg_latency": 1.0}))
            if stderr is not None and stderr_text:
                stderr.write(stderr_text)
                stderr.flush()

        def poll(self):
            if self._poll_sequence:
                return self._poll_sequence.pop(0)
            return self.returncode

        def wait(self):
            return self.returncode

        def kill(self):
            pass

    return _FakePopen


def test_is_vllm_available_true_when_on_path():
    with patch("app.benchmark.vllm_runner.shutil.which", return_value="/usr/local/bin/vllm"):
        assert is_vllm_available() is True


def test_is_vllm_available_false_when_missing():
    with patch("app.benchmark.vllm_runner.shutil.which", return_value=None):
        assert is_vllm_available() is False


def test_run_raises_when_vllm_not_available():
    with patch("app.benchmark.vllm_runner.shutil.which", return_value=None):
        with pytest.raises(BenchmarkError, match="not installed"):
            run_vllm_bench_latency(model="m", input_tokens=1, output_tokens=1, concurrency=1)


def test_run_happy_path_returns_raw_json_and_gpu_samples():
    fake_sample = GpuSample(power_draw_w=150.0, memory_used_mb=8000.0)
    fake_popen = _fake_popen_class(poll_sequence=[None, 0], output_json={"avg_latency": 0.5, "percentiles": {"50": 0.4}})

    with (
        patch("app.benchmark.vllm_runner.shutil.which", return_value="/usr/local/bin/vllm"),
        patch("app.benchmark.vllm_runner.subprocess.Popen", fake_popen),
        patch("app.benchmark.vllm_runner.sample_gpu_once", return_value=fake_sample),
        patch("app.benchmark.vllm_runner.time.sleep"),
    ):
        result = run_vllm_bench_latency(model="meta-llama/Llama-3.1-8B-Instruct", input_tokens=512, output_tokens=128, concurrency=1)

    assert result.raw_json == {"avg_latency": 0.5, "percentiles": {"50": 0.4}}
    assert len(result.gpu_samples) == 2  # one sample per poll() call in the sequence above
    assert all(s == fake_sample for s in result.gpu_samples)


def test_run_builds_the_expected_command():
    captured_cmd = {}

    class _CapturingPopen:
        def __init__(self, cmd, stdout=None, stderr=None):
            captured_cmd["cmd"] = list(cmd)
            idx = cmd.index("--output-json")
            Path(cmd[idx + 1]).write_text(json.dumps({"avg_latency": 1.0}))
            self.returncode = 0

        def poll(self):
            return 0

        def wait(self):
            return 0

        def kill(self):
            pass

    with (
        patch("app.benchmark.vllm_runner.shutil.which", return_value="/usr/local/bin/vllm"),
        patch("app.benchmark.vllm_runner.subprocess.Popen", _CapturingPopen),
        patch("app.benchmark.vllm_runner.sample_gpu_once", return_value=None),
        patch("app.benchmark.vllm_runner.time.sleep"),
    ):
        run_vllm_bench_latency(
            model="meta-llama/Llama-3.1-8B-Instruct",
            input_tokens=512,
            output_tokens=128,
            concurrency=4,
            iterations=5,
            warmup_iterations=2,
        )

    cmd = captured_cmd["cmd"]
    assert cmd[:3] == ["vllm", "bench", "latency"]
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "meta-llama/Llama-3.1-8B-Instruct"
    assert cmd[cmd.index("--input-len") + 1] == "512"
    assert cmd[cmd.index("--output-len") + 1] == "128"
    assert cmd[cmd.index("--batch-size") + 1] == "4"
    assert cmd[cmd.index("--num-iters") + 1] == "5"
    assert cmd[cmd.index("--num-iters-warmup") + 1] == "2"


def test_run_raises_on_nonzero_exit_with_stderr_in_message():
    fake_popen = _fake_popen_class(poll_sequence=[0], returncode=1, stderr_text="CUDA out of memory")

    with (
        patch("app.benchmark.vllm_runner.shutil.which", return_value="/usr/local/bin/vllm"),
        patch("app.benchmark.vllm_runner.subprocess.Popen", fake_popen),
        patch("app.benchmark.vllm_runner.sample_gpu_once", return_value=None),
        patch("app.benchmark.vllm_runner.time.sleep"),
    ):
        with pytest.raises(BenchmarkError, match="CUDA out of memory"):
            run_vllm_bench_latency(model="m", input_tokens=1, output_tokens=1, concurrency=1)


def test_run_raises_when_no_output_file_produced():
    fake_popen = _fake_popen_class(poll_sequence=[0], write_output=False)

    with (
        patch("app.benchmark.vllm_runner.shutil.which", return_value="/usr/local/bin/vllm"),
        patch("app.benchmark.vllm_runner.subprocess.Popen", fake_popen),
        patch("app.benchmark.vllm_runner.sample_gpu_once", return_value=None),
        patch("app.benchmark.vllm_runner.time.sleep"),
    ):
        with pytest.raises(BenchmarkError, match="no output file"):
            run_vllm_bench_latency(model="m", input_tokens=1, output_tokens=1, concurrency=1)


def test_run_raises_and_kills_process_on_timeout():
    fake_popen = _fake_popen_class(poll_sequence=[None] * 10)
    killed = {"called": False}

    class _TimeoutPopen(fake_popen):
        def kill(self):
            killed["called"] = True

    with (
        patch("app.benchmark.vllm_runner.shutil.which", return_value="/usr/local/bin/vllm"),
        patch("app.benchmark.vllm_runner.subprocess.Popen", _TimeoutPopen),
        patch("app.benchmark.vllm_runner.sample_gpu_once", return_value=None),
        patch("app.benchmark.vllm_runner.time.sleep"),
        patch("app.benchmark.vllm_runner.time.monotonic", side_effect=[0.0, 1000.0]),
    ):
        with pytest.raises(BenchmarkError, match="did not finish within"):
            run_vllm_bench_latency(model="m", input_tokens=1, output_tokens=1, concurrency=1, timeout_s=5.0)

    assert killed["called"] is True
