"""Validated, read-only saved inputs for analyze; no placement policy lives here."""
from __future__ import annotations

import json
import math
from pathlib import Path

from app.benchmark.cross_vendor import CrossVendorEvidenceRecord
from app.benchmark.store import list_runs
from app.cli.yaml_io import AnalyzeError
from app.core.schemas import (
    LATENCY_METRIC_KEY,
    THROUGHPUT_METRIC_KEY,
    ComputeTarget,
    PerformanceEvidence,
)


def _record(raw: dict, model, version: str):
    if not isinstance(raw, dict) or raw.get("schema_version") != version:
        raise ValueError(f"expected explicit schema_version '{version}'")
    return model.model_validate(raw)


def _id(value: str | None, label: str):
    if not value or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be a nonempty ID without surrounding whitespace")


def load_saved_input(path: str, *, target: bool):
    """One JSON object per file: ComputeTarget, PerformanceEvidence, or envelope."""
    try:
        raw = json.loads(Path(path).read_text())
        if target:
            result = _record(raw, ComputeTarget, "forgeway/v0.1")
            _id(result.id, "target.id")
            return result
        if isinstance(raw, dict) and "performance_evidence" in raw:
            envelope = _record(raw, CrossVendorEvidenceRecord, "forgeway-cross-vendor/v0.1")
            _record(raw["target"], ComputeTarget, "forgeway/v0.1")
            _record(raw["performance_evidence"], PerformanceEvidence, "forgeway/v0.1")
            result = envelope.to_performance_evidence()
            _id(envelope.target.id, "target.id")
            _id(envelope.run_id, "run_id")
            if envelope.target.id != result.compute_target_id:
                raise ValueError("envelope target.id differs from performance_evidence.compute_target_id")
            if envelope.run_id != result.benchmark_run_id:
                raise ValueError("envelope run_id differs from performance_evidence.benchmark_run_id")
        else:
            result = _record(raw, PerformanceEvidence, "forgeway/v0.1")
        _id(result.compute_target_id, "compute_target_id")
        _id(result.workload_id, "workload_id")
        if result.benchmark_run_id is not None:
            _id(result.benchmark_run_id, "benchmark_run_id")
        for key in (THROUGHPUT_METRIC_KEY, LATENCY_METRIC_KEY):
            metric = result.metrics.get(key)
            if metric is None:
                continue  # Missing metrics remain the engine's insufficient-evidence case.
            positive = key == THROUGHPUT_METRIC_KEY
            if not math.isfinite(metric.value) or (metric.value <= 0 if positive else metric.value < 0):
                constraint = "strictly positive" if positive else "non-negative"
                raise ValueError(f"metrics.{key}.value must be finite and {constraint}")
        return result
    except (OSError, ValueError) as exc:
        raise AnalyzeError(f"{path}: {exc}") from exc


def validate_evidence(evidence: list[PerformanceEvidence], targets: list[ComputeTarget], workload_id: str):
    if not evidence:
        return
    target_ids = {t.id for t in targets}
    seen = set()
    stored: dict[str, list[PerformanceEvidence]] = {}
    for run in list_runs():
        if run.benchmark_run_id:
            stored.setdefault(run.benchmark_run_id, []).append(run)
    for record in evidence:
        if record.compute_target_id not in target_ids:
            raise AnalyzeError(f"evidence target '{record.compute_target_id}' is not in the analyzed targets")
        if record.workload_id != workload_id:
            raise AnalyzeError(f"evidence workload_id '{record.workload_id}' does not match workload '{workload_id}'")
        # Anonymous typed records remain valid; reject repeated identical inputs too.
        key = record.benchmark_run_id or record.model_dump_json()
        if key in seen:
            label = record.benchmark_run_id or "anonymous record"
            raise AnalyzeError(f"duplicate evidence/run ID: {label}")
        seen.add(key)
        prior_records = stored.get(record.benchmark_run_id, [])
        if any(prior != record for prior in prior_records):
            raise AnalyzeError(f"run ID '{record.benchmark_run_id}' collides with different evidence in the benchmark store")


def target_warnings(target: ComputeTarget) -> list[str]:
    missing = []
    if target.memory_gb_per_device <= 0:
        missing.append("memory_gb_per_device unknown/unavailable")
    if not target.supported_precisions:
        missing.append("supported_precisions missing")
    if target.runtime_support is None:
        missing.append("runtime_support unknown")
    if target.interconnect == "not probed":
        missing.append("interconnect not probed")
    if target.price_per_hr_per_unit.confidence == 0:
        missing.append("pricing unavailable/unverified; placeholder is not a free-hardware price")
    return [f"target '{target.id}': {item}" for item in missing]
