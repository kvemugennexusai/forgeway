from fastapi import APIRouter, HTTPException

from app.data.loader import get_compute_target, load_compute_targets
from app.models import ComputeTarget

router = APIRouter(prefix="/api/infrastructure", tags=["infrastructure"])


@router.get("", response_model=list[ComputeTarget])
def list_compute_targets() -> list[ComputeTarget]:
    return load_compute_targets()


@router.get("/{target_id}", response_model=ComputeTarget)
def get_target(target_id: str) -> ComputeTarget:
    target = get_compute_target(target_id)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Unknown compute target '{target_id}'")
    return target
