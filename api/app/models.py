"""Typed data contracts for the Forgeway decision engine.

These are the ONLY shapes that cross the API boundary. The frontend's
lib/types.ts mirrors this file by hand — keep them in sync when you change
either side.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, computed_field, field_validator

Provenance = Literal["MEASURED", "PUBLISHED", "MODELED"]
WorkloadClass = Literal["realtime-inference", "batch-inference", "training"]


class ScenarioType(str, Enum):
    normal = "normal"
    demand_spike = "demand_spike"
    h100_capacity_loss = "h100_capacity_loss"
    cost_priority = "cost_priority"
    performance_priority = "performance_priority"
    strict_confidence_policy = "strict_confidence_policy"


# --------------------------------------------------------------------------
# Metric — the one shape every number in this engine is reported through.
# Every metric carries what it is, how sure we are, where it came from, and
# the range it could plausibly fall in (when one is known). A candidate is
# never allowed to present a MODELED number as if it were MEASURED — this is
# the type that makes that distinction impossible to drop on the way to the
# UI.
# --------------------------------------------------------------------------


class Metric(BaseModel):
    value: float
    confidence: float = Field(ge=0, le=100)
    provenance: Provenance
    range_low: Optional[float] = None
    range_high: Optional[float] = None
    source: str = ""


# --------------------------------------------------------------------------
# Fixture-backed domain objects
# --------------------------------------------------------------------------


class UnsupportedWorkloadClass(BaseModel):
    workload_class: str
    reason: str


class ComputeTarget(BaseModel):
    id: str
    vendor: str
    model: str
    tier: Literal["datacenter", "edge", "lab"]
    location: str
    architecture: str
    memory_gb_per_device: float
    interconnect: str
    supported_precisions: list[str]
    capacity_units_total: int
    capacity_units_allocated: int
    price_per_hr_per_unit: Metric
    status: Literal["healthy", "degraded", "offline"]
    unsupported_workload_classes: list[UnsupportedWorkloadClass] = Field(default_factory=list)
    notes: str = ""

    @computed_field  # type: ignore[misc]
    @property
    def free_capacity_units(self) -> int:
        return max(self.capacity_units_total - self.capacity_units_allocated, 0)

    @computed_field  # type: ignore[misc]
    @property
    def utilization_pct(self) -> float:
        if self.capacity_units_total == 0:
            return 0.0
        return round(100 * self.capacity_units_allocated / self.capacity_units_total, 1)


class SLO(BaseModel):
    p99_latency_ms: float
    min_throughput_tokens_per_s: float
    availability_pct: float


class EnterprisePolicy(BaseModel):
    allowed_vendors: list[str]
    denied_vendors: list[str] = Field(default_factory=list)
    allowed_regions: list[str]
    budget_ceiling_per_hr: float


class ObjectiveWeights(BaseModel):
    """Relative priority a workload places on cost, performance (latency
    headroom), and fleet headroom (spare capacity left behind). Arbitrary
    non-negative numbers — the engine normalizes them before scoring, so
    (1, 1, 1) and (5, 5, 5) rank identically."""

    cost: float = 0.5
    performance: float = 0.3
    headroom: float = 0.2

    @field_validator("cost", "performance", "headroom")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("objective weights must be non-negative")
        return v

    def normalized(self) -> "ObjectiveWeights":
        total = self.cost + self.performance + self.headroom
        if total <= 0:
            return ObjectiveWeights(cost=1 / 3, performance=1 / 3, headroom=1 / 3)
        return ObjectiveWeights(
            cost=self.cost / total,
            performance=self.performance / total,
            headroom=self.headroom / total,
        )


class CurrentPlacement(BaseModel):
    target_id: str
    replica_count: int
    measured_p99_latency_ms: float
    measured_throughput_tokens_per_s_per_replica: float
    cost_per_hr: float
    provenance: Provenance
    source: str


class Workload(BaseModel):
    id: str
    name: str
    model_family: str
    model_params_billion: float
    workload_class: WorkloadClass
    precision: str
    weights_footprint_gb: float
    kv_cache_overhead_gb: float
    baseline_concurrency: int
    slo: SLO
    policy: EnterprisePolicy
    current_placement: CurrentPlacement
    objective_weights: ObjectiveWeights = Field(default_factory=ObjectiveWeights)
    min_confidence_pct: float = 70.0
    tokens_per_request: Optional[float] = None
    reanalyze: bool = False


class PerformanceProfile(BaseModel):
    """Raw fixture row: what we know about running this workload on this
    target, per replica. Combined with the target's price at retrieval time
    (engine step 5) to build a full Prediction."""

    workload_id: str
    target_id: str
    throughput_tokens_per_s_per_replica: Metric
    p99_latency_ms_per_replica: Metric


# --------------------------------------------------------------------------
# Decision-engine output objects
# --------------------------------------------------------------------------


class FeasibilityCheck(BaseModel):
    name: str
    passed: bool
    detail: str


class Prediction(BaseModel):
    """What we predict for one workload on one target, per replica —
    retrieved (not computed) from the performance-profile fixture plus the
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


