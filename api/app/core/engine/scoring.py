"""Retrieves the prediction for a feasible target (step 5), checks it against
the workload's SLO at the scale the workload actually needs (step 6), and
sizes the placement.

The raw Prediction (per replica, straight from the performance-profile
evidence + the target's priced Metric) is kept separate from the *sized*
outcome (how many replicas this scenario needs, and whether that sizing
holds the SLO) — retrieval and scale are different concerns. Normalizing
across candidates and applying objective weights happens one level up, in
app.core.engine.ranking, because those steps need the whole candidate set,
not just one target.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.core.schemas import (
    CandidateEvaluation,
    ComputeTarget,
    FeasibilityCheck,
    PerformanceProfile,
    PredictedOutcome,
    Prediction,
    Workload,
)


@dataclass
class SizingResult:
    ideal_replicas: int
    capacity_cap: int
    budget_cap: int
    actual_replicas: int
    binding_constraint: str | None  # "capacity" | "budget" | "capacity+budget" | None


def size_replicas(
    *,
    required_throughput: float,
    throughput_per_replica: float,
    free_capacity_units: int,
    budget_ceiling_per_hr: float,
    price_per_unit: float,
) -> SizingResult:
    ideal = max(math.ceil(required_throughput / throughput_per_replica), 1)
    capacity_cap = max(free_capacity_units, 0)
    budget_cap = (
        math.floor(budget_ceiling_per_hr / price_per_unit) if price_per_unit > 0 else ideal
    )
    actual = max(min(ideal, capacity_cap, budget_cap), 0)

    binding: str | None = None
    if actual < ideal:
        capacity_bound = capacity_cap <= budget_cap
        budget_bound = budget_cap <= capacity_cap
        if capacity_bound and budget_bound:
            binding = "capacity+budget"
        elif capacity_bound:
            binding = "capacity"
        else:
            binding = "budget"

    return SizingResult(
        ideal_replicas=ideal,
        capacity_cap=capacity_cap,
        budget_cap=budget_cap,
        actual_replicas=actual,
        binding_constraint=binding,
    )


def retrieve_prediction(
    workload: Workload, target: ComputeTarget, profile: PerformanceProfile
) -> Prediction:
    """Step 5: retrieve the prediction for this (workload, target) pair.
    Latency and throughput come straight from the performance-profile
    evidence; cost is the target's own priced Metric — nothing here is
    computed, only looked up."""
    return Prediction(
        target_id=target.id,
        workload_id=workload.id,
        latency_p99_ms=profile.p99_latency_ms_per_replica,
        throughput_tokens_per_s=profile.throughput_tokens_per_s_per_replica,
        cost_per_hr=target.price_per_hr_per_unit,
    )


def score_candidate(
    *,
    workload: Workload,
    target: ComputeTarget,
    profile: PerformanceProfile | None,
    checks: list[FeasibilityCheck],
    required_throughput: float,
    free_capacity_units: int,
) -> CandidateEvaluation:
    hard_feasible = all(c.passed for c in checks)
    label = f"{target.model}"
    failing = [c.detail for c in checks if not c.passed]

    if not hard_feasible:
        return CandidateEvaluation(
            target_id=target.id,
            target_label=label,
            vendor=target.vendor,
            feasible=False,
            checks=checks,
            rejection_reason=failing[0],
            rejection_reasons=failing,
        )

    if profile is None:
        reason = (
            "No performance evidence on file for this workload on this target — "
            "refusing to score from an unmeasured, unmodeled assumption."
        )
        return CandidateEvaluation(
            target_id=target.id,
            target_label=label,
            vendor=target.vendor,
            feasible=False,
            checks=checks,
            rejection_reason=reason,
            rejection_reasons=[reason],
        )

    # Step 5: retrieve the prediction.
    prediction = retrieve_prediction(workload, target, profile)
    throughput_per_replica = prediction.throughput_tokens_per_s.value
    p99 = prediction.latency_p99_ms.value
    price_per_unit = prediction.cost_per_hr.value

    sizing = size_replicas(
        required_throughput=required_throughput,
        throughput_per_replica=throughput_per_replica,
        free_capacity_units=free_capacity_units,
        budget_ceiling_per_hr=workload.policy.budget_ceiling_per_hr,
        price_per_unit=price_per_unit,
    )

    # Step 6: check SLO constraints. A hard constraint — reject, never weight.
    slo_violations: list[str] = []
    if p99 > workload.slo.p99_latency_ms:
        slo_violations.append(
            f"Predicted P99 latency {p99:.0f}ms exceeds the {workload.slo.p99_latency_ms:.0f}ms SLO."
        )
    if sizing.actual_replicas < sizing.ideal_replicas:
        achievable = sizing.actual_replicas * throughput_per_replica
        if sizing.binding_constraint == "budget":
            slo_violations.append(
                f"Cannot reach the required {required_throughput:.0f} tok/s minimum throughput "
                f"within the ${workload.policy.budget_ceiling_per_hr:.2f}/hr budget ceiling "
                f"(max {achievable:.0f} tok/s achievable)."
            )
        else:
            slo_violations.append(
                f"Cannot reach the required {required_throughput:.0f} tok/s minimum throughput "
                f"within available capacity (max {achievable:.0f} tok/s achievable)."
            )

    throughput_total = sizing.actual_replicas * throughput_per_replica
    cost_total = sizing.actual_replicas * price_per_unit
    meets_slo = len(slo_violations) == 0

    predicted = PredictedOutcome(
        replica_count=sizing.actual_replicas,
        throughput_tokens_per_s_total=throughput_total,
        p99_latency_ms=p99,
        cost_per_hr=round(cost_total, 2),
        meets_slo=meets_slo,
        provenance=prediction.throughput_tokens_per_s.provenance,
    )

    capacity_constrained = sizing.binding_constraint is not None
    capacity_note = None
    if sizing.binding_constraint == "capacity":
        capacity_note = (
            f"Needs {sizing.ideal_replicas} replicas to fully cover required throughput; only "
            f"{sizing.capacity_cap} free capacity slice(s) available on {target.model}."
        )
    elif sizing.binding_constraint == "budget":
        capacity_note = (
            f"Needs {sizing.ideal_replicas} replicas to fully cover required throughput; the "
            f"${workload.policy.budget_ceiling_per_hr:.2f}/hr budget ceiling caps this target at "
            f"{sizing.budget_cap} replica(s)."
        )
    elif sizing.binding_constraint == "capacity+budget":
        capacity_note = (
            f"Needs {sizing.ideal_replicas} replicas to fully cover required throughput; both free "
            f"capacity ({sizing.capacity_cap}) and the budget ceiling ({sizing.budget_cap}) cap this "
            f"target below that."
        )

    score = price_per_unit / throughput_per_replica

    return CandidateEvaluation(
        target_id=target.id,
        target_label=label,
        vendor=target.vendor,
        feasible=True,
        checks=checks,
        raw_prediction=prediction,
        slo_violations=slo_violations,
        predicted=predicted,
        capacity_constrained=capacity_constrained,
        capacity_note=capacity_note,
        score=round(score, 6),
        confidence_pct=prediction.confidence_pct,
    )
