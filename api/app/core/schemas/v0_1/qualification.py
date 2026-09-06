"""QualificationRecord (forgeway/v0.1) — a sourced, dated, evidence-linked
fact about whether one specific combination actually works, kept
deliberately separate from `Metric.confidence` (measurement uncertainty)
and from free-text rejection reasons.

A qualification is never about a vendor. It's about a combination: the
exact hardware, runtime and version, model, precision, deployment
configuration, and workload/SLO a caller cares about
(`QualificationSubject`). "This precision is not supported on this GPU"
and "this latency measurement has 80% confidence" are different kinds of
fact — the first is answered here, the second stays on `Metric` — and
blurring them would make both harder to reason about (see
docs/qualification.md's rationale).

Every record carries `source`, `environment`, `timestamp`, an optional
`evidence_reference`, and an optional `review_date` — the minimum a reader
needs to judge whether to trust and still rely on the claim. A record
going stale (`review_date` in the past — see `is_stale()` in
app.qualification.store) means "revalidate, or discount this," never
"treat as failed" — see docs/qualification.md.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.core.schemas.workload import SLO, WorkloadClass

SCHEMA_VERSION = "forgeway/v0.1"

#: Four states in the sense that matters to a caller deciding whether to
#: trust a claim — "measured pass" and "measured fail" are the two
#: possible outcomes of the same fourth state ("a specific SLO was
#: actually evaluated"), not a fifth, weaker kind of fact.
QualificationState = Literal["unknown", "unsupported", "smoke_tested", "measured_pass", "measured_fail"]

#: The order staged checking runs in. A later stage presupposes every
#: earlier one passed — an installed plugin or a registered entry point
#: only proves "runtime_present," nothing about the stages after it
#: (see app.qualification.checker.RuntimeChecker).
QualificationStage = Literal["runtime_present", "device_reachable", "config_supported", "smoke_test_passed"]


class QualificationStageResult(BaseModel):
    """One stage of the staged pipeline — mirrors
    app.core.schemas.engine.FeasibilityCheck's (name, passed, detail)
    shape deliberately, for the same reason: every stage is reported, not
    just the first failure, so a reader can see exactly how far checking
    actually got."""

    stage: QualificationStage
    passed: bool
    detail: str


class QualificationSubject(BaseModel):
    """The exact combination a qualification record is about. Never tied
    to one specific discovered ComputeTarget instance (the same hardware
    class gets rediscovered many times, under many ids) — `vendor` /
    `hardware_model` / `architecture` describe a class of hardware, the
    same way a BenchmarkProfile describes a class of run rather than one
    specific execution.

    `slo` is deliberately optional and part of this type's identity
    (`subject_key()` hashes the whole object): a general "does this
    combination run at all for this workload class" fact
    (`slo=None`) and a "does it meet this exact SLO" fact (`slo` set) are
    different claims about different things, not the same claim at two
    levels of detail — conflating them would let a coarse "it runs" fact
    be mistaken for "it meets this SLO," which is exactly the kind of
    blurring this schema exists to avoid.
    """

    vendor: str
    hardware_model: str
    architecture: Optional[str] = None
    runtime: str
    runtime_version: Optional[str] = None
    backend: Optional[str] = None
    #: Normally an exact model id, matching BenchmarkProfile.model (e.g.
    #: "meta-llama/Llama-3.1-70B-Instruct"). "*" is a documented wildcard
    #: meaning "any model" — used only by general, workload-class-level
    #: facts (app.engine.qualification_check.ANY_MODEL, and any
    #: hand-authored record meant to apply regardless of model), never by
    #: a real measured/smoke-tested claim about one specific model.
    model: str
    #: Normally an exact precision string (matching BenchmarkProfile.
    #: precision, e.g. "fp8"). "*" (app.engine.qualification_check.
    #: ANY_PRECISION) is the same documented wildcard as `model` above,
    #: for the same reason: precision *compatibility* is already its own
    #: independent check (app.core.engine.feasibility), so a general
    #: workload-class-level qualification fact is deliberately
    #: precision-agnostic.
    precision: str
    deployment_config: dict = Field(default_factory=dict)
    workload_class: WorkloadClass
    slo: Optional[SLO] = None

    def subject_key(self) -> str:
        """A deterministic identity for this exact combination — what the
        databank (app.qualification.store) looks records up by. Two
        subjects with identical fields (including a None-vs-None `slo`)
        share a key; anything different, including a specific `slo` vs.
        none, does not."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


class QualificationRecord(BaseModel):
    schema_version: Literal["forgeway/v0.1"] = SCHEMA_VERSION
    id: str
    subject: QualificationSubject
    state: QualificationState
    stages: list[QualificationStageResult] = Field(default_factory=list)
    source: str
    environment: str
    evidence_reference: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    review_date: Optional[date] = None
    notes: str = ""

    @model_validator(mode="after")
    def _measured_states_require_slo_and_evidence(self) -> "QualificationRecord":
        if self.state in ("measured_pass", "measured_fail"):
            if self.subject.slo is None:
                raise ValueError(
                    f"state={self.state!r} claims a specific SLO was evaluated, but "
                    "subject.slo is not set"
                )
            if not self.evidence_reference:
                raise ValueError(
                    f"state={self.state!r} claims a specific SLO was evaluated, but "
                    "evidence_reference is not set — a measured claim must point at what measured it"
                )
        return self

    @classmethod
    def for_subject(cls, subject: QualificationSubject, **fields) -> "QualificationRecord":
        """Convenience constructor that fills `id` from
        `subject.subject_key()` rather than requiring every caller to
        remember the `qual-<key>` convention."""
        return cls(id=f"qual-{subject.subject_key()}", subject=subject, **fields)
