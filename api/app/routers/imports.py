"""Import benchmark result (docs/importing-results.md): validates an
uploaded ComputeTarget or PerformanceEvidence JSON record against the real
Pydantic schema — the same one the CLI and the rest of the engine use, so
validation can never drift between "what the CLI produces" and "what the
web UI accepts".

FastAPI/Pydantic do the actual validation via each endpoint's declared
request-body type: a malformed body, an unsupported schema_version (both
schemas pin `Literal["forgeway/v0.1"]`), or a missing required field all
surface as FastAPI's standard 422 response with per-field detail — no
hand-rolled validation logic here to drift out of sync with the schema.

Stateless: nothing is persisted server-side. This is the "no server-side
persistence for this feature" line from the goal — the browser (see
web/lib/imported-storage.ts) is the only place this feature keeps state;
these endpoints just confirm an upload is valid and hand it straight back.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.core.schemas import ComputeTarget
from app.core.schemas.v0_1 import PerformanceEvidence

router = APIRouter(prefix="/api/import", tags=["import"])


@router.post("/performance-evidence", response_model=PerformanceEvidence)
def validate_performance_evidence(payload: PerformanceEvidence) -> PerformanceEvidence:
    return payload


@router.post("/compute-target", response_model=ComputeTarget)
def validate_compute_target(payload: ComputeTarget) -> ComputeTarget:
    return payload
