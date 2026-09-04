"""Best-effort GPU telemetry sampling via rocm-smi, independent of whatever
benchmark is running — the AMD equivalent of app.benchmark.gpu_sampler.
Same contract: a failed sample is never fatal and never raised, since GPU
telemetry is optional context, not a required benchmark result.

rocm-smi's JSON key casing has varied across ROCm releases (see
app.discovery.rocm's module docstring for the same caveat on the discovery
side) — this module does its own case-insensitive field lookup rather than
importing app.discovery.rocm's, so it stays independently testable and
functional even if that module changes (same non-sharing convention
gpu_sampler.py already follows relative to app.discovery.nvidia).
"""
from __future__ import annotations

import json
import subprocess
from typing import Optional

from app.benchmark.gpu_sampler import GpuSample

_CARD_KEY_PREFIX = "card"


def _lookup(fields: dict, name: str) -> Optional[str]:
    lowered = {k.lower(): v for k, v in fields.items()}
    return lowered.get(name.lower())


def _safe_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None  # e.g. rocm-smi reporting an unavailable field as text


def sample_gpu_once(device_index: int = 0, *, timeout: float = 5.0) -> Optional[GpuSample]:
    """One rocm-smi query for power draw + VRAM used on one device. Returns
    None on any failure (missing binary, timeout, non-zero exit,
    unparseable output) rather than raising."""
    try:
        result = subprocess.run(
            ["rocm-smi", "-d", str(device_index), "--showmeminfo", "vram", "--showpower", "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None

    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None

    # -d should scope rocm-smi's output to the one requested device, but
    # its top-level key naming isn't guaranteed stable (see module
    # docstring) — fall back to the first card-shaped entry rather than
    # assuming "cardN" matches device_index exactly.
    fields = parsed.get(f"{_CARD_KEY_PREFIX}{device_index}")
    if not isinstance(fields, dict):
        fields = next(
            (v for k, v in parsed.items() if k.lower().startswith(_CARD_KEY_PREFIX) and isinstance(v, dict)),
            None,
        )
    if not isinstance(fields, dict):
        return None

    memory_used_bytes = _safe_float(_lookup(fields, "VRAM Total Used Memory (B)"))
    memory_used_mb = memory_used_bytes / (1024**2) if memory_used_bytes is not None else None
    power_draw_w = _safe_float(_lookup(fields, "Average Graphics Package Power (W)"))

    return GpuSample(power_draw_w=power_draw_w, memory_used_mb=memory_used_mb)
