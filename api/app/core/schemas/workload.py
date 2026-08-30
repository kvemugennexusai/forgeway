"""The workload schema — what a caller needs to know about one deployable
AI workload to place it: its footprint, its SLO, its enterprise policy
constraints, and where it runs today.

This is the forgeway/v0.1 AIWorkload contract (see docs/schemas.md and
app.core.schemas.v0_1). The class below keeps the name `Workload` — it's
used throughout this codebase's engine, routers, and tests — and
`AIWorkload` is exported as a plain alias for the same class from
app.core.schemas.v0_1, so external/formal references can use the
vendor-neutral name without any internal rename."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.core.schemas.evidence import Metric, Provenance

SCHEMA_VERSION = "forgeway/v0.1"

WorkloadClass = Literal["realtime-inference", "batch-inference", "training"]


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
    schema_version: Literal["forgeway/v0.1"] = SCHEMA_VERSION
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
    """Raw benchmark/evidence row: what we know about running this workload
    on this target, per replica. Combined with the target's price at
    retrieval time to build a full Prediction (app.core.schemas.engine)."""

    workload_id: str
    target_id: str
    throughput_tokens_per_s_per_replica: Metric
    p99_latency_ms_per_replica: Metric
