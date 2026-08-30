"""PlacementDecision (forgeway/v0.1) — a vendor-neutral summary of one
placement decision: what was evaluated, what qualified, what was rejected
and why, what's recommended, and how much better that is than today.

This formalizes a concept the demo already produces, spread across
`CandidateEvaluation` (per-target result — already a core schema) and the
product-level `Recommendation` (in app.models — which also carries this
demo's own scenario metadata, split-allocation, and narrative reasoning,
none of which are vendor-neutral concepts). PlacementDecision.from_candidates()
builds the vendor-neutral summary directly from a workload and its list of
CandidateEvaluations — the same inputs/outputs app.core.engine already
works with — with no dependency on app.models.Recommendation or any other
product-layer type.

Known v0.1 limitation: a *split* placement across multiple targets (the
demo's greedy-split fallback — see app/engine/decision.py) has no
representation here yet; `recommended_target_id` is only set when a single
target was ranked #1 outright. See docs/schemas.md.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.core.schemas.engine import CandidateEvaluation
from app.core.schemas.workload import SLO, CurrentPlacement, Workload

SCHEMA_VERSION = "forgeway/v0.1"


class RejectedTarget(BaseModel):
    target_id: str
    target_label: str
    reasons: list[str]


class ScoreBreakdown(BaseModel):
    cost: float
    performance: float
    headroom: float
    weighted_score: float


class ImprovementVsCurrentPlacement(BaseModel):
    current_target_id: str
    current_cost_per_hr: float
    recommended_cost_per_hr: float
    cost_savings_pct: Optional[float] = None
    slo_met: bool


class EvidenceReference(BaseModel):
    label: str
    source: str


class PlacementDecision(BaseModel):
    schema_version: Literal["forgeway/v0.1"] = SCHEMA_VERSION
    workload_id: str
    workload_name: str
    slo: SLO
    current_placement: CurrentPlacement
    evaluated_targets: list[str]
    feasible_targets: list[str]
    rejected_targets: list[RejectedTarget] = Field(default_factory=list)
    recommended_target_id: Optional[str] = None
    score_breakdown: dict[str, ScoreBreakdown] = Field(default_factory=dict)
    confidence: Optional[float] = None
    improvement_vs_current_placement: Optional[ImprovementVsCurrentPlacement] = None
    evidence_references: list[EvidenceReference] = Field(default_factory=list)

    @classmethod
    def from_candidates(
        cls,
        workload: Workload,
        candidates: list[CandidateEvaluation],
    ) -> "PlacementDecision":
        """Builds the vendor-neutral decision summary directly from a
        workload and its already-evaluated, already-ranked candidates.

        Precondition, matching app.core.engine.ranking.normalize_and_weight:
        candidates that qualify (feasible, SLO-compliant, and confidence-
        gated) must already have `meets_confidence_requirement` set and, if
        they qualify, `rank` assigned by the caller's confidence-gate and
        ranking steps — this function does not re-run either itself, to
        avoid a second copy of that logic living here. Both preconditions
        are checked explicitly below and raise `ValueError` if violated,
        rather than silently reporting "no recommendation" for what's
        actually "the caller skipped a step." `rank` and
        `meets_confidence_requirement` are core.schemas.engine fields;
        product-layer concepts like `status`/`why_not_chosen` are not used.
        """
        evaluated_targets = [c.target_id for c in candidates]
        feasible_targets = [c.target_id for c in candidates if c.feasible]

        slo_compliant_ids = {
            c.target_id for c in candidates if c.feasible and c.predicted and c.predicted.meets_slo
        }
        ungated = [
            c.target_id
            for c in candidates
            if c.target_id in slo_compliant_ids and c.meets_confidence_requirement is None
        ]
        if ungated:
            raise ValueError(
                "PlacementDecision.from_candidates requires the confidence gate to have "
                "already run (meets_confidence_requirement set) for every feasible, "
                f"SLO-compliant candidate; missing for target_id(s): {ungated}"
            )

        qualifies = {
            c.target_id
            for c in candidates
            if c.target_id in slo_compliant_ids and c.meets_confidence_requirement
        }
        unranked = [c.target_id for c in candidates if c.target_id in qualifies and c.rank is None]
        if unranked:
            raise ValueError(
                "PlacementDecision.from_candidates requires ranking to have already run "
                f"(rank set) for every qualifying candidate; missing for target_id(s): {unranked}"
            )

        rejected_targets = [
            RejectedTarget(
                target_id=c.target_id,
                target_label=c.target_label,
                reasons=_rejection_reasons(c, workload.min_confidence_pct),
            )
            for c in candidates
            if c.target_id not in qualifies
        ]

        recommended = next((c for c in candidates if c.rank == 1), None)

        score_breakdown = {
            c.target_id: ScoreBreakdown(
                cost=c.normalized_scores.cost,
                performance=c.normalized_scores.performance,
                headroom=c.normalized_scores.headroom,
                weighted_score=c.weighted_score,
            )
            for c in candidates
            if c.normalized_scores is not None and c.weighted_score is not None
        }

        improvement = None
        confidence = None
        evidence_references: list[EvidenceReference] = []
        if recommended is not None and recommended.predicted is not None:
            confidence = recommended.confidence_pct
            current_cost = workload.current_placement.cost_per_hr
            recommended_cost = recommended.predicted.cost_per_hr
            cost_savings_pct = (
                round(100 * (current_cost - recommended_cost) / current_cost, 1)
                if current_cost > 0
                else None
            )
            improvement = ImprovementVsCurrentPlacement(
                current_target_id=workload.current_placement.target_id,
                current_cost_per_hr=current_cost,
                recommended_cost_per_hr=recommended_cost,
                cost_savings_pct=cost_savings_pct,
                slo_met=recommended.predicted.meets_slo,
            )
            if recommended.raw_prediction is not None:
                pred = recommended.raw_prediction
                evidence_references = [
                    EvidenceReference(
                        label=f"{recommended.target_label} — on-demand price",
                        source=pred.cost_per_hr.source,
                    ),
                    EvidenceReference(
                        label=f"{recommended.target_label} — throughput, this workload",
                        source=pred.throughput_tokens_per_s.source,
                    ),
                    EvidenceReference(
                        label=f"{recommended.target_label} — P99 latency, this workload",
                        source=pred.latency_p99_ms.source,
                    ),
                ]

        return cls(
            workload_id=workload.id,
            workload_name=workload.name,
            slo=workload.slo,
            current_placement=workload.current_placement,
            evaluated_targets=evaluated_targets,
            feasible_targets=feasible_targets,
            rejected_targets=rejected_targets,
            recommended_target_id=recommended.target_id if recommended else None,
            score_breakdown=score_breakdown,
            confidence=confidence,
            improvement_vs_current_placement=improvement,
            evidence_references=evidence_references,
        )


def _rejection_reasons(candidate: CandidateEvaluation, min_confidence_pct: float) -> list[str]:
    if candidate.rejection_reasons:
        return candidate.rejection_reasons
    if candidate.slo_violations:
        return candidate.slo_violations
    if candidate.meets_confidence_requirement is False:
        return [
            f"{candidate.confidence_pct:.0f}% confidence is below the "
            f"{min_confidence_pct:.0f}% requirement for this workload."
        ]
    return []
