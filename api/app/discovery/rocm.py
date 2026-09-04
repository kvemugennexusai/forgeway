"""AMD ROCm-capable local hardware discovery, via `rocm-smi`.

Scope (v0.1): local AMD GPUs only, queried through the `rocm-smi` CLI tool
that ships with the ROCm stack. Second DiscoveryAdapter (ROADMAP.md); shares
nothing but the DiscoveryAdapter interface with app/discovery/nvidia.py —
rocm-smi's own output shape has nothing in common with nvidia-smi's.

rocm-smi's `--json` output is not a stable, long-documented schema the way
nvidia-smi's `--query-gpu` CSV is — its key names and casing have varied
across ROCm releases in the wild (e.g. "Card series" vs "Card Series"), and
there is no public compute-capability-equivalent field for architecture the
way CUDA's compute_cap is. This adapter compensates by doing case-insensitive
field lookups and, for architecture, a best-effort substring match against
known AMD product names — falling back to an explicit "unknown" label rather
than guessing, same convention as nvidia.py's compute-cap mapping. See
docs/discovery.md for what's captured and what's a placeholder.
"""
from __future__ import annotations

import json
import platform
import re
import shutil
import socket
import subprocess
from datetime import datetime, timezone
from typing import Optional

from app.core.schemas import ComputeTarget, Metric
from app.discovery.adapter import DiscoveryAdapter, DiscoveryError

_SHOW_ARGS = ["--showproductname", "--showuniqueid", "--showmeminfo", "vram", "--showuse", "--json"]

_CARD_KEY_RE = re.compile(r"^card\d+$", re.IGNORECASE)

_VERSION_RE = re.compile(r"\d+(?:\.\d+){1,3}")

# Best-effort product-name substring -> architecture codename mapping. Not
# exhaustive — an unrecognized model falls back to a labeled "unknown"
# string rather than a guess. See module docstring and docs/discovery.md.
_ARCHITECTURE_BY_MODEL_SUBSTRING: list[tuple[str, str]] = [
    ("mi300", "cdna3"),
    ("mi250", "cdna2"),
    ("mi210", "cdna2"),
    ("mi100", "cdna"),
    ("rx 7", "rdna3"),
    ("rx 6", "rdna2"),
]


def _architecture_for(model: str) -> str:
    lowered = model.lower()
    for substring, arch in _ARCHITECTURE_BY_MODEL_SUBSTRING:
        if substring in lowered:
            return arch
    return f"unknown (rocm-smi doesn't report a compute-capability equivalent for {model!r})"


def _run_show_query(timeout: float = 5.0) -> str:
    """Runs `rocm-smi --showproductname --showuniqueid --showmeminfo vram
    --showuse --json` and returns its stdout. Raises DiscoveryError on a
    non-zero exit, a missing binary, or a timeout — never lets subprocess's
    own exceptions escape to the caller."""
    cmd = ["rocm-smi", *_SHOW_ARGS]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise DiscoveryError("rocm-smi is not installed or not on PATH") from e
    except subprocess.TimeoutExpired as e:
        raise DiscoveryError(f"rocm-smi did not respond within {timeout:.0f}s") from e
    if result.returncode != 0:
        raise DiscoveryError(
            f"rocm-smi exited with code {result.returncode}: {result.stderr.strip() or '(no stderr)'}"
        )
    return result.stdout


