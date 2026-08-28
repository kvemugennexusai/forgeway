"""The six named scenario presets.

A scenario is a pure function of the workload's own canonical baseline — it
never reads or depends on whatever recommendation a user happens to be
looking at, and it never mutates a fixture. That means the same scenario
name always produces the same result for a given workload (deterministic,
reproducible, safe to call from anywhere), which is what "temporary changes,
not persistent state" means in practice: every call starts from the real
baseline and derives a hypothetical overlay on top of it, then discards it.

Each scenario returns the *inputs* run_decision() needs (effective required
throughput, objective weights, confidence threshold, capacity overrides) —
it never computes a recommendation itself. run_scenario(), below, is what
actually calls run_decision() twice (once for BEFORE, once for AFTER) and
builds the comparison the frontend renders.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.data.loader import get_compute_target
from app.engine.decision import run_decision
from app.models import (
    CandidateEvaluation,
    ObjectiveWeights,
    Recommendation,
    ScenarioComparison,
    ScenarioEventInfo,
    ScenarioParams,
    ScenarioType,
    Workload,
)

H100_TARGET_ID = "nvidia-h100-dc"
DEMAND_SPIKE_MULTIPLIER = 3.5  # 20 -> 70 requests/sec for the flagship workload
H100_CAPACITY_LOSS_PCT = 0.5
COST_PRIORITY_WEIGHT = 0.7
PERFORMANCE_PRIORITY_WEIGHT = 0.7
STRICT_CONFIDENCE_PCT = 95.0

CATALOG: list[ScenarioEventInfo] = [
    ScenarioEventInfo(
        name=ScenarioType.normal,
        label="Normal",
        description="The workload's baseline — no scenario applied.",
    ),
    ScenarioEventInfo(
        name=ScenarioType.demand_spike,
        label="Demand Spike",
        description="Demand rises from 20 to 70 requests/sec (3.5x).",
    ),
    ScenarioEventInfo(
        name=ScenarioType.h100_capacity_loss,
        label="H100 Capacity Loss",
        description="Available H100 capacity drops by 50%.",
    ),
    ScenarioEventInfo(
        name=ScenarioType.cost_priority,
        label="Cost Priority",
        description=f"Objective cost weight raised to {COST_PRIORITY_WEIGHT:.0%}.",
    ),
    ScenarioEventInfo(
        name=ScenarioType.performance_priority,
        label="Performance Priority",
        description=f"Objective performance weight raised to {PERFORMANCE_PRIORITY_WEIGHT:.0%}.",
    ),
    ScenarioEventInfo(
        name=ScenarioType.strict_confidence_policy,
        label="Strict Confidence Policy",
        description=f"Minimum recommendation confidence raised to {STRICT_CONFIDENCE_PCT:.0f}%.",
    ),
]

_CATALOG_BY_NAME = {entry.name: entry for entry in CATALOG}


@dataclass
class ScenarioApplication:
    scenario: ScenarioParams
    effective_min_throughput: float
    objective_weights: ObjectiveWeights
    min_confidence_pct: float
    capacity_overrides: dict[str, int] = field(default_factory=dict)


def _redistribute(base: ObjectiveWeights, axis: str, target: float) -> ObjectiveWeights:
    """Set one axis to `target` and redistribute the remainder proportionally
    across the other two, preserving their relative priority rather than
    zeroing them out."""
    values = {"cost": base.cost, "performance": base.performance, "headroom": base.headroom}
    others = {k: v for k, v in values.items() if k != axis}
    other_sum = sum(others.values())
    remainder = max(1 - target, 0.0)
    if other_sum <= 0:
        share = remainder / len(others)
        redistributed = {k: share for k in others}
    else:
        redistributed = {k: remainder * (v / other_sum) for k, v in others.items()}
    redistributed[axis] = target
    return ObjectiveWeights(**redistributed)


def apply_scenario(workload: Workload, name: ScenarioType) -> ScenarioApplication:
    base_throughput = workload.slo.min_throughput_tokens_per_s
    base_weights = workload.objective_weights
    base_confidence = workload.min_confidence_pct

    if name == ScenarioType.normal:
        return ScenarioApplication(
            scenario=ScenarioParams(type=name, label="Normal — baseline, no scenario applied"),
            effective_min_throughput=base_throughput,
            objective_weights=base_weights,
            min_confidence_pct=base_confidence,
        )

    if name == ScenarioType.demand_spike:
        new_throughput = base_throughput * DEMAND_SPIKE_MULTIPLIER
        if workload.tokens_per_request:
            before_rps = base_throughput / workload.tokens_per_request
            after_rps = new_throughput / workload.tokens_per_request
            label = (
                f"Demand spike: {before_rps:.0f} → {after_rps:.0f} requests/sec "
                f"({DEMAND_SPIKE_MULTIPLIER:g}x)"
            )
        else:
            label = (
                f"Demand spike: {base_throughput:.0f} → {new_throughput:.0f} tok/s "
                f"({DEMAND_SPIKE_MULTIPLIER:g}x)"
            )
        return ScenarioApplication(
            scenario=ScenarioParams(type=name, demand_multiplier=DEMAND_SPIKE_MULTIPLIER, label=label),
            effective_min_throughput=new_throughput,
            objective_weights=base_weights,
            min_confidence_pct=base_confidence,
        )

    if name == ScenarioType.h100_capacity_loss:
        target = get_compute_target(H100_TARGET_ID)
        overrides: dict[str, int] = {}
        if target is not None:
            reduced = max(int(target.free_capacity_units * (1 - H100_CAPACITY_LOSS_PCT)), 0)
            overrides[H100_TARGET_ID] = reduced
            label = (
                f"H100 capacity reduced {H100_CAPACITY_LOSS_PCT:.0%}: "
                f"{target.free_capacity_units} → {reduced} free unit(s)"
            )
        else:
            label = f"H100 capacity reduced by {H100_CAPACITY_LOSS_PCT:.0%}"
        return ScenarioApplication(
            scenario=ScenarioParams(
                type=name,
                capacity_loss_target_id=H100_TARGET_ID,
                capacity_loss_pct=H100_CAPACITY_LOSS_PCT,
                label=label,
            ),
            effective_min_throughput=base_throughput,
            objective_weights=base_weights,
            min_confidence_pct=base_confidence,
            capacity_overrides=overrides,
        )

    if name == ScenarioType.cost_priority:
        weights = _redistribute(base_weights, "cost", COST_PRIORITY_WEIGHT)
        label = f"Cost priority: cost weight {base_weights.cost:.0%} → {weights.cost:.0%}"
        return ScenarioApplication(
            scenario=ScenarioParams(type=name, label=label),
            effective_min_throughput=base_throughput,
            objective_weights=weights,
            min_confidence_pct=base_confidence,
        )

    if name == ScenarioType.performance_priority:
        weights = _redistribute(base_weights, "performance", PERFORMANCE_PRIORITY_WEIGHT)
        label = (
            f"Performance priority: performance weight {base_weights.performance:.0%} "
            f"→ {weights.performance:.0%}"
        )
        return ScenarioApplication(
            scenario=ScenarioParams(type=name, label=label),
            effective_min_throughput=base_throughput,
            objective_weights=weights,
            min_confidence_pct=base_confidence,
        )

    if name == ScenarioType.strict_confidence_policy:
        label = (
            f"Strict confidence policy: minimum confidence {base_confidence:.0f}% "
            f"→ {STRICT_CONFIDENCE_PCT:.0f}%"
        )
        return ScenarioApplication(
            scenario=ScenarioParams(type=name, label=label),
            effective_min_throughput=base_throughput,
            objective_weights=base_weights,
            min_confidence_pct=STRICT_CONFIDENCE_PCT,
        )

    raise ValueError(f"Unknown scenario '{name}'")


def _candidate(rec: Recommendation, target_id: str) -> CandidateEvaluation | None:
    return next((c for c in rec.candidates if c.target_id == target_id), None)


def _build_change_explanation(before: Recommendation, after: Recommendation) -> str:
    before_id = before.recommended_target_id
    after_id = after.recommended_target_id

    if before_id and after_id and before_id == after_id and not after.split_allocation:
        before_score = _candidate(before, before_id)
        after_score = _candidate(after, after_id)
        score_note = ""
        if (
            before_score
            and after_score
            and before_score.weighted_score is not None
            and after_score.weighted_score is not None
            and abs(before_score.weighted_score - after_score.weighted_score) > 1e-6
        ):
            score_note = (
                f" Its margin moved with the scenario — weighted score "
                f"{before_score.weighted_score:.2f} → {after_score.weighted_score:.2f} — "
                f"but it was still the strongest choice under the new priorities."
            )
        return (
            f"No change: {after.recommended_target_id} remains the top-ranked recommendation "
            f"({before.confidence_pct}% → {after.confidence_pct}% confidence, "
            f"${before.recommended.cost_per_hr:.2f}/hr → ${after.recommended.cost_per_hr:.2f}/hr)."  # type: ignore[union-attr]
            f"{score_note}"
        )

    if before_id and after_id and before_id != after_id:
        prior_under_new = _candidate(after, before_id)
        reason = None
        if prior_under_new is not None:
            if prior_under_new.slo_violations:
                reason = "; ".join(prior_under_new.slo_violations)
            elif prior_under_new.meets_confidence_requirement is False:
                reason = (
                    f"its {prior_under_new.confidence_pct:.0f}% confidence fell below the new "
                    f"{after.min_confidence_pct:.0f}% requirement"
                )
            elif prior_under_new.why_not_chosen:
                reason = prior_under_new.why_not_chosen
        if reason:
            return f"Changed from {before_id} to {after_id}, because {reason}."
        return f"Changed from {before_id} to {after_id} under the new scenario."

    if before_id and not after_id and after.split_allocation:
        parts = ", ".join(a.target_label for a in after.split_allocation)
        return (
            f"{before_id} alone can no longer satisfy the SLO and confidence requirement under "
            f"this scenario — traffic now splits across {parts}."
        )

    if before_id and not after_id and not after.split_allocation:
        prior_under_new = _candidate(after, before_id)
        if prior_under_new and prior_under_new.meets_confidence_requirement is False:
            return (
                f"No recommendation remains under this scenario: {before_id} would still meet "
                f"the SLO, but no candidate reaches the {after.min_confidence_pct:.0f}% "
                f"confidence requirement (highest available: "
                f"{prior_under_new.confidence_pct:.0f}%)."
            )
        return f"No feasible recommendation remains under this scenario (previously {before_id})."

    if not before_id and after_id:
        return f"A recommendation is now possible under this scenario: {after_id}."

    if before.split_allocation and after.split_allocation and {a.target_id for a in before.split_allocation} == {
        a.target_id for a in after.split_allocation
    }:
        return "No change: the same split placement still holds under this scenario."

    return "The recommendation changed under this scenario."


def run_scenario(
    workload: Workload,
    name: ScenarioType,
    *,
    before_id: str,
    after_id: str,
) -> ScenarioComparison:
    before = run_decision(
        workload,
        record_id=before_id,
        scenario=ScenarioParams(type=ScenarioType.normal, label="Normal — baseline, no scenario applied"),
        effective_min_throughput=workload.slo.min_throughput_tokens_per_s,
    )

    application = apply_scenario(workload, name)
    after = run_decision(
        workload,
        record_id=after_id,
        scenario=application.scenario,
        effective_min_throughput=application.effective_min_throughput,
        objective_weights=application.objective_weights,
        min_confidence_pct=application.min_confidence_pct,
        capacity_overrides=application.capacity_overrides,
        prior=before,
    )

    event = _CATALOG_BY_NAME[name]

    return ScenarioComparison(
        workload_id=workload.id,
        event=ScenarioEventInfo(name=name, label=application.scenario.label, description=event.description),
        before=before,
        after=after,
        change_explanation=_build_change_explanation(before, after),
    )
