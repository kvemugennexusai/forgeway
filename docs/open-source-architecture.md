# Open-source architecture: the Forgeway core

Forgeway's long-term description is: **an open-source workload intelligence
layer for heterogeneous AI compute.** This note records the first,
incremental step toward that — separating the reusable decision-making core
from this repo's specific product (the FastAPI demo API + Next.js UI) —
and where the remaining boundary work still needs to happen.

This is a refactor of internal module boundaries only. No API route, JSON
shape, fixture, or frontend behavior changed. All 29 backend tests and the
frontend build pass unchanged; see "Verification" below.

## The boundary: core vs. product

**Core** (`api/app/core/`) is the part that should eventually be
lift-and-shiftable into its own open-source package, independent of this
demo. It has one rule: **no filesystem, network, or presentation
concerns** — every function takes typed objects in and returns typed
objects out. It doesn't know a JSON fixture exists, doesn't know about HTTP,
and doesn't know this product has a dashboard or six named demo scenarios.

**Product** (everything else under `api/app/`, plus all of `web/`) is this
specific demo: the fixture-backed data source, the six scenario presets and
their narrative, the estate dashboard aggregation, the in-memory
recommendation store, the HTTP routes, and the UI. It *consumes* the core —
it never re-implements feasibility, sizing, or ranking.

| Goal item | Status | Where |
|---|---|---|
| 1. Compute target schema | ✅ moved | `core/schemas/compute.py` |
| 2. Workload schema | ✅ moved | `core/schemas/workload.py` |
| 3. Evidence schema | ✅ moved | `core/schemas/evidence.py` (`Metric`, `Provenance`) |
| 4. Compatibility/feasibility engine | ✅ moved | `core/engine/feasibility.py` |
| 5. Recommendation/scoring engine | ⚠️ partially moved | `core/engine/scoring.py` (sizing + SLO gate) and `core/engine/ranking.py` (normalize + weight) are core; the surrounding orchestration — confidence gate, split fallback, evidence-for-UI, reasoning narrative — stays product-level in `app/engine/decision.py` (see below) |
| 6. Hardware discovery adapters | ✅ first adapter shipped | `app/discovery/` — `NvidiaDiscoveryAdapter`, local NVIDIA GPUs only via `nvidia-smi`. See [`docs/discovery.md`](discovery.md). Not yet wired into `app/data/loader.py` or the web UI — it's reachable only via the CLI below. |
| 7. Benchmark runner | 📋 not started | no code exists yet; `app/data/loader.py` is the seam |
| 8. CLI | ✅ first command shipped | `app/cli/` — `forgeway discover` (installed via `api/pyproject.toml`'s console-script entry point). One subcommand only; see docs/discovery.md. |

## Directory layout

```
api/app/
  core/                          # reusable — no IO, no product concerns
    schemas/
      evidence.py                  Metric, Provenance
      compute.py                    ComputeTarget, UnsupportedWorkloadClass
      workload.py                    Workload, SLO, EnterprisePolicy,
                                     ObjectiveWeights, CurrentPlacement,
                                     PerformanceProfile
      engine.py                      FeasibilityCheck, Prediction,
                                     PredictedOutcome, NormalizedScores,
                                     CandidateEvaluation
    engine/
      feasibility.py                evaluate_feasibility() — hard
                                     compatibility checks (policy, memory,
                                     precision, workload-class, status)
      scoring.py                     retrieve_prediction(), size_replicas(),
                                     score_candidate() — prediction lookup,
                                     replica sizing, SLO gate
      ranking.py                     normalize_and_weight() — min-max
                                     normalization + objective-weight blend
                                     across a qualifying candidate set

  data/loader.py                 fixture-backed data source for this demo
                                  (the seam a discovery adapter / benchmark
                                  runner would eventually replace)
  models.py                      product-specific schemas (Recommendation,
                                  the six-scenario types, estate/dashboard
                                  views, request DTOs) — re-exports every
                                  core schema too, so existing
                                  `from app.models import X` imports are
                                  untouched
  engine/
    decision.py                  orchestrator: wires core engine + this
                                  demo's data source, adds the confidence
                                  gate / greedy-split fallback, and builds
                                  the Recommendation's evidence + reasoning
    scenarios.py                  the six named demo scenario presets
    estate.py                     dashboard aggregation
  state.py, main.py, routers/    HTTP <-> engine glue, in-memory store

web/                              unchanged — still just an HTTP client
                                  over the same JSON API
```

## Why `decision.py` isn't fully in `core/` yet

`run_decision()` currently does two jobs at once: run the core pipeline
(feasibility → prediction → SLO gate → normalize/weight/rank), and build
this product's `Recommendation` — human-readable `reasoning` strings,
`Evidence` rows for the UI panel, and the `demand_spike` scenario's
`unmitigated_projection` narrative. Those two jobs don't split cleanly
without introducing a new core-level "ranked decision" return type distinct
from `Recommendation`, which is a real design decision (what does a
headless caller get back instead of prose?) rather than a mechanical move.
Pulling `feasibility`, `scoring`, and the pure `normalize_and_weight` step
out now — the part with no ambiguity — was the right-sized change for this
pass; finishing the split is the natural next step once there's a second
caller (a CLI, a different UI) that needs a non-narrative answer.

## What's deliberately not done

A benchmark runner (goal item 7) still has no implementation — `app/data/
loader.py` still only reads `app/fixtures/*.json`, and remains the seam a
real benchmark runner (producing measured `PerformanceProfile` rows instead
of fixture ones) would plug into without changing a line of `core/`.

Hardware discovery (item 6) now has a first real adapter
(`app/discovery/`, NVIDIA-only — see `docs/discovery.md`) and a CLI (item
8, `app/cli/`, one command: `forgeway discover`) — but discovery is
deliberately **not** wired into `app/data/loader.py`, `app/state.py`, or
the web UI yet. `forgeway discover` today only prints/emits a
`ComputeTarget`; it doesn't feed it into a running decision or the
estate dashboard. That integration is the natural next step once there's
a concrete need for it (e.g. seeding the fixture set from real hardware,
or a live-inventory mode for `/infrastructure`).

## Import compatibility

`app/models.py` re-exports every type it used to define directly — e.g.
`ComputeTarget`, `Workload`, `Metric` — from `app.core.schemas`. Every other
file in the codebase (`state.py`, `routers/*.py`, `engine/estate.py`,
`engine/scenarios.py`) still does `from app.models import X` unchanged. Only
three files needed an import-path update, because they reached directly
into the modules that moved: `engine/decision.py` and
`tests/test_engine.py` (now import `evaluate_feasibility` / `score_candidate`
from `app.core.engine.*`), plus `decision.py`'s new
`app.core.engine.ranking.normalize_and_weight` import.

## Verification

- `cd api && source .venv/bin/activate && pytest tests/ -v` — 29/29 pass,
  unchanged from before the refactor.
- `cd web && npm run build` — compiles clean, same route/bundle output.
- Manual smoke test via `TestClient` against every route
  (`/api/health`, `/api/estate/summary`, `/api/infrastructure`,
  `/api/workloads`, `/api/analyze`, `/api/scenarios`,
  `/api/workloads/{id}/scenario`) confirms identical behavior — same
  recommended target (`amd-mi300x`), same demand-spike split, same
  scenario catalog.
