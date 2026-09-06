"""forgeway/v0.1 — Forgeway's formal, versioned data contracts.

Five concepts, matching docs/schemas.md:

  ComputeTarget       app.core.schemas.compute.ComputeTarget, unchanged in
                      place — it was already this codebase's one canonical
                      compute-target type.
  AIWorkload          alias for app.core.schemas.workload.Workload, same
                      reason — the vendor-neutral name for an existing type,
                      not a new one.
  PerformanceEvidence a portable record of one (workload, target)
                      performance observation, built via
                      PerformanceEvidence.from_performance_profile() or a
                      real `forgeway bench` run. Also the shape the
                      placement engine itself consumes — see
                      docs/decision-engine.md — which is why its
                      definition now lives in app.core.schemas proper
                      (this module just re-exports it, same as
                      ComputeTarget and AIWorkload below).
  PlacementDecision   a vendor-neutral summary of one placement decision,
                      built via PlacementDecision.from_candidates().
  QualificationRecord new: a sourced, dated, evidence-linked fact about
                      whether one specific hardware+runtime+model+
                      precision+config+workload/SLO combination actually
                      works — see docs/qualification.md.

Every one of the five carries `schema_version == "forgeway/v0.1"`. See
docs/schemas.md for field-level documentation and examples/ for
serialized instances.
"""
from __future__ import annotations

from app.core.schemas.compute import ComputeTarget
from app.core.schemas.performance_evidence import PerformanceEvidence
from app.core.schemas.v0_1.placement_decision import (
    EvidenceReference,
    ImprovementVsCurrentPlacement,
    PlacementDecision,
    RejectedTarget,
    ScoreBreakdown,
)
from app.core.schemas.v0_1.qualification import (
    QualificationRecord,
    QualificationStage,
    QualificationStageResult,
    QualificationState,
    QualificationSubject,
)
from app.core.schemas.workload import Workload as AIWorkload

SCHEMA_VERSION = "forgeway/v0.1"

__all__ = [
    "SCHEMA_VERSION",
    "ComputeTarget",
    "AIWorkload",
    "PerformanceEvidence",
    "PlacementDecision",
    "RejectedTarget",
    "ScoreBreakdown",
    "ImprovementVsCurrentPlacement",
    "EvidenceReference",
    "QualificationRecord",
    "QualificationSubject",
    "QualificationState",
    "QualificationStage",
    "QualificationStageResult",
]
