"""PerformanceEvidence — a portable, timestamped record of what's known
about running one workload on one compute target, and the single shape
app.core.engine.evidence_selection and app.core.engine.scoring consume.

Originally introduced as a v0.1-only formal contract (see
docs/schemas.md), not yet used internally. It's promoted here, into
app.core.schemas proper, now that the placement engine actually consumes
it (docs/decision-engine.md) — the same move already made for
ComputeTarget and Workload/AIWorkload: the core engine-facing definition
lives here, and app.core.schemas.v0_1 re-exports it unchanged under the
same formal name. Nothing importing `app.core.schemas.v0_1.PerformanceEvidence`
needs to change.

Built from a PerformanceProfile fixture row via
`from_performance_profile()`, or from a real benchmark run
(app.benchmark.evidence.build_performance_evidence) — either way, the
engine only ever sees this one shape.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.core.schemas.evidence import PROVENANCE_RANK, Metric, Provenance
from app.core.schemas.workload import PerformanceProfile
from app.core.version import FORGEWAY_VERSION

SCHEMA_VERSION = "forgeway/v0.1"

#: Canonical per-replica metric keys app.core.engine.scoring needs from a
#: selected PerformanceEvidence. Both fixture-derived evidence (below) and
#: a real benchmark run must use these exact keys to be usable by the
#: engine — see docs/decision-engine.md on why key names aren't fuzzy-matched.
LATENCY_METRIC_KEY = "p99_latency_ms_per_replica"
THROUGHPUT_METRIC_KEY = "throughput_tokens_per_s_per_replica"


def _weakest_provenance(provenances: list[Provenance]) -> Provenance:
    """The least-certain provenance among a set — a record is never allowed
    to claim better evidence than its weakest contributing metric."""
    return min(provenances, key=lambda p: PROVENANCE_RANK[p])


class PerformanceEvidence(BaseModel):
    schema_version: Literal["forgeway/v0.1"] = SCHEMA_VERSION
    compute_target_id: str
    workload_id: str
    # Free-text description of the run this evidence reflects (e.g. replica
    # count, tensor-parallel degree), when known. Not populated by today's
    # fixtures — there is no structured configuration data to draw from yet.
    configuration: Optional[str] = None
    metrics: dict[str, Metric] = Field(default_factory=dict)
    provenance: Provenance
    confidence: float = Field(ge=0, le=100)
    source: str = ""
    # None means "not recorded" — today's fixtures carry no timestamp, and
    # this deliberately doesn't default to "now" to avoid implying a measurement
    # just happened when it's actually migrated fixture data.
    timestamp: Optional[datetime] = None
    forgeway_version: str = FORGEWAY_VERSION
    benchmark_run_id: Optional[str] = None

    @classmethod
    def from_performance_profile(
        cls,
        profile: PerformanceProfile,
        *,
        configuration: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        benchmark_run_id: Optional[str] = None,
    ) -> "PerformanceEvidence":
        metrics = {
            THROUGHPUT_METRIC_KEY: profile.throughput_tokens_per_s_per_replica,
            LATENCY_METRIC_KEY: profile.p99_latency_ms_per_replica,
        }
        confidence = min(m.confidence for m in metrics.values())
        provenance = _weakest_provenance([m.provenance for m in metrics.values()])
        # In every current fixture row both metrics share one source string;
        # the throughput metric's source is used as the representative one.
        source = profile.throughput_tokens_per_s_per_replica.source
        return cls(
            compute_target_id=profile.target_id,
            workload_id=profile.workload_id,
            configuration=configuration,
            metrics=metrics,
            provenance=provenance,
            confidence=confidence,
            source=source,
            timestamp=timestamp,
            benchmark_run_id=benchmark_run_id,
        )
