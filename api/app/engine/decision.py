"""Orchestrates one placement decision, in the exact order every step of the
pipeline depends on the one before it:

 1. Load workload.                          (caller — app/data/loader.py)
 2. Load compute targets.                   (caller — app/data/loader.py)
 3. Evaluate hard compatibility.             (app/engine/feasibility.py)
 4. Return explicit rejection reasons.       (CandidateEvaluation.rejection_reasons)
 5. For feasible targets, retrieve prediction fixture.  (app/engine/scoring.retrieve_prediction)
 6. Check SLO constraints.                   (app/engine/scoring.score_candidate — hard reject)
 7. Normalize cost/performance/headroom scores.         (_normalize, below)
 8. Apply workload objective weights.        (_normalize, below)
 9. Apply confidence requirements.           (_apply_confidence_gate, below)
10. Rank candidates.                         (below)
11. Return recommendation plus detailed reasoning.      (Recommendation)

Hard constraints (steps 3 and 6) reject a candidate outright — they are never
folded into the weighted score in steps 7-8. A candidate that fails either
one cannot be recommended no matter how its weighted score would otherwise
come out; objective weights only ever choose among candidates that already
cleared both hard gates.

This is the ONLY function that produces a Recommendation. Every route that
needs one — /analyze, the estate insight panel, and both simulation types —
calls it, so the dashboard, the analyzer, and "what if" simulations can never
diverge into separate scoring logic.

When no single target can satisfy the SLO and the confidence requirement
alone (checked in steps 6 and 9 for every candidate), the pipeline falls back
to a greedy split across whatever's left that still clears the confidence
bar — an addition beyond the 11-step spec, kept because a workload that
overflows a single target still needs an answer, not a shrug. It never
substitutes for a hard-constraint check; it only engages after every solo
candidate has already been rejected on capacity/budget. If the confidence
requirement itself is what's blocking every candidate — SLO-compliant, but
none trustworthy enough — the split is not attempted either; withholding a
recommendation is more honest than blending unconfident options together.
"""
from __future__ import annotations

import math
from typing import Optional

from app.data.loader import get_performance_profile, load_compute_targets
from app.engine.feasibility import evaluate_feasibility
from app.engine.scoring import score_candidate
from app.models import (
    CandidateEvaluation,
    Evidence,
    NormalizedScores,
    ObjectiveWeights,
    Recommendation,
    ScenarioParams,
    SplitAllocation,
    UnmitigatedProjection,
    Workload,
)


def _build_unmitigated_projection(
    workload: Workload, prior: Optional[Recommendation], effective_min_throughput: float
) -> Optional[UnmitigatedProjection]:
    if prior is None or prior.recommended_target_id is None or prior.recommended is None:
        return None

    target_id = prior.recommended_target_id
    profile = get_performance_profile(workload.id, target_id)
    if profile is None:
        return None

    target = next((t for t in load_compute_targets() if t.id == target_id), None)
    if target is None:
        return None

    replica_count = prior.recommended.replica_count
    throughput_per_replica = profile.throughput_tokens_per_s_per_replica.value
    available = replica_count * throughput_per_replica
    ratio = effective_min_throughput / available if available > 0 else float("inf")

    base_p99 = profile.p99_latency_ms_per_replica.value
    if ratio <= 1:
        predicted_p99 = base_p99
    else:
        predicted_p99 = base_p99 * (ratio ** 3)

    violated = ratio > 1 or predicted_p99 > workload.slo.p99_latency_ms

    narrative = (
        f"Holding the prior {replica_count}x {target.model} placement (sized for "
        f"{available:.0f} tok/s) against {effective_min_throughput:.0f} tok/s of demand "
        f"({ratio:.1f}x over its sized capacity) is projected to push P99 latency to "
        f"~{predicted_p99:.0f}ms — a breach of the {workload.slo.p99_latency_ms:.0f}ms SLO."
        if violated
        else f"The prior {replica_count}x {target.model} placement still covers "
        f"{effective_min_throughput:.0f} tok/s of demand without a projected SLO breach."
    )

    return UnmitigatedProjection(
        target_id=target_id,
        target_label=target.model,
        replica_count=replica_count,
        required_throughput_tokens_per_s=effective_min_throughput,
        available_throughput_tokens_per_s=available,
        utilization_ratio=round(ratio, 2),
        predicted_p99_latency_ms=round(predicted_p99, 0),
        slo_violated=violated,
        narrative=narrative,
    )


