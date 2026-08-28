from fastapi import APIRouter, HTTPException

from app.data.loader import get_workload
from app.engine.decision import run_decision
from app.models import AnalyzeRequest, Recommendation, ScenarioParams, ScenarioType
from app.state import store

router = APIRouter(prefix="/api/analyze", tags=["analyze"])


@router.post("", response_model=Recommendation)
def analyze(payload: AnalyzeRequest) -> Recommendation:
    workload = get_workload(payload.workload_id)
    if workload is None:
        raise HTTPException(status_code=404, detail=f"Unknown workload '{payload.workload_id}'")

    record = run_decision(
        workload,
        record_id=store.next_id(),
        scenario=ScenarioParams(type=ScenarioType.normal, label="Normal — baseline, no scenario applied"),
        effective_min_throughput=workload.slo.min_throughput_tokens_per_s,
        objective_weights=payload.objective_weights,
        min_confidence_pct=payload.min_confidence_pct,
    )
    return store.put(record)
