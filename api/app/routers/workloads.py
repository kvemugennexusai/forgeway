from fastapi import APIRouter, HTTPException

from app.data.loader import get_workload, load_workloads
from app.models import Workload, WorkloadListItem
from app.state import store

router = APIRouter(prefix="/api/workloads", tags=["workloads"])


@router.get("", response_model=list[WorkloadListItem])
def list_workloads() -> list[WorkloadListItem]:
    items = []
    for w in load_workloads():
        record = store.latest_for_workload(w.id)
        slo_status = (
            "met" if w.current_placement.measured_p99_latency_ms <= w.slo.p99_latency_ms else "violated"
        )
        items.append(
            WorkloadListItem(
                workload=w,
                slo_status=slo_status,
                latest_recommendation_id=record.id if record else None,
            )
        )
    return items


@router.get("/{workload_id}", response_model=Workload)
def get_workload_detail(workload_id: str) -> Workload:
    workload = get_workload(workload_id)
    if workload is None:
        raise HTTPException(status_code=404, detail=f"Unknown workload '{workload_id}'")
    return workload
