#!/usr/bin/env python3
"""Regenerates ../../examples/*.v0_1.json from the real demo fixtures and
the real app.core.engine pipeline — nothing in examples/ is hand-written.

Run with the api/ virtualenv active, from either the repo root or api/ —
its own working directory doesn't matter, only the venv does:

    python api/scripts/generate_examples.py      # from the repo root
    python scripts/generate_examples.py          # from api/

If app/fixtures/*.json or app.core.engine's behavior change, rerun this to
keep examples/ in sync — nothing else regenerates them automatically.
tests/test_v0_1_schemas.py validates that the checked-in files still parse
and still match the demo's known behavior, but it does not regenerate them.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `app` importable regardless of the caller's working directory — this
# script lives in api/scripts/, but `app` is a package rooted at api/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.engine.feasibility import evaluate_feasibility  # noqa: E402
from app.core.engine.ranking import normalize_and_weight
from app.core.engine.scoring import score_candidate
from app.core.schemas import LATENCY_METRIC_KEY, THROUGHPUT_METRIC_KEY
from app.core.schemas.v0_1 import PerformanceEvidence, PlacementDecision
from app.data.loader import (
    get_performance_profile,
    get_workload,
    load_compute_targets,
)
from app.engine.evidence_gateway import resolve_evidence

_REQUIRED_METRICS = (LATENCY_METRIC_KEY, THROUGHPUT_METRIC_KEY)

EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"


def _write(path: Path, model) -> None:
    path.write_text(model.model_dump_json(indent=2) + "\n")
    print(f"wrote {path}")


def main() -> None:
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    # 1. ComputeTarget — a real fixture entry, loaded + re-dumped through
    #    the versioned schema (so schema_version/accelerator_count appear).
    h100 = next(t for t in load_compute_targets() if t.id == "nvidia-h100-dc")
    _write(EXAMPLES_DIR / "compute_target.v0_1.json", h100)

    # 2. AIWorkload — the flagship realtime-inference workload.
    workload = get_workload("wl-llama70b-rt")
    assert workload is not None
    _write(EXAMPLES_DIR / "ai_workload.v0_1.json", workload)

    # 3. PerformanceEvidence — the H100/llama70b fixture row (this
    #    workload's synthetic demo current-placement baseline; MODELED, not
    #    a real measurement — see api/app/fixtures/performance_profiles.json).
    profile = get_performance_profile("wl-llama70b-rt", "nvidia-h100-dc")
    assert profile is not None
    evidence = PerformanceEvidence.from_performance_profile(profile)
    _write(EXAMPLES_DIR / "performance_evidence.v0_1.json", evidence)

    # 4. PlacementDecision — the real baseline decision for wl-llama70b-rt,
    #    built by running the actual core pipeline against real fixtures.
    #    score_candidate() takes already-*selected* evidence, not a raw
    #    fixture profile — resolve_evidence() is the same gather+select step
    #    app.engine.decision.run_decision() uses (docs/decision-engine.md);
    #    benchmark_runs=[] here since this script only regenerates from the
    #    static fixture catalog, not any locally saved `forgeway bench` run.
    targets = load_compute_targets()
    targets_by_id = {t.id: t for t in targets}
    candidates = []
    for target in targets:
        checks = evaluate_feasibility(workload, target)
        target_evidence = resolve_evidence(
            workload.id, target.id, benchmark_runs=[], required_metrics=_REQUIRED_METRICS
        )
        candidates.append(
            score_candidate(
                workload=workload,
                target=target,
                evidence=target_evidence,
                checks=checks,
                required_throughput=workload.slo.min_throughput_tokens_per_s,
                free_capacity_units=target.free_capacity_units,
            )
        )
    slo_compliant = [c for c in candidates if c.feasible and c.predicted and c.predicted.meets_slo]
    for c in slo_compliant:
        c.meets_confidence_requirement = (c.confidence_pct or 0) >= workload.min_confidence_pct
    qualifying = [c for c in slo_compliant if c.meets_confidence_requirement]
    normalize_and_weight(qualifying, workload, {}, targets_by_id)
    qualifying.sort(key=lambda c: c.weighted_score or 0.0, reverse=True)
    for rank, c in enumerate(qualifying, start=1):
        c.rank = rank

    decision = PlacementDecision.from_candidates(workload, candidates)
    _write(EXAMPLES_DIR / "placement_decision.v0_1.json", decision)

    print(f"recommended_target_id: {decision.recommended_target_id}")


if __name__ == "__main__":
    main()
