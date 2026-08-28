from fastapi import APIRouter, HTTPException

from app.models import Recommendation
from app.state import store

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.get("/{record_id}", response_model=Recommendation)
def get_recommendation(record_id: str) -> Recommendation:
    record = store.get(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Unknown recommendation '{record_id}'")
    return record