def _normalize_and_weight(
    qualifying: list[CandidateEvaluation],
    workload: Workload,
    capacity_overrides: dict[str, int],
) -> None:
    """Steps 7-8. Min-max normalize cost (lower better), performance — P99
    latency (lower better) — and headroom — spare capacity left behind
    (higher better) — across the qualifying candidate set, then blend them
    with the workload's (normalized) objective weights. Mutates each
    candidate in place."""
    if not qualifying:
        return

    targets_by_id = {t.id: t for t in load_compute_targets()}
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


def _greedy_split(
    workload: Workload,
    candidates: list[CandidateEvaluation],
    required_throughput: float,
    capacity_overrides: dict[str, int],
    effective_min_confidence: float,
) -> tuple[list[SplitAllocation], float]:
    # A split is still bound by the confidence gate: contributing a slice of
    # traffic to a target doesn't need it to clear the SLO alone, but it must
    # still clear the confidence requirement — splitting across candidates
    # nobody trusts enough isn't a fix, it's the same problem spread thinner.
    feasible = sorted(
        (
            c
            for c in candidates
            if c.feasible and c.score is not None and (c.confidence_pct or 0) >= effective_min_confidence
        ),
        key=lambda c: c.score,  # type: ignore[arg-type,return-value]
    )
    targets_by_id = {t.id: t for t in load_compute_targets()}

    remaining_required = required_throughput
    remaining_budget = workload.policy.budget_ceiling_per_hr
    allocations: list[SplitAllocation] = []

    for candidate in feasible:
        if remaining_required <= 0:
            break
        target = targets_by_id[candidate.target_id]
        profile = get_performance_profile(workload.id, candidate.target_id)
        if profile is None or target is None:
            continue
        price = target.price_per_hr_per_unit.value
        throughput_per_replica = profile.throughput_tokens_per_s_per_replica.value

        ideal_for_remaining = max(math.ceil(remaining_required / throughput_per_replica), 1)
        capacity_cap = capacity_overrides.get(target.id, target.free_capacity_units)
        budget_cap = math.floor(remaining_budget / price) if price > 0 else ideal_for_remaining
        replicas = max(min(ideal_for_remaining, capacity_cap, budget_cap), 0)
        if replicas <= 0:
            continue

        throughput_added = replicas * throughput_per_replica
        cost_added = replicas * price
        remaining_required -= throughput_added
        remaining_budget -= cost_added

        allocations.append(
            SplitAllocation(
                target_id=target.id,
                target_label=target.model,
                replica_count=replicas,
                throughput_tokens_per_s=throughput_added,
                throughput_share_pct=0.0,
                cost_per_hr=round(cost_added, 2),
                p99_latency_ms=profile.p99_latency_ms_per_replica.value,
            )
        )

    total_throughput = sum(a.throughput_tokens_per_s for a in allocations)
    if total_throughput > 0:
        for a in allocations:
            a.throughput_share_pct = round(100 * a.throughput_tokens_per_s / total_throughput, 1)

    shortfall = max(required_throughput - total_throughput, 0.0)
    return allocations, shortfall


