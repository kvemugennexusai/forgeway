from fastapi import APIRouter, HTTPException

from app.data.loader import get_workload, load_compute_targets
from app.engine.decision import run_decision
from app.models import AnalyzeRequest, Recommendation, ScenarioParams, ScenarioType
from app.state import store

router = APIRouter(prefix="/api/analyze", tags=["analyze"])


@router.post("", response_model=Recommendation)
def analyze(payload: AnalyzeRequest) -> Recommendation:
    workload = get_workload(payload.workload_id)
    if workload is None:
        raise HTTPException(status_code=404, detail=f"Unknown workload '{payload.workload_id}'")

    reference_targets = load_compute_targets()
    reference_ids = {t.id for t in reference_targets}

    # "Do not merge imported data silently with demo/reference fixtures"
    # (docs/importing-results.md): an imported target id that collides with
    # a reference one is rejected outright, never silently overwritten or
    # blended.
    if payload.imported_targets:
        colliding = [t.id for t in payload.imported_targets if t.id in reference_ids]
        if colliding:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Imported target id(s) conflict with the reference catalog and were not "
                    f"applied: {', '.join(colliding)}. Re-export with a different id."
                ),
            )

    # The same "never silently merged" rule applies to evidence, not just
    # targets: imported_evidence naming a reference-catalog compute_target_id
    # would otherwise be gathered as a scoring candidate for that reference
    # target (app/engine/evidence_gateway.py matches on compute_target_id
    # alone) and could outrank — and silently replace — its real fixture
    # evidence via ordinary MEASURED > PUBLISHED > MODELED / confidence /
    # recency tie-breaking, with no id-collision signal to catch it the way
    # imported_targets has above. Evidence is only ever legitimate for a
    # target the caller also imported in this same request.
    imported_target_ids = {t.id for t in payload.imported_targets}
    if payload.imported_evidence:
        evidence_colliding = sorted(
            {
                e.compute_target_id
                for e in payload.imported_evidence
                if e.compute_target_id in reference_ids and e.compute_target_id not in imported_target_ids
            }
        )
        if evidence_colliding:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Imported evidence references reference-catalog target id(s) that were not "
                    f"also imported as a target, and was not applied: {', '.join(evidence_colliding)}. "
                    "Import evidence only for a target you also imported, to avoid silently overriding "
                    "trusted reference data."
                ),
            )

    targets = reference_targets + payload.imported_targets

    record = run_decision(
        workload,
        record_id=store.next_id(),
        scenario=ScenarioParams(type=ScenarioType.normal, label="Normal — baseline, no scenario applied"),
        effective_min_throughput=workload.slo.min_throughput_tokens_per_s,
        objective_weights=payload.objective_weights,
        min_confidence_pct=payload.min_confidence_pct,
        targets=targets,
        imported_evidence=payload.imported_evidence,
    )
    return store.put(record)
