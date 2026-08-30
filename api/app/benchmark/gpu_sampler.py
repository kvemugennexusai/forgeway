"""Best-effort GPU telemetry sampling via nvidia-smi, independent of
whatever benchmark is running. app.benchmark.vllm_runner polls this while
a benchmark subprocess executes, to get a genuine time-averaged power
draw and a real peak memory-used figure — not a single before/after
snapshot mislabeled as an average.

A failed sample is never fatal and never raised: GPU telemetry is
explicitly "if safely obtainable" (docs/benchmarking.md) — optional
context, not a required benchmark result. If nvidia-smi is missing,
times out, or reports "N/A" (common for power draw on GPUs/drivers
without power-management reporting), that one sample is just skipped.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class GpuSample:
    power_draw_w: Optional[float]
    memory_used_mb: Optional[float]


def _safe_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except ValueError:
        return None  # e.g. "N/A" or "[N/A]" when a driver doesn't report a field


def sample_gpu_once(device_index: int = 0, *, timeout: float = 5.0) -> Optional[GpuSample]:
    """One nvidia-smi query for power draw + memory used on one device.
    Returns None on any failure (missing binary, timeout, non-zero exit,
    unparseable output) rather than raising."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "-i",
                str(device_index),
                "--query-gpu=power.draw,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 2:
        return None
    return GpuSample(power_draw_w=_safe_float(parts[0]), memory_used_mb=_safe_float(parts[1]))
