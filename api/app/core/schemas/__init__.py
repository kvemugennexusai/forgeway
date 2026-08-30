"""Forgeway core schemas — the typed contracts for compute targets,
workloads, evidence, and engine output. These are the ONLY shapes the core
engine (app.core.engine) accepts or returns; a product built on top of
Forgeway (this demo's API included) adds its own request/response and
narrative types on top of these rather than duplicating them."""
from __future__ import annotations

from app.core.schemas.compute import ComputeTarget, UnsupportedWorkloadClass
from app.core.schemas.engine import (
    CandidateEvaluation,
    CandidateStatus,
    FeasibilityCheck,
    NormalizedScores,
    PredictedOutcome,
    Prediction,
)
from app.core.schemas.evidence import PROVENANCE_RANK, Metric, Provenance
from app.core.schemas.performance_evidence import (
    LATENCY_METRIC_KEY,
    THROUGHPUT_METRIC_KEY,
    PerformanceEvidence,
)
from app.core.schemas.workload import (
    SLO,
    CurrentPlacement,
    EnterprisePolicy,
    ObjectiveWeights,
    PerformanceProfile,
    Workload,
    WorkloadClass,
)

__all__ = [
    "ComputeTarget",
    "UnsupportedWorkloadClass",
    "CandidateEvaluation",
    "CandidateStatus",
    "FeasibilityCheck",
    "NormalizedScores",
    "PredictedOutcome",
    "Prediction",
    "Metric",
    "Provenance",
    "PROVENANCE_RANK",
    "PerformanceEvidence",
    "LATENCY_METRIC_KEY",
    "THROUGHPUT_METRIC_KEY",
    "SLO",
    "CurrentPlacement",
    "EnterprisePolicy",
    "ObjectiveWeights",
    "PerformanceProfile",
    "Workload",
    "WorkloadClass",
]
