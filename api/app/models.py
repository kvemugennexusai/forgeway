"""Typed data contracts for the Forgeway product API.

These are the ONLY shapes that cross the API boundary. The frontend's
lib/types.ts mirrors this file by hand — keep them in sync when you change
either side.

The reusable, product-agnostic contracts (compute targets, workloads,
evidence, engine output) live in `app.core.schemas` and are re-exported
below unchanged, so every existing `from app.models import X` keeps working.
Everything defined directly in this file — Recommendation, the six-scenario
types, estate/dashboard views, request DTOs — is this product's own
storytelling and API surface on top of that core; see
docs/architecture.md for the boundary.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.core.schemas import (
    SLO,
    CandidateEvaluation,
    CandidateStatus,
    ComputeTarget,
    CurrentPlacement,
    EnterprisePolicy,
    FeasibilityCheck,
    Metric,
    NormalizedScores,
    ObjectiveWeights,
    PerformanceEvidence,
    PerformanceProfile,
    PredictedOutcome,
    Prediction,
    Provenance,
    UnsupportedWorkloadClass,
    Workload,
    WorkloadClass,
)

__all__ = [
    "Provenance",
    "WorkloadClass",
    "Metric",
    "UnsupportedWorkloadClass",
    "ComputeTarget",
    "SLO",
    "EnterprisePolicy",
    "ObjectiveWeights",
    "CurrentPlacement",
    "Workload",
    "PerformanceProfile",
    "PerformanceEvidence",
    "FeasibilityCheck",
    "Prediction",
    "PredictedOutcome",
    "NormalizedScores",
    "CandidateStatus",
    "CandidateEvaluation",
    "ScenarioType",
    "Evidence",
    "SplitAllocation",
    "UnmitigatedProjection",
    "ScenarioParams",
    "Recommendation",
    "WorkloadListItem",
    "VendorBreakdown",
    "InsightCard",
    "EstateSummary",
    "AnalyzeRequest",
    "ScenarioCatalogEntry",
    "ScenarioRequest",
    "ScenarioEventInfo",
    "ScenarioComparison",
]


class ScenarioType(str, Enum):
    normal = "normal"
    demand_spike = "demand_spike"
    h100_capacity_loss = "h100_capacity_loss"
    cost_priority = "cost_priority"
    performance_priority = "performance_priority"
    strict_confidence_policy = "strict_confidence_policy"


# --------------------------------------------------------------------------
# Product-specific objects, built on top of app.core.schemas. `Evidence`
# below is deliberately distinct from `Prediction`/`Metric`: it's a
# display-oriented row (label + formatted value) for the UI's evidence
# panel, not a core evidence primitive.
# --------------------------------------------------------------------------


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
    # "Import benchmark result" (docs/importing-results.md): a browser-local
    # set of targets/evidence the user uploaded, sent with the request
    # rather than stored server-side. Kept strictly additive to the
    # fixture catalog — analyze.py rejects an imported target whose id
    # collides with a reference one, so imported data is never silently
    # merged into the demo's own fixtures.
    imported_targets: list[ComputeTarget] = Field(default_factory=list)
    imported_evidence: list[PerformanceEvidence] = Field(default_factory=list)


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
