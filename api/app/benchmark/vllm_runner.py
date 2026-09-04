"""Orchestrates one `vllm bench latency` run: builds the command, launches
it as a subprocess, samples GPU telemetry while it runs
(app.benchmark.gpu_sampler), and hands back the raw JSON it produced plus
the GPU samples collected.

Deliberately does not parse vLLM's JSON itself (app.benchmark.parser) or
know about PerformanceEvidence (app.benchmark.evidence) — this module's
only job is running the external tool and getting its output back, so it
can be tested (mocking subprocess.Popen) independent of parsing/evidence
concerns.

Scope: local NVIDIA CUDA or AMD ROCm systems, one benchmark path — `vllm
bench latency`, an offline (no server) per-request latency benchmark. The
`vllm bench latency` subprocess and command line are identical either way
(PyTorch/HIP handle device dispatch underneath); `gpu_vendor` here only
selects which vendor's telemetry sampler (app.benchmark.gpu_sampler for
NVIDIA, app.benchmark.rocm_gpu_sampler for AMD) polls memory/power while it
runs. See docs/benchmarking.md for why this path was chosen and what it
does not measure (notably: no TTFT — that needs a streaming/serving
benchmark like `vllm bench serve`, not this one), and for the real
dependency gap between the two vendors — `pip install vllm` gets you the
CUDA build; a ROCm-capable vllm needs a heavier, ROCm-specific install.

Subprocess I/O note: stdout/stderr are redirected to temp files, not
subprocess.PIPE — vLLM can write more logging output than a pipe's OS
buffer while we're busy polling GPU telemetry instead of draining it,
which would deadlock the child process. Files avoid that risk entirely.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.benchmark.errors import BenchmarkError
from app.benchmark.gpu_sampler import GpuSample, sample_gpu_once
from app.benchmark.rocm_gpu_sampler import sample_gpu_once as sample_gpu_once_rocm

DEFAULT_ITERATIONS = 3
DEFAULT_WARMUP_ITERATIONS = 1
DEFAULT_TIMEOUT_S = 600.0
DEFAULT_SAMPLE_INTERVAL_S = 1.0
DEFAULT_PERCENTILES = "50,99"

_STDERR_TAIL_CHARS = 2000


@dataclass
class RawBenchmarkResult:
    raw_json: dict
    gpu_samples: list[GpuSample] = field(default_factory=list)


def is_vllm_available() -> bool:
    return shutil.which("vllm") is not None


def run_vllm_bench_latency(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    concurrency: int,
    iterations: int = DEFAULT_ITERATIONS,
    warmup_iterations: int = DEFAULT_WARMUP_ITERATIONS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    sample_interval_s: float = DEFAULT_SAMPLE_INTERVAL_S,
    device_index: int = 0,
    gpu_vendor: str = "nvidia",
) -> RawBenchmarkResult:
    if not is_vllm_available():
        raise BenchmarkError(
            "vllm is not installed or not on PATH. Install it on a CUDA- or ROCm-capable "
            "machine to run this benchmark path — see docs/benchmarking.md."
        )
    # Looked up by name at call time (not bound to a local at import time)
    # so mock.patch("app.benchmark.vllm_runner.sample_gpu_once", ...) and its
    # ROCm counterpart both still work as direct substitutions in tests.
    sampler = sample_gpu_once_rocm if gpu_vendor == "amd" else sample_gpu_once

    output_fd, output_path_str = tempfile.mkstemp(suffix=".json", prefix="forgeway-vllm-bench-")
    os.close(output_fd)
    stdout_fd, stdout_path_str = tempfile.mkstemp(suffix=".log", prefix="forgeway-vllm-bench-stdout-")
    stderr_fd, stderr_path_str = tempfile.mkstemp(suffix=".log", prefix="forgeway-vllm-bench-stderr-")
    os.close(stdout_fd)
    os.close(stderr_fd)
    output_path = Path(output_path_str)
    stdout_path = Path(stdout_path_str)
    stderr_path = Path(stderr_path_str)

    cmd = [
        "vllm",
        "bench",
        "latency",
        "--model",
        model,
        "--input-len",
        str(input_tokens),
        "--output-len",
        str(output_tokens),
        "--batch-size",
        str(concurrency),
        "--num-iters",
        str(iterations),
        "--num-iters-warmup",
        str(warmup_iterations),
        "--percentiles",
        DEFAULT_PERCENTILES,
        "--output-json",
        str(output_path),
    ]

    try:
        with open(stdout_path, "w") as out_f, open(stderr_path, "w") as err_f:
            process = subprocess.Popen(cmd, stdout=out_f, stderr=err_f)

            gpu_samples: list[GpuSample] = []
            start = time.monotonic()
            while True:
                sample = sampler(device_index)
                if sample is not None:
                    gpu_samples.append(sample)
                if process.poll() is not None:
                    break
                if time.monotonic() - start > timeout_s:
                    process.kill()
                    process.wait()
                    raise BenchmarkError(f"vllm bench latency did not finish within {timeout_s:.0f}s")
                time.sleep(sample_interval_s)

        if process.returncode != 0:
            stderr_text = stderr_path.read_text(errors="replace") if stderr_path.exists() else ""
            raise BenchmarkError(
                f"vllm bench latency exited with code {process.returncode}: "
                f"{stderr_text.strip()[-_STDERR_TAIL_CHARS:] or '(no stderr captured)'}"
            )

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise BenchmarkError("vllm bench latency completed but produced no output file")

        raw_json = json.loads(output_path.read_text())
    finally:
        output_path.unlink(missing_ok=True)
        stdout_path.unlink(missing_ok=True)
        stderr_path.unlink(missing_ok=True)

    return RawBenchmarkResult(raw_json=raw_json, gpu_samples=gpu_samples)
