"""Consults the qualification databank (app.qualification.store) to build
one additive FeasibilityCheck for a (workload, target) pair — kept
outside app.core.engine.feasibility deliberately: app.core is proven
decoupled from any I/O source (api/tests/test_core_isolation.py), and the
databank is real filesystem I/O (a bundled fixture + a local directory) —
the same reason app.engine.evidence_gateway, not app.core, is what
touches app.benchmark.store for PerformanceEvidence.

Deliberately coarse: this check only ever looks up a general,
model-agnostic, config-agnostic subject (QualificationSubject.model="*",
deployment_config={}, slo=None) — a record produced by a real
`forgeway qualify` run (which pins a specific model and deployment
config) is a different, more specific subject and is never matched here.
See docs/qualification.md.
"""
from __future__ import annotations

from app.core.schemas import ComputeTarget, FeasibilityCheck, Workload
from app.core.schemas.v0_1.qualification import QualificationSubject
from app.qualification.store import get_qualification, is_stale

_CHECK_NAME = "qualification: databank record"

#: Forgeway's only real runtime today (app.benchmark.cross_vendor.
#: BenchmarkProfile.runtime's default) — this coarse check has nothing
#: else to look up against yet. Revisit once ComputeTarget.runtime_support
#: is ever actually populated by a discovery adapter.
_ONLY_REAL_RUNTIME = "vllm"

#: QualificationSubject.model is normally an exact model id (matching
#: BenchmarkProfile.model) — "*" is the documented wildcard meaning "any
#: model," used by general, workload-class-level facts (this check, and
#: any hand-authored record meant to apply regardless of model).
ANY_MODEL = "*"


def coarse_qualification_subject(workload: Workload, target: ComputeTarget) -> QualificationSubject:
    return QualificationSubject(
        vendor=target.vendor,
        hardware_model=target.model,
        runtime=_ONLY_REAL_RUNTIME,
        model=ANY_MODEL,
        precision=workload.precision,
        workload_class=workload.workload_class,
    )


def evaluate_databank_qualification(workload: Workload, target: ComputeTarget) -> FeasibilityCheck:
    """Additive to app.core.engine.feasibility.evaluate_feasibility()'s own
    "software: workload class qualified" check (which still reads
    ComputeTarget.unsupported_workload_classes, untouched) — both run
    independently, same "unrelated facts, unrelated reasons" discipline
    already stated in feasibility.py's module docstring.

    A stale record (app.qualification.store.is_stale()) never flips this
    check's pass/fail outcome either direction, only annotates `detail` —
    per the rule that a stale record means "revalidate," not a silent
    rejection (or a silent acceptance)."""
    subject = coarse_qualification_subject(workload, target)
    record = get_qualification(subject)
    stale_note = (
        " (this record is stale — recommend revalidating)" if record is not None and is_stale(record) else ""
    )

    if record is None:
        return FeasibilityCheck(
            name=_CHECK_NAME,
            passed=True,
            detail=f"'{workload.workload_class}' on {target.model} has no qualification record yet — "
            "not blocking; see `forgeway qualify`",
        )

    if record.state == "unsupported":
        return FeasibilityCheck(name=_CHECK_NAME, passed=False, detail=record.source + stale_note)

    if record.state == "unknown":
        return FeasibilityCheck(
            name=_CHECK_NAME,
            passed=True,
            detail=f"'{workload.workload_class}' on {target.model} is recorded as not yet checked "
            "(state=unknown) — not blocking; see `forgeway qualify`" + stale_note,
        )

    return FeasibilityCheck(
        name=_CHECK_NAME,
        passed=True,
        detail=f"'{workload.workload_class}' on {target.model} is qualified (state={record.state}) — "
        f"source: {record.source}" + stale_note,
    )
