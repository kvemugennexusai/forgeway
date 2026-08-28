from fastapi import APIRouter

from app.engine.estate import compute_estate_summary
from app.models import EstateSummary
from app.state import store

router = APIRouter(prefix="/api/estate", tags=["estate"])


@router.get("/summary", response_model=EstateSummary)
def get_estate_summary() -> EstateSummary:
    return compute_estate_summary(store)
