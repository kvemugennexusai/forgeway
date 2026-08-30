"""PerformanceEvidence (forgeway/v0.1) — a portable, timestamped record of
what's known about running one workload on one compute target.

This formalizes a concept the engine already has, spread across two
places: `app.core.schemas.PerformanceProfile` (the fixture-shaped pair of
throughput/latency Metrics `app.core.engine.scoring` reads) and the
`Prediction` it's turned into once a target's price is attached. Neither of
those carries a timestamp, a Forgeway version, or a benchmark-run id, and
neither is meant to be handed to an external caller as a standalone record.
PerformanceEvidence is that standalone record — built from a
PerformanceProfile via `from_performance_profile()`, additive only: nothing
in app.core.engine changes to produce or consume this type.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.core.schemas.evidence import Metric, Provenance
from app.core.schemas.workload import PerformanceProfile
from app.core.version import FORGEWAY_VERSION

SCHEMA_VERSION = "forgeway/v0.1"

_PROVENANCE_RANK: dict[Provenance, int] = {"MODELED": 0, "PUBLISHED": 1, "MEASURED": 2}


def _weakest_provenance(provenances: list[Provenance]) -> Provenance:
    """The least-certain provenance among a set — a record is never allowed
    to claim better evidence than its weakest contributing metric."""
    return min(provenances, key=lambda p: _PROVENANCE_RANK[p])


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
            "throughput_tokens_per_s_per_replica": profile.throughput_tokens_per_s_per_replica,
            "p99_latency_ms_per_replica": profile.p99_latency_ms_per_replica,
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