class Evidence(BaseModel):
    label: str
    display_value: str
    metric: Metric
    source: str


class SplitAllocation(BaseModel):
    target_id: str
    target_label: str
    replica_count: int
    throughput_tokens_per_s: float
    throughput_share_pct: float
    cost_per_hr: float
    p99_latency_ms: float


class UnmitigatedProjection(BaseModel):
    """What happens if the operator does nothing and the prior placement absorbs new load as-is."""

    target_id: str
    target_label: str
    replica_count: int
    required_throughput_tokens_per_s: float
    available_throughput_tokens_per_s: float
    utilization_ratio: float
    predicted_p99_latency_ms: float
    slo_violated: bool
    narrative: str


class ScenarioParams(BaseModel):
    type: ScenarioType
    demand_multiplier: Optional[float] = None
    capacity_loss_target_id: Optional[str] = None
    capacity_loss_pct: Optional[float] = None
    label: str


class Recommendation(BaseModel):
    id: str
    workload_id: str
    workload_name: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    scenario: ScenarioParams
    derived_from_id: Optional[str] = None
    slo: SLO
    current_placement: CurrentPlacement
    effective_min_throughput_tokens_per_s: float
    objective_weights: ObjectiveWeights
    min_confidence_pct: float
    candidates: list[CandidateEvaluation]
    recommended_target_id: Optional[str] = None
    recommended: Optional[PredictedOutcome] = None
    split_allocation: list[SplitAllocation] = Field(default_factory=list)
    achieved_throughput_tokens_per_s: float = 0.0
    shortfall_tokens_per_s: float = 0.0
    slo_met: bool = False
    confidence_pct: int = 0
    evidence: list[Evidence] = Field(default_factory=list)
    unmitigated_projection: Optional[UnmitigatedProjection] = None
    reasoning: str = ""


class WorkloadListItem(BaseModel):
    workload: Workload
    slo_status: Literal["met", "violated"]
    latest_recommendation_id: Optional[str] = None


class VendorBreakdown(BaseModel):
    vendor: str
    devices_total: int
    devices_allocated: int
    utilization_pct: float


class InsightCard(BaseModel):
    workload_id: str
    workload_name: str
    title: str
    body: str
    recommendation_id: str
    current_target_id: str
    current_cost_per_hr: float
    recommended_target_id: str
    recommended_cost_per_hr: float
    savings_pct: float
    slo_met: bool
    confidence_pct: int


class EstateSummary(BaseModel):
    devices_total: int
    devices_allocated: int
    overall_utilization_pct: float
    active_workloads: int
    estimated_spend_per_hr: float
    slo_compliance_pct: float
    vendor_breakdown: list[VendorBreakdown]
    insights: list[InsightCard]


class AnalyzeRequest(BaseModel):
    workload_id: str
    objective_weights: Optional[ObjectiveWeights] = None
    min_confidence_pct: Optional[float] = None


# --------------------------------------------------------------------------
# Scenario simulation — six named, backend-owned presets. A scenario never
# mutates fixture/production state: it derives temporary overrides from the
# workload's own canonical baseline and reruns run_decision(), producing two
# independently stored Recommendations (before/after) plus an explicit
# comparison. The frontend never invents a scenario's parameters or its
# outcome — everything here comes from this API.
# --------------------------------------------------------------------------


class ScenarioCatalogEntry(BaseModel):
    name: ScenarioType
    label: str
    description: str


class ScenarioRequest(BaseModel):
    scenario: ScenarioType


class ScenarioEventInfo(BaseModel):
    name: ScenarioType
    label: str
    description: str


class ScenarioComparison(BaseModel):
    workload_id: str
    event: ScenarioEventInfo
    before: Recommendation
    after: Recommendation
    change_explanation: str
