# Architecture: the Forgeway core, and how everything else uses it

Forgeway's long-term description is: **an open-source workload
intelligence layer for heterogeneous AI compute.** This doc describes the
boundary between that reusable core and the product built on top of it —
today, a FastAPI demo API, a CLI, and a Next.js UI — and the current status
of every piece README.md's quick start walks through.

## The boundary: core vs. product

**Core** (`api/app/core/`) is the part that should eventually be
lift-and-shiftable into its own open-source package, independent of this
repo's demo and CLI. It has one rule: **no filesystem, network, or
presentation concerns** — every function takes typed objects in and
returns typed objects out. It doesn't know a JSON fixture exists, doesn't
know about HTTP, and doesn't know this product has a dashboard or six
named demo scenarios.

**Product** (everything else under `api/app/`, plus all of `web/`) is this
specific demo and CLI: the fixture-backed data source, the six scenario
presets and their narrative, the estate dashboard aggregation, the
in-memory recommendation store, the HTTP routes, the discovery/benchmark
adapters, and the UI. It *consumes* the core — it never re-implements
feasibility, sizing, ranking, or evidence selection.

| Area | Status | Where |
|---|---|---|
| Compute target schema | done | `core/schemas/compute.py` |
| Workload schema | done | `core/schemas/workload.py` |
| Evidence schema | done | `core/schemas/evidence.py` (`Metric`, `Provenance`), `core/schemas/performance_evidence.py` (`PerformanceEvidence`) |
| Versioned `forgeway/v0.1` contracts | done | `core/schemas/v0_1/` — see [`docs/schemas.md`](schemas.md) |
| Compatibility/feasibility engine | done | `core/engine/feasibility.py` |
| Recommendation/scoring engine | partially core | `core/engine/scoring.py` (sizing + SLO gate), `core/engine/ranking.py` (normalize + weight), `core/engine/evidence_selection.py` (choosing which `PerformanceEvidence` to score against — see [`docs/decision-engine.md`](decision-engine.md)) are core; the surrounding orchestration — confidence gate, split fallback, evidence-for-UI, reasoning narrative — stays product-level in `app/engine/decision.py` (see below) |
| Hardware discovery adapters | one adapter shipped | `app/discovery/` — `NvidiaDiscoveryAdapter`, local NVIDIA GPUs only via `nvidia-smi`. See [`docs/discovery.md`](discovery.md) and [`docs/adding-an-accelerator.md`](adding-an-accelerator.md) for adding another. |
| Benchmark runner | one path shipped | `app/benchmark/` — `forgeway bench`, one path only: `vllm bench latency` on local NVIDIA GPUs. See [`docs/benchmarking.md`](benchmarking.md). |
| CLI | core commands shipped | `app/cli/` (installed via `api/pyproject.toml`'s console-script entry point): `forgeway discover`, `forgeway bench` / `forgeway runs`, and `forgeway analyze` — the last calls `app/engine/decision.py::run_decision()` directly, the same function every web route calls. |
| CLI-to-web bridge | done, browser-local | `/import` (`app/routers/imports.py`, `web/lib/imported-storage.ts`) validates a `forgeway discover`/`forgeway bench` result and makes it available to `/analyze` for that browser session — no server-side persistence. See [`docs/importing-results.md`](importing-results.md). |

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
      performance_evidence.py        PerformanceEvidence (forgeway/v0.1)
      v0_1/                          versioned schema re-exports +
                                     PlacementDecision — see docs/schemas.md
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
      evidence_selection.py          select_evidence() — comparability
                                     before provenance preference; see
                                     docs/decision-engine.md

  data/loader.py                 fixture-backed data source for this demo
                                  (app/fixtures/*.json — the seam a live
                                  inventory source would eventually replace)
  models.py                      product-specific schemas (Recommendation,
                                  the six-scenario types, estate/dashboard
                                  views, request DTOs) — re-exports every
                                  core schema too
  discovery/
    adapter.py                    DiscoveryAdapter ABC + DiscoveryError
    nvidia.py                      NvidiaDiscoveryAdapter (nvidia-smi only)
  benchmark/
    vllm_runner.py                 subprocess wrapper around
                                   `vllm bench latency`
    parser.py                      parses vLLM's --output-json shape
    gpu_sampler.py                 nvidia-smi polling during a run
    evidence.py                    build_performance_evidence() — combines
                                   the above into a real PerformanceEvidence,
                                   including the canonical metric-key
                                   aliases the engine's evidence selection
                                   requires (docs/decision-engine.md)
    store.py                       ~/.forgeway/benchmarks/*.json — the only
                                   on-disk state this project writes
  cli/main.py                    forgeway discover / bench / runs / analyze
  engine/
    decision.py                  orchestrator: wires core engine + this
                                  demo's data source, adds the confidence
                                  gate / greedy-split fallback, merges any
                                  imported targets/evidence for the caller
                                  of this one request, and builds the
                                  Recommendation's evidence + reasoning
    evidence_gateway.py            gathers every PerformanceEvidence
                                   candidate (fixture + locally saved
                                   forgeway bench runs + imported) for a
                                   (workload, target) pair and selects one
    scenarios.py                  the six named demo scenario presets
    estate.py                     dashboard aggregation
  routers/
    imports.py                    stateless ComputeTarget/PerformanceEvidence
                                   validation endpoints backing /import
    analyze.py, estate.py,        HTTP <-> engine glue; analyze.py also
    infrastructure.py,             merges + collision-checks imported
    recommendations.py,            targets/evidence before calling
    scenarios.py, workloads.py     run_decision()
  state.py, main.py              in-memory Recommendation store, app wiring

web/                              Next.js UI — an HTTP client over the
                                  same JSON API, plus browser-localStorage
                                  for imported targets/evidence
  lib/imported-storage.ts          the only client-side persistence layer
                                   in this codebase
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
`PlacementDecision` (`docs/schemas.md`) is a step toward that — a
vendor-neutral summary built from the same `CandidateEvaluation` list via
an additive `from_candidates()` converter — but `run_decision()` itself
still returns the product's own `Recommendation` shape; finishing the
split is the natural next step once there's a second caller that needs a
non-narrative answer and nothing else.

## What's deliberately not done

- **Discovery and benchmark results don't automatically feed the
  fixture catalog, the in-memory store, or the estate dashboard.**
  `forgeway discover` and `forgeway bench` produce real records; getting
  them into an actual placement decision requires either the CLI's
  `forgeway analyze` (which reads a locally discovered target and any
  locally saved benchmark run automatically) or the web UI's `/import`
  (manual upload, browser-local only — see `docs/importing-results.md`).
  There is no live-inventory mode where the dashboard reflects real,
  continuously-discovered hardware.
- **One vendor, one runtime, one benchmark shape.** NVIDIA-only discovery,
  `vllm bench latency`-only benchmarking. See `docs/adding-an-accelerator.md`
  for the seam a second vendor would extend, and `docs/benchmarking.md`
  for the benchmark runner's own scope limits.
- **No scheduler or orchestrator integration.** Forgeway recommends; it
  never places, migrates, or schedules anything on a real cluster. See
  `ROADMAP.md`.

## Import compatibility

`app/models.py` re-exports every type it used to define directly — e.g.
`ComputeTarget`, `Workload`, `Metric` — from `app.core.schemas`. Every
other file in the codebase (`state.py`, `routers/*.py`, `engine/estate.py`,
`engine/scenarios.py`) still does `from app.models import X` unchanged.

## Verification

- `cd api && source .venv/bin/activate && pytest tests/ -v` — see the
  test count in the repo's CI/test output; every change to `core/` or
  `engine/` is expected to keep the full suite green.
- `cd web && npm run build` — compiles clean; `next lint` and
  `tsc --noEmit` are also run as part of a normal change.
- `forgeway discover`, `forgeway bench`, `forgeway analyze` are exercised
  directly against the fixture catalog and (where hardware allows)
  real NVIDIA GPUs — see `docs/discovery.md` and `docs/benchmarking.md`
  for what's mocked-vs-real in their respective test suites.
