"""NVIDIA CUDA-capable local hardware discovery, via `nvidia-smi`.

Scope (v0.1): local NVIDIA GPUs only, queried through the `nvidia-smi` CLI
tool that ships with the NVIDIA driver. No NVML/pynvml bindings (would add
a dependency for no benefit over parsing `nvidia-smi`'s own structured CSV
output), no cloud/remote discovery, no AMD/Intel/Jetson-specific paths —
see docs/discovery.md for what's deliberately out of scope.
"""
from __future__ import annotations

import platform
import re
import shutil
import socket
import subprocess
from datetime import datetime, timezone

from app.core.schemas import ComputeTarget, Metric
from app.discovery.adapter import DiscoveryAdapter, DiscoveryError

_QUERY_FIELDS = [
    "index",
    "name",
    "memory.total",
    "memory.used",
    "memory.free",
    "utilization.gpu",
    "utilization.memory",
    "driver_version",
    "compute_cap",
]

# Best-effort compute-capability -> architecture codename mapping. Not
# exhaustive — an unrecognized major version falls back to a labeled
# "unknown" string rather than a guess. See docs/discovery.md.
_ARCHITECTURE_BY_COMPUTE_CAP_MAJOR: dict[str, str] = {
    "9": "hopper",
    "8": "ampere-or-ada",  # 8.0/8.6/8.7 = ampere, 8.9 = ada-lovelace — see note below
    "7": "turing-or-volta",  # 7.5 = turing, 7.0/7.2 = volta
    "6": "pascal",
    "5": "maxwell",
}

# Compute capabilities specific enough to resolve the 8.x/7.x ambiguity above.
_ARCHITECTURE_BY_EXACT_COMPUTE_CAP: dict[str, str] = {
    "8.9": "ada-lovelace",
    "8.7": "ampere",
    "8.6": "ampere",
    "8.0": "ampere",
    "7.5": "turing",
    "7.2": "volta",
    "7.0": "volta",
}

_CUDA_VERSION_RE = re.compile(r"CUDA Version:\s*([\d.]+)")


def _architecture_for(compute_cap: str) -> str:
    if compute_cap in _ARCHITECTURE_BY_EXACT_COMPUTE_CAP:
        return _ARCHITECTURE_BY_EXACT_COMPUTE_CAP[compute_cap]
    major = compute_cap.split(".")[0] if compute_cap else ""
    if major in _ARCHITECTURE_BY_COMPUTE_CAP_MAJOR:
        return _ARCHITECTURE_BY_COMPUTE_CAP_MAJOR[major]
    return f"unknown (compute capability {compute_cap or 'unreported'})"


def _run_query_gpu(timeout: float = 5.0) -> str:
    """Runs `nvidia-smi --query-gpu=... --format=csv,noheader,nounits` and
    returns its stdout. Raises DiscoveryError on a non-zero exit, a
    missing binary, or a timeout — never lets subprocess's own exceptions
    escape to the caller."""
    cmd = ["nvidia-smi", f"--query-gpu={','.join(_QUERY_FIELDS)}", "--format=csv,noheader,nounits"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise DiscoveryError("nvidia-smi is not installed or not on PATH") from e
    except subprocess.TimeoutExpired as e:
        raise DiscoveryError(f"nvidia-smi did not respond within {timeout:.0f}s") from e
    if result.returncode != 0:
        raise DiscoveryError(
            f"nvidia-smi exited with code {result.returncode}: {result.stderr.strip() or '(no stderr)'}"
        )
    return result.stdout


def _run_version_banner(timeout: float = 5.0) -> str:
    """Runs plain `nvidia-smi` (no query flags) to read its text banner,
    which is the only place nvidia-smi reports the driver's supported CUDA
    version — there is no --query-gpu field for it. Best-effort: returns
    "" on any failure rather than raising, since CUDA version is
    explicitly "where discoverable", not required."""
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout


def _parse_gpu_rows(csv_output: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in csv_output.strip().splitlines():
        if not line.strip():
            continue
        values = [v.strip() for v in line.split(",")]
        if len(values) != len(_QUERY_FIELDS):
            raise DiscoveryError(
                f"unexpected nvidia-smi output shape (expected {len(_QUERY_FIELDS)} fields, "
                f"got {len(values)}): {line!r}"
            )
        rows.append(dict(zip(_QUERY_FIELDS, values)))
    return rows


def _parse_float(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0


class NvidiaDiscoveryAdapter(DiscoveryAdapter):
    name = "NVIDIA"

    def is_available(self) -> bool:
        return shutil.which("nvidia-smi") is not None

    def discover(self) -> ComputeTarget:
        csv_output = _run_query_gpu()
        rows = _parse_gpu_rows(csv_output)
        if not rows:
            raise DiscoveryError("nvidia-smi ran successfully but reported zero GPUs")

        first = rows[0]
        models = {r["name"] for r in rows}
        heterogeneous_note = ""
        if len(models) > 1:
            heterogeneous_note = (
                f" NOTE: this machine has {len(models)} different GPU models "
                f"({', '.join(sorted(models))}); only the first device's specs "
                "(model, memory, architecture) are reflected below — heterogeneous "
                "GPU machines are not fully modeled in this adapter yet."
            )

        memory_total_gb = _parse_float(first["memory.total"]) / 1024
        avg_gpu_util = sum(_parse_float(r["utilization.gpu"]) for r in rows) / len(rows)
        avg_mem_util = sum(_parse_float(r["utilization.memory"]) for r in rows) / len(rows)

        # memory.free/memory.used have no home in ComputeTarget's schema yet
        # (only free_capacity_units — a device-count concept, not a memory-
        # size one — exists). Surfaced here as free text, the same treatment
        # already given to driver/CUDA version, rather than silently dropped.
        free_memory_summary = "; ".join(
            f"GPU {r['index']}: {_parse_float(r['memory.free']) / 1024:.1f}/"
            f"{_parse_float(r['memory.total']) / 1024:.1f} GB free"
            for r in rows
        )

        cuda_version = ""
        match = _CUDA_VERSION_RE.search(_run_version_banner())
        if match:
            cuda_version = match.group(1)

        hostname = socket.gethostname()
        os_platform = platform.platform()

        notes = (
            f"Discovered via nvidia-smi on {hostname} ({os_platform}). "
            f"Driver version: {first['driver_version']}. "
            f"CUDA version: {cuda_version or 'not discoverable'}. "
            f"Free device memory — {free_memory_summary}. "
            "price_per_hr_per_unit is a placeholder — there is no real "
            "hourly cost for locally discovered hardware; set it manually "
            "before using this target in cost-based placement decisions. "
            "supported_precisions is not auto-detected in this adapter — "
            "set it manually based on this GPU's known capabilities."
            f"{heterogeneous_note}"
        )

        return ComputeTarget(
            id=f"local-nvidia-{hostname}".lower().replace(" ", "-"),
            vendor="nvidia",
            model=first["name"],
            tier="lab",
            location=f"local ({hostname})",
            architecture=_architecture_for(first["compute_cap"]),
            memory_gb_per_device=round(memory_total_gb, 1),
            interconnect="not probed",
            supported_precisions=[],
            capacity_units_total=len(rows),
            capacity_units_allocated=0,
            price_per_hr_per_unit=Metric(
                value=0.0,
                confidence=0,
                provenance="MODELED",
                source="No pricing available for locally discovered hardware.",
            ),
            status="healthy",
            notes=notes,
            observed_gpu_utilization_pct=round(avg_gpu_util, 1),
            observed_memory_utilization_pct=round(avg_mem_util, 1),
            discovered_at=datetime.now(timezone.utc),
        )