def _run_driver_version_query(timeout: float = 5.0) -> str:
    """Runs `rocm-smi --showdriverversion --json`, best-effort: returns ""
    on any failure rather than raising, since driver version is explicitly
    "where discoverable", not required — mirrors nvidia.py's CUDA-version
    banner treatment."""
    try:
        result = subprocess.run(
            ["rocm-smi", "--showdriverversion", "--json"], capture_output=True, text=True, timeout=timeout
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout


def _extract_driver_version(raw_json: str) -> str:
    """Best-effort extraction of a version-looking string from whatever
    shape --showdriverversion's JSON turns out to have (its key naming
    isn't documented as stable — see module docstring). Never raises."""
    if not raw_json:
        return ""
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        return ""

    def walk(node: object) -> Optional[str]:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and "driver" in key.lower():
                    match = _VERSION_RE.search(value)
                    if match:
                        return match.group(0)
            for value in node.values():
                found = walk(value)
                if found:
                    return found
        return None

    return walk(parsed) or ""


def _parse_show_output(raw_json: str) -> dict[str, dict[str, str]]:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as e:
        raise DiscoveryError(f"rocm-smi produced unparseable JSON output: {e}") from e
    if not isinstance(parsed, dict):
        raise DiscoveryError(
            f"unexpected rocm-smi JSON shape (expected a JSON object, got {type(parsed).__name__})"
        )
    cards = {k: v for k, v in parsed.items() if _CARD_KEY_RE.match(k) and isinstance(v, dict)}
    if not cards:
        raise DiscoveryError("rocm-smi ran successfully but reported zero GPUs (no 'cardN' entries in its output)")
    return cards


def _lookup(fields: dict[str, str], name: str) -> Optional[str]:
    """Case-insensitive field lookup — rocm-smi's JSON key casing for the
    same field has varied across ROCm releases (see module docstring)."""
    lowered = {k.lower(): v for k, v in fields.items()}
    return lowered.get(name.lower())


def _parse_float(value: Optional[str]) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


class RocmDiscoveryAdapter(DiscoveryAdapter):
    name = "AMD ROCm"

    def is_available(self) -> bool:
        return shutil.which("rocm-smi") is not None

    def discover(self) -> ComputeTarget:
        cards = _parse_show_output(_run_show_query())

        rows: list[dict[str, object]] = []
        for key in sorted(cards):
            fields = cards[key]
            model = _lookup(fields, "Card series")
            vram_total_str = _lookup(fields, "VRAM Total Memory (B)")
            if model is None or vram_total_str is None:
                raise DiscoveryError(
                    f"unexpected rocm-smi JSON shape for {key} (missing 'Card series' or "
                    f"'VRAM Total Memory (B)'): {fields!r}"
                )
            vram_total_gb = _parse_float(vram_total_str) / (1024**3)
            vram_used_gb = _parse_float(_lookup(fields, "VRAM Total Used Memory (B)")) / (1024**3)
            rows.append(
                {
                    "model": model,
                    "vram_total_gb": vram_total_gb,
                    "vram_used_gb": vram_used_gb,
                    "gpu_use_pct": _parse_float(_lookup(fields, "GPU use (%)")),
                    "unique_id": _lookup(fields, "Unique ID") or "",
                }
            )

        first = rows[0]
        models = {r["model"] for r in rows}
        heterogeneous_note = ""
        if len(models) > 1:
            heterogeneous_note = (
                f" NOTE: this machine has {len(models)} different GPU models "
                f"({', '.join(sorted(models))}); only the first device's specs "
                "(model, memory, architecture) are reflected below — heterogeneous "
                "GPU machines are not fully modeled in this adapter yet."
            )

        avg_gpu_util = sum(r["gpu_use_pct"] for r in rows) / len(rows)
        avg_mem_util = sum(
            (r["vram_used_gb"] / r["vram_total_gb"] * 100) if r["vram_total_gb"] else 0.0 for r in rows
        ) / len(rows)

        # VRAM has no home in ComputeTarget's schema beyond memory_gb_per_device
        # (a total-capacity concept, not a free/used one) — surfaced here as
        # free text, the same treatment nvidia.py gives its own free-memory
        # figures, rather than silently dropped.
        free_memory_summary = "; ".join(
            f"GPU {i}: {max(r['vram_total_gb'] - r['vram_used_gb'], 0):.1f}/{r['vram_total_gb']:.1f} GB free"
            for i, r in enumerate(rows)
        )

        driver_version = _extract_driver_version(_run_driver_version_query())
        hostname = socket.gethostname()
        os_platform = platform.platform()

        unique_id_note = f" Unique ID: {first['unique_id']}." if first["unique_id"] else ""

        notes = (
            f"Discovered via rocm-smi on {hostname} ({os_platform}). "
            f"Driver version: {driver_version or 'not discoverable'}."
            f"{unique_id_note} "
            f"Free device memory — {free_memory_summary}. "
            "price_per_hr_per_unit is a placeholder — there is no real "
            "hourly cost for locally discovered hardware; set it manually "
            "before using this target in cost-based placement decisions. "
            "supported_precisions is not auto-detected in this adapter — "
            "set it manually based on this GPU's known capabilities."
            f"{heterogeneous_note}"
        )

        return ComputeTarget(
            id=f"local-amd-{hostname}".lower().replace(" ", "-"),
            vendor="amd",
            model=first["model"],
            tier="lab",
            location=f"local ({hostname})",
            architecture=_architecture_for(first["model"]),
            memory_gb_per_device=round(first["vram_total_gb"], 1),
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
