"""The evidence primitive — the one shape every number in the engine is
reported through.

Every metric carries what it is, how sure we are, where it came from, and
the range it could plausibly fall in (when one is known). A candidate is
never allowed to present a MODELED number as if it were MEASURED — this is
the type that makes that distinction impossible to drop on the way to a
caller.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Provenance = Literal["MEASURED", "PUBLISHED", "MODELED"]

#: How much to trust one provenance tier over another — higher is more
#: trustworthy. The single shared ranking used everywhere Forgeway needs
#: to compare provenances: PerformanceEvidence.from_performance_profile()
#: (a record's overall provenance is never better than its weakest
#: contributing metric) and app.core.engine.evidence_selection
#: (prefer the best-provenance evidence among what's actually usable).
PROVENANCE_RANK: dict[Provenance, int] = {"MODELED": 0, "PUBLISHED": 1, "MEASURED": 2}


class Metric(BaseModel):
    value: float
    confidence: float = Field(ge=0, le=100)
    provenance: Provenance
    range_low: Optional[float] = None
    range_high: Optional[float] = None
    source: str = ""
    # Traceable pointer back to the PerformanceEvidence this metric was
    # selected from — a real benchmark_run_id for a measured evidence
    # record, or a synthetic fixture-evidence descriptor otherwise. None
    # for metrics that don't come through the evidence-selection path
    # (e.g. ComputeTarget.price_per_hr_per_unit, which has its own `source`
    # string and isn't part of PerformanceEvidence).
    evidence_reference: Optional[str] = None