def run_decision(
    workload: Workload,
    *,
    record_id: str,
    scenario: ScenarioParams,
    effective_min_throughput: float,
    prior: Optional[Recommendation] = None,
    capacity_overrides: Optional[dict[str, int]] = None,
    objective_weights: Optional[ObjectiveWeights] = None,
    min_confidence_pct: Optional[float] = None,
) -> Recommendation:
    capacity_overrides = capacity_overrides or {}
    effective_weights = objective_weights or workload.objective_weights
    effective_min_confidence = (
        min_confidence_pct if min_confidence_pct is not None else workload.min_confidence_pct
    )
    # Steps 7-9 read the workload's own settings unless a caller overrides
    # them for this run — the workload object itself is never mutated, so a
    # test can vary either independently without touching the fixture.
    scoring_workload = workload.model_copy(update={"objective_weights": effective_weights})

    targets = load_compute_targets()
    candidates: list[CandidateEvaluation] = []

    # Steps 3-6, per target.
    for target in targets:
        checks = evaluate_feasibility(workload, target)
        profile = get_performance_profile(workload.id, target.id)
        free_capacity = capacity_overrides.get(target.id, target.free_capacity_units)
        candidate = score_candidate(
            workload=scoring_workload,
            target=target,
            profile=profile,
            checks=checks,
            required_throughput=effective_min_throughput,
            free_capacity_units=free_capacity,
        )
        candidates.append(candidate)

    # Step 9: apply the confidence requirement to every feasible, SLO-compliant candidate.
    slo_compliant = [c for c in candidates if c.feasible and c.predicted and c.predicted.meets_slo]
    for c in slo_compliant:
        c.meets_confidence_requirement = (c.confidence_pct or 0) >= effective_min_confidence

    qualifying = [c for c in slo_compliant if c.meets_confidence_requirement]

    # Steps 7-8: normalize and weight only the candidates that cleared both hard gates.
    _normalize_and_weight(qualifying, scoring_workload, capacity_overrides)

    # Step 10: rank by weighted score, highest first.
    qualifying.sort(key=lambda c: c.weighted_score or 0.0, reverse=True)
    for rank, c in enumerate(qualifying, start=1):
        c.rank = rank

    split_allocation: list[SplitAllocation] = []
    shortfall = 0.0
    recommended_target_id: Optional[str] = None
    recommended = None
    achieved = 0.0

    if qualifying:
        best = qualifying[0]
        recommended_target_id = best.target_id
        recommended = best.predicted
        achieved = best.predicted.throughput_tokens_per_s_total  # type: ignore[union-attr]

        qualifying_ids = {c.target_id for c in qualifying}
        slo_compliant_ids = {c.target_id for c in slo_compliant}
        for c in candidates:
            if c.target_id == best.target_id:
                continue
            if c.target_id in qualifying_ids:
                c.why_not_chosen = (
                    f"Meets the SLO and the {effective_min_confidence:.0f}% confidence "
                    f"requirement, but scores lower under the current objective weights "
                    f"({c.weighted_score:.2f} vs {best.weighted_score:.2f})."
                )
            elif c.target_id in slo_compliant_ids:
                c.why_not_chosen = (
                    f"Meets the SLO, but {c.confidence_pct:.0f}% confidence is below the "
                    f"{effective_min_confidence:.0f}% requirement for this workload."
                )
            elif c.feasible:
                c.why_not_chosen = "; ".join(c.slo_violations) or c.capacity_note
    else:
        split_allocation, shortfall = _greedy_split(
            scoring_workload, candidates, effective_min_throughput, capacity_overrides, effective_min_confidence
        )
        achieved = effective_min_throughput - shortfall
        for c in candidates:
            if c.feasible:
                alloc = next((a for a in split_allocation if a.target_id == c.target_id), None)
                if alloc:
                    c.why_not_chosen = (
                        f"Contributing {alloc.replica_count} replica(s) "
                        f"({alloc.throughput_share_pct:.0f}% of split traffic) — no single target "
                        f"cleared the SLO and confidence requirement alone."
                    )
                elif c.meets_confidence_requirement is False:
                    c.why_not_chosen = (
                        f"Meets the SLO, but {c.confidence_pct:.0f}% confidence is below the "
                        f"{effective_min_confidence:.0f}% requirement for this workload."
                    )
                elif c.slo_violations:
                    c.why_not_chosen = "; ".join(c.slo_violations)
                else:
                    c.why_not_chosen = c.capacity_note or "Not needed to cover required throughput."

    # Every candidate gets one explicit, machine-readable status: RECOMMENDED
    # (chosen solo or part of a split), FEASIBLE (cleared every gate but
    # wasn't picked — a legitimate alternative, not a failure), or REJECTED
    # (failed a hard compatibility check, the SLO, or the confidence
    # requirement — always with reasons attached via rejection_reasons /
    # slo_violations / why_not_chosen).
    recommended_ids = {recommended_target_id} if recommended_target_id else {
        a.target_id for a in split_allocation
    }
    for c in candidates:
        if c.target_id in recommended_ids:
            c.status = "recommended"
        elif c.feasible and not c.slo_violations and c.meets_confidence_requirement is not False:
            c.status = "feasible"
        else:
            c.status = "rejected"

    # A confidence problem is not a capacity problem: if every SLO-compliant
    # candidate exists but none clears the confidence bar, splitting across
    # them doesn't help — the honest answer is to withhold a recommendation,
    # not silently blend unconfident options together.
    confidence_blocked = not qualifying and not split_allocation and bool(slo_compliant)

    slo_met = (not split_allocation and bool(recommended and recommended.meets_slo)) or (
        bool(split_allocation) and shortfall <= 0
    )

    evidence: list[Evidence] = []
    targets_by_id = {t.id: t for t in targets}
    if recommended_target_id:
        best_candidate = qualifying[0]
        t = targets_by_id[recommended_target_id]
        evidence.append(
            Evidence(
                label=f"{t.model} — on-demand price",
                display_value=f"${t.price_per_hr_per_unit.value:.2f}/hr per unit",
                metric=t.price_per_hr_per_unit,
                source=t.price_per_hr_per_unit.source,
            )
        )
        if best_candidate.raw_prediction:
            pred = best_candidate.raw_prediction
            evidence.append(
                Evidence(
                    label=f"{t.model} — throughput, this workload",
                    display_value=f"{pred.throughput_tokens_per_s.value:.0f} tok/s per replica",
                    metric=pred.throughput_tokens_per_s,
                    source=pred.throughput_tokens_per_s.source,
                )
            )
            evidence.append(
                Evidence(
                    label=f"{t.model} — P99 latency, this workload",
                    display_value=f"{pred.latency_p99_ms.value:.0f} ms per replica",
                    metric=pred.latency_p99_ms,
                    source=pred.latency_p99_ms.source,
                )
            )
    for alloc in split_allocation:
        t = targets_by_id[alloc.target_id]
        candidate = next(c for c in candidates if c.target_id == alloc.target_id)
        evidence.append(
            Evidence(
                label=f"{t.model} — on-demand price",
                display_value=f"${t.price_per_hr_per_unit.value:.2f}/hr per unit",
                metric=t.price_per_hr_per_unit,
                source=t.price_per_hr_per_unit.source,
            )
        )
        if candidate.raw_prediction:
            pred = candidate.raw_prediction
            evidence.append(
                Evidence(
                    label=f"{t.model} — throughput, this workload",
                    display_value=f"{pred.throughput_tokens_per_s.value:.0f} tok/s per replica",
                    metric=pred.throughput_tokens_per_s,
                    source=pred.throughput_tokens_per_s.source,
                )
            )

    if recommended:
        confidence = int(round(qualifying[0].confidence_pct or 0))
    elif split_allocation:
        total_share = sum(a.throughput_share_pct for a in split_allocation) or 1.0
        blended = 0.0
        for alloc in split_allocation:
            candidate = next(c for c in candidates if c.target_id == alloc.target_id)
            blended += (candidate.confidence_pct or 0) * (alloc.throughput_share_pct / total_share)
        penalty = 15.0 if shortfall > 0 else 0.0
        confidence = int(round(max(blended - penalty, 0)))
    else:
        confidence = 0

    unmitigated = None
    if scenario.type.value == "demand_spike":
        unmitigated = _build_unmitigated_projection(workload, prior, effective_min_throughput)

    if recommended and recommended_target_id:
        t = targets_by_id[recommended_target_id]
        current = workload.current_placement
        current_cost = current.cost_per_hr
        savings_pct = (
            100 * (current_cost - recommended.cost_per_hr) / current_cost if current_cost > 0 else 0
        )
        weights = scoring_workload.objective_weights.normalized()
        weight_note = (
            f"(objective weights: cost {weights.cost:.0%} · performance {weights.performance:.0%} · "
            f"headroom {weights.headroom:.0%}; confidence requirement {effective_min_confidence:.0f}%)"
        )
        if recommended_target_id == current.target_id:
            reasoning = (
                f"{t.model} remains the top-ranked target: {recommended.replica_count}x "
                f"replicas at ${recommended.cost_per_hr:.2f}/hr hold the "
                f"{workload.slo.p99_latency_ms:.0f}ms P99 SLO {weight_note}."
            )
        elif savings_pct > 0:
            reasoning = (
                f"{t.model} meets the {workload.slo.p99_latency_ms:.0f}ms P99 / "
                f"{effective_min_throughput:.0f} tok/s SLO at ${recommended.cost_per_hr:.2f}/hr — "
                f"{savings_pct:.1f}% less than the current {current.target_id} placement "
                f"(${current_cost:.2f}/hr), with {confidence}% confidence {weight_note}."
            )
        else:
            reasoning = (
                f"{t.model} is the top-ranked target meeting the "
                f"{workload.slo.p99_latency_ms:.0f}ms P99 SLO at ${recommended.cost_per_hr:.2f}/hr "
                f"{weight_note}."
            )
    elif split_allocation and shortfall <= 0:
        parts = " / ".join(
            f"{a.throughput_share_pct:.0f}% {a.target_label}" for a in split_allocation
        )
        total_cost = sum(a.cost_per_hr for a in split_allocation)
        reasoning = (
            f"No single target clears both the SLO and the {effective_min_confidence:.0f}% "
            f"confidence requirement alone at this volume. Splitting traffic {parts} restores "
            f"compliance at ${total_cost:.2f}/hr combined."
        )
    elif split_allocation:
        pct = 100 * achieved / effective_min_throughput if effective_min_throughput else 0
        reasoning = (
            f"Even combining every feasible target's free capacity within policy, the estate can "
            f"supply {achieved:.0f} of {effective_min_throughput:.0f} tok/s required ({pct:.0f}%). "
            f"Additional capacity is needed to fully hold the SLO at this volume."
        )
    elif confidence_blocked:
        names = ", ".join(c.target_label for c in slo_compliant)
        best_conf = max((c.confidence_pct or 0) for c in slo_compliant)
        reasoning = (
            f"{names} would satisfy the {workload.slo.p99_latency_ms:.0f}ms P99 / "
            f"{effective_min_throughput:.0f} tok/s SLO, but no candidate reaches the "
            f"{effective_min_confidence:.0f}% confidence requirement for this workload "
            f"(highest available: {best_conf:.0f}%). Recommendation withheld rather than "
            f"presenting a placement below the required confidence bar."
        )
    else:
        reasoning = "No feasible target was found for this workload under current policy."

    return Recommendation(
        id=record_id,
        workload_id=workload.id,
        workload_name=workload.name,
        scenario=scenario,
        derived_from_id=prior.id if prior else None,
        slo=workload.slo,
        current_placement=workload.current_placement,
        effective_min_throughput_tokens_per_s=effective_min_throughput,
        objective_weights=effective_weights,
        min_confidence_pct=effective_min_confidence,
        candidates=candidates,
        recommended_target_id=recommended_target_id,
        recommended=recommended,
        split_allocation=split_allocation,
        achieved_throughput_tokens_per_s=round(achieved, 0),
        shortfall_tokens_per_s=round(shortfall, 0),
        slo_met=slo_met,
        confidence_pct=confidence,
        evidence=evidence,
        unmitigated_projection=unmitigated,
        reasoning=reasoning,
    )
