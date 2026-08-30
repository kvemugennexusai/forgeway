"""Decision-engine output schemas — the per-target evaluation contract the
feasibility, scoring, and ranking engines (app.core.engine) produce. Any
caller (this product's UI, a CLI, a different frontend) renders the same
CandidateEvaluation shape rather than re-deriving it."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.core.schemas.evidence import Metric, Provenance


class FeasibilityCheck(BaseModel):
    name: str
    passed: bool
    detail: str


class Prediction(BaseModel):
    """What we predict for one workload on one target, per replica —
    retrieved (not computed) from the performance-profile evidence plus the
    target's own priced Metric. This is the raw evidence a candidate is
    scored from; sizing it to the workload's required scale happens after."""

    target_id: str
    workload_id: str
    latency_p99_ms: Metric
    throughput_tokens_per_s: Metric
    cost_per_hr: Metric

    @property
    def confidence_pct(self) -> float:
        """Weakest-link confidence across the three metrics this prediction
        rests on — a recommendation is never more certain than its least
        certain input."""
        return min(self.latency_p99_ms.confidence, self.throughput_tokens_per_s.confidence, self.cost_per_hr.confidence)


class PredictedOutcome(BaseModel):
    """The sized outcome of placing this workload's full required throughput
    on this target: how many replicas, at what aggregate cost/throughput,
    and whether that sizing holds the SLO."""

    replica_count: int
    throughput_tokens_per_s_total: float
    p99_latency_ms: float
    cost_per_hr: float
    meets_slo: bool
    provenance: Provenance


class NormalizedScores(BaseModel):
    """Each axis min-max normalized to [0, 1] across the SLO-compliant,
    confidence-qualified candidate set for this decision — 1.0 is best in
    class, 0.0 is worst. Not comparable across different decisions."""

    cost: float
    performance: float
    headroom: float


CandidateStatus = Literal["recommended", "feasible", "rejected"]


class CandidateEvaluation(BaseModel):
    target_id: str
    target_label: str
    vendor: str
    feasible: bool
    status: CandidateStatus = "rejected"
    checks: list[FeasibilityCheck]
    rejection_reason: Optional[str] = None
    rejection_reasons: list[str] = Field(default_factory=list)
    raw_prediction: Optional[Prediction] = None
    slo_violations: list[str] = Field(default_factory=list)
    predicted: Optional[PredictedOutcome] = None
    capacity_constrained: bool = False
    capacity_note: Optional[str] = None
    normalized_scores: Optional[NormalizedScores] = None
    score: Optional[float] = None
    weighted_score: Optional[float] = None
    confidence_pct: Optional[float] = None
    meets_confidence_requirement: Optional[bool] = None
    rank: Optional[int] = None
    why_not_chosen: Optional[str] = None
