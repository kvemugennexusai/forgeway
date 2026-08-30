"""Saves and lists locally-stored benchmark runs — plain JSON files on
disk, one PerformanceEvidence per run, no database. Deliberately the
simplest thing that works: this is a single-user CLI tool, not a service.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from app.core.schemas.v0_1 import PerformanceEvidence

_RAW_OUTPUT_SUFFIX = ".raw_vllm_output.json"


def results_dir() -> Path:
    """~/.forgeway/benchmarks by default; override with FORGEWAY_BENCH_DIR
    (used by tests to isolate runs in a tmp directory, and available to
    anyone who'd rather not use the home directory)."""
    override = os.environ.get("FORGEWAY_BENCH_DIR")
    return Path(override) if override else Path.home() / ".forgeway" / "benchmarks"


def save_run(evidence: PerformanceEvidence, *, raw_output: dict | None = None) -> Path:
    """Saves <run_id>.json (the PerformanceEvidence record) and, if given,
    <run_id>.raw_vllm_output.json alongside it — the exact JSON vLLM
    produced, kept for anyone who wants to double-check this adapter's
    parsing against what vLLM actually reported for that run (see
    docs/benchmarking.md's reproducibility caveats). Returns the path to
    the saved PerformanceEvidence file."""
    run_id = evidence.benchmark_run_id or "unknown-run"
    directory = results_dir()
    directory.mkdir(parents=True, exist_ok=True)

    evidence_path = directory / f"{run_id}.json"
    evidence_path.write_text(evidence.model_dump_json(indent=2) + "\n")

    if raw_output is not None:
        (directory / f"{run_id}{_RAW_OUTPUT_SUFFIX}").write_text(json.dumps(raw_output, indent=2) + "\n")

    return evidence_path


def list_runs() -> list[PerformanceEvidence]:
    """All saved runs, oldest filename first. A file that fails to parse
    as a PerformanceEvidence (foreign JSON someone dropped in the
    directory, a raw-output file, a future/incompatible schema version) is
    skipped rather than crashing `forgeway runs` for everyone."""
    directory = results_dir()
    if not directory.exists():
        return []

    runs: list[PerformanceEvidence] = []
    for path in sorted(directory.glob("*.json")):
        if path.name.endswith(_RAW_OUTPUT_SUFFIX):
            continue
        try:
            runs.append(PerformanceEvidence.model_validate_json(path.read_text()))
        except (ValueError, OSError):
            continue
    return runs
