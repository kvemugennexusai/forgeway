from fastapi import APIRouter, HTTPException

from app.data.loader import get_workload
from app.engine.scenarios import CATALOG, run_scenario
from app.models import ScenarioCatalogEntry, ScenarioComparison, ScenarioRequest
from app.state import store

router = APIRouter(prefix="/api", tags=["scenarios"])


@router.get("/scenarios", response_model=list[ScenarioCatalogEntry])
def list_scenarios() -> list[ScenarioCatalogEntry]:
    return [ScenarioCatalogEntry(name=e.name, label=e.label, description=e.description) for e in CATALOG]


@router.post("/workloads/{workload_id}/scenario", response_model=ScenarioComparison)
def apply_workload_scenario(workload_id: str, payload: ScenarioRequest) -> ScenarioComparison:
    workload = get_workload(workload_id)
    if workload is None:
        raise HTTPException(status_code=404, detail=f"Unknown workload '{workload_id}'")

    comparison = run_scenario(
        workload,
        payload.scenario,
        before_id=store.next_id(),
        after_id=store.next_id(),
    )
    store.put(comparison.before)
    store.put(comparison.after)
    return comparison
