"""Normalizes cost/performance/headroom across a qualifying candidate set and
applies the workload's objective weights (steps 7-8 of the decision
pipeline). Pure — takes the compute targets it needs as an argument rather
than loading them itself — so it works the same whether those targets came
from a JSON fixture, a live discovery adapter, or a benchmark run.
"""
from __future__ import annotations

from app.core.schemas import CandidateEvaluation, ComputeTarget, NormalizedScores, Workload


def normalize_and_weight(
    qualifying: list[CandidateEvaluation],
    workload: Workload,
    capacity_overrides: dict[str, int],
    targets_by_id: dict[str, ComputeTarget],
) -> None:
    """Min-max normalize cost (lower better), performance — P99 latency
    (lower better) — and headroom — spare capacity left behind (higher
    better) — across the qualifying candidate set, then blend them with the
    workload's (normalized) objective weights. Mutates each candidate in
    place.

    Precondition: every candidate in `qualifying` must already have
    `predicted` set and a `target_id` present in `targets_by_id` — i.e. it
    already cleared feasibility and the SLO/sizing gate (app.core.engine.
    scoring.score_candidate). This function only ranks candidates that
    already qualify; it does not itself decide who qualifies.
    """
    if not qualifying:
        return

    missing = [c.target_id for c in qualifying if c.predicted is None or c.target_id not in targets_by_id]
    if missing:
        raise ValueError(
            f"normalize_and_weight requires every candidate to have `predicted` set and a "
            f"matching entry in targets_by_id; missing/unqualified target_id(s): {missing}"
        )

    costs = [c.predicted.cost_per_hr for c in qualifying]  # type: ignore[union-attr]
    latencies = [c.predicted.p99_latency_ms for c in qualifying]  # type: ignore[union-attr]
    headrooms = []
    for c in qualifying:
        target = targets_by_id[c.target_id]
        free_before = capacity_overrides.get(c.target_id, target.free_capacity_units)
        free_after = max(free_before - c.predicted.replica_count, 0)  # type: ignore[union-attr]
        headrooms.append(free_after / target.capacity_units_total if target.capacity_units_total else 0.0)

    def norm(values: list[float], i: int, *, higher_is_better: bool) -> float:
        lo, hi = min(values), max(values)
        if hi - lo <= 1e-9:
            return 1.0
        return (values[i] - lo) / (hi - lo) if higher_is_better else (hi - values[i]) / (hi - lo)

    weights = workload.objective_weights.normalized()
    for i, c in enumerate(qualifying):
        cost_n = norm(costs, i, higher_is_better=False)
        perf_n = norm(latencies, i, higher_is_better=False)
        headroom_n = norm(headrooms, i, higher_is_better=True)
        c.normalized_scores = NormalizedScores(
            cost=round(cost_n, 4), performance=round(perf_n, 4), headroom=round(headroom_n, 4)
        )
        c.weighted_score = round(
            weights.cost * cost_n + weights.performance * perf_n + weights.headroom * headroom_n, 6
        )
