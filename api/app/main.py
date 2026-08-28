"""Forgeway decision-engine API.

Fixture-driven demo backend. No real infrastructure integrations — every
compute target, workload and performance figure comes from
app/fixtures/*.json. The engine (app/engine/) is the single place that
decides anything; routers only translate HTTP <-> engine calls.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.data.loader import load_workloads
from app.engine.decision import run_decision
from app.models import ScenarioParams, ScenarioType
from app.routers import analyze, estate, infrastructure, recommendations, scenarios, workloads
from app.state import store


def _seed_baseline_recommendations() -> None:
    """Pre-compute a baseline recommendation for every workload flagged
    reanalyze=true, so the dashboard's Insight panel and a direct link to
    /recommendations/<id> work before anyone submits the analyzer form.

    Recorded as each workload's canonical baseline — the estate Insight
    panel always reads this, never whatever a user most recently computed
    via /analyze or a scenario, so exploring the app can't make the
    dashboard's opportunity disappear."""
    for workload in load_workloads():
        if not workload.reanalyze:
            continue
        record = run_decision(
            workload,
            record_id=store.next_id(),
            scenario=ScenarioParams(type=ScenarioType.normal, label="Normal — baseline, no scenario applied"),
            effective_min_throughput=workload.slo.min_throughput_tokens_per_s,
        )
        store.put(record)
        store.set_canonical(workload.id, record.id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _seed_baseline_recommendations()
    yield


app = FastAPI(
    title="Forgeway Decision Engine API",
    description="Feasibility, prediction, ranking and explanation for heterogeneous AI compute placement.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(infrastructure.router)
app.include_router(workloads.router)
app.include_router(analyze.router)
app.include_router(recommendations.router)
app.include_router(estate.router)
app.include_router(scenarios.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
