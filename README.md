# Forgeway

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-D22128?logo=apache&logoColor=white)](LICENSE)
[![Schema forgeway/v0.1](https://img.shields.io/badge/schema-forgeway%2Fv0.1-blue)](docs/schemas.md)
[![FastAPI](https://img.shields.io/badge/FastAPI-%3E%3D0.115-009688?logo=fastapi&logoColor=white)](api/requirements.txt)
[![Pydantic](https://img.shields.io/badge/Pydantic-%3E%3D2.9-E92063?logo=pydantic&logoColor=white)](api/requirements.txt)
[![Next.js](https://img.shields.io/badge/Next.js-15-black?logo=next.js&logoColor=white)](web/package.json)
[![React](https://img.shields.io/badge/React-19-149ECA?logo=react&logoColor=white)](web/package.json)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)](web/package.json)
[![Last commit](https://img.shields.io/github/last-commit/kvemugennexusai/forgeway)](https://github.com/kvemugennexusai/forgeway/commits/main)

Forgeway is the decision layer for heterogeneous AI infrastructure. Given a workload, its
service-level objective, enterprise policy, the available compute targets, predicted or
measured performance, and capacity/economics, Forgeway determines which targets are
**feasible**, predicts the outcome on each, **ranks** them, **recommends** a placement, and
**explains why** — including what loses and why, and how the recommendation changes under a
demand spike or a capacity loss.

This is a product demo, not an orchestration platform: it does not schedule Kubernetes
workloads or migrate anything. Every compute target, workload, and performance figure is a
JSON fixture. There are no real infrastructure integrations.

> A fresh, independent build — not a fork or port of any prior project. New repo, own history.

---

## Architecture

Two independently-run pieces, talking over a plain JSON HTTP API:

```
api/    FastAPI decision engine (Python)      → the ONLY place anything is decided
web/    Next.js control-plane UI (TypeScript)  → renders engine output, triggers analysis
```

**One decision engine, every caller.** `api/app/engine/decision.py` is the single function
that turns a workload + scenario into a `Recommendation`. The `/analyze` route, the estate
Insight panel (seeded at startup), and every scenario preset all call it — none of them
re-implement scoring. This mirrors the project convention that a placement brain must never
fork: the dashboard, the analyzer, and "what if" scenarios must always agree, because they are
the same code path.

### Backend (`api/`)

```
app/core/                  reusable, product-agnostic core — no filesystem/HTTP access anywhere
  schemas/                  ComputeTarget, Workload, Metric/Provenance (evidence), and the
                            engine's output contracts (FeasibilityCheck, Prediction,
                            CandidateEvaluation, ...)
  engine/
    feasibility.py           step 3: the hard compatibility checks (policy, memory, precision,
                             workload-class, status) — every check runs and is reported, not
                             just the first failure
    scoring.py                steps 5-6: retrieves the prediction for a feasible target, sizes
                             it to the workload's required throughput (capacity- and
                             budget-aware), and checks it against the SLO — a hard reject, never
                             a weighted preference
    ranking.py                 steps 7-8: normalizes cost/performance/headroom across the
                             qualifying candidates and applies the workload's objective weights
app/models.py               Pydantic contracts — the only shapes that cross the API boundary
                             (re-exports every app/core/schemas type, plus this product's own:
                             Recommendation, the six-scenario types, estate/dashboard views)
app/fixtures/*.json        compute targets, workloads, and per-(workload,target) performance profiles
app/data/loader.py         reads the fixtures into typed objects (the only filesystem access;
                            the seam a future discovery adapter / benchmark runner replaces)
app/engine/
  decision.py                steps 9-11 plus orchestration: wires the core engine above to this
                            demo's fixture data, applies the confidence gate, falls back to a
                            greedy split across whatever still clears the confidence bar when no
                            single target clears both gates alone (withholds a recommendation
                            entirely if nothing does), and builds the Recommendation's
                            evidence/reasoning narrative
  scenarios.py                the six named scenario presets (below) — each a pure function of
                            the workload's own baseline — plus run_scenario(), which computes a
                            fresh BEFORE, applies one preset for AFTER, and builds the
                            change_explanation the frontend renders
  estate.py                     aggregate fleet stats + Insight cards, read from already-computed records
app/state.py                in-memory Recommendation store (no database — this is a fixture demo)
app/routers/                 HTTP <-> engine translation only; no logic lives here
tests/test_engine.py        unit tests: hard-constraint rejections in isolation, plus
                             objective-weight / confidence-threshold / demand-spike behavior
                             against the real fixtures
tests/test_scenarios.py     unit tests: the six presets' exact parameter values, that they
                             never mutate fixture state, and the BEFORE/AFTER/explanation shape
```

> Forgeway's long-term goal is to describe this core as an open-source
> workload intelligence layer for heterogeneous AI compute, reusable outside
> this demo. See [`docs/open-source-architecture.md`](docs/open-source-architecture.md)
> for the public-vs-product boundary this split establishes.

**The decision pipeline, in order:** load workload → load compute targets → evaluate hard
compatibility (`feasibility.py`) → collect explicit rejection reasons for anything that fails
→ for feasible targets, retrieve the prediction fixture (`scoring.retrieve_prediction`) → check
it against the SLO, a hard reject (`scoring.score_candidate`) → normalize cost/performance/
headroom to [0, 1] across the survivors → apply the workload's `ObjectiveWeights` → apply the
`min_confidence_pct` requirement → rank by weighted score → return the top-ranked target as a
`Recommendation` with full reasoning. **Hard constraints (compatibility, SLO) reject a
candidate outright and are never folded into the weighted score** — objective weights only ever
choose among candidates that already cleared both gates. No LLM and no machine learning
anywhere in this path: every step is a deterministic, unit-testable function over typed data.

**Every metric carries its own confidence, provenance, and range.** `Metric` (`value`,
`confidence`, `provenance`, `range_low`/`range_high` when known, `source`) is the one shape
every number in the engine is reported through — target pricing, predicted latency, predicted
throughput. A candidate's overall confidence is the weakest-link minimum across its metrics
(`Prediction.confidence_pct`); a workload's `min_confidence_pct` gates which candidates are
even eligible to be ranked, so raising the bar can change the recommendation even when nothing
else about the workload changes. A not-yet-adopted target's throughput comes from a performance
model and is always labeled `MODELED` — the engine has no code path that can present a modeled
number as measured. `tests/test_engine.py::test_modeled_evidence_never_labeled_measured` guards
this.

**Enterprise policy is a real constraint, not a label.** Each workload carries an
`allowed_vendors` / `allowed_regions` / `budget_ceiling_per_hr` `EnterprisePolicy`. Sizing a
candidate (`scoring.size_replicas`) caps replicas at whichever binds first — free capacity or
the budget ceiling — and reports which one did. The demand-spike scenario is deliberately tuned
so *capacity*, not budget, is what forces a split placement across two targets.

**Scenarios recompute, they don't re-theme — and they never mutate persistent state.** Each of
the six presets in `app/engine/scenarios.py` is a pure function of the workload's *own current
baseline* (never of whatever recommendation a user happens to be looking at), so calling the
same scenario twice always produces the same result:

| Scenario | Effect |
|---|---|
| `normal` | No override — the baseline itself. |
| `demand_spike` | Required throughput: 20 → 70 requests/sec (3.5x), via each workload's `tokens_per_request`. |
| `h100_capacity_loss` | H100's free capacity cut by 50%, via a temporary `capacity_overrides` map — the fixture is never written to. |
| `cost_priority` | Cost weight → 70%; the other two axes shrink proportionally, keeping their relative priority. |
| `performance_priority` | Performance (P99 latency) weight → 70%, same proportional redistribution. |
| `strict_confidence_policy` | `min_confidence_pct` → 95%. |

`run_scenario()` computes a fresh baseline as **BEFORE**, applies the preset for **AFTER** (both
independently stored `Recommendation`s, both fully re-derived — nothing here is hardcoded or
copied from a prior run), and builds `change_explanation` by diffing the two: which target won
each side, and — by inspecting the *other* side's candidate list — exactly which gate (SLO,
confidence, or a lower weighted score) is why. `demand_spike` also computes an
`unmitigated_projection` — what P99 would look like if the *prior* recommendation's replica
count were held fixed against the new demand (a simplified queueing degradation model,
explicitly labeled `MODELED`).

The split fallback respects the confidence gate too: under `strict_confidence_policy`, neither
H100 (92%) nor MI300X (78%) clears 95%, and splitting traffic across two candidates nobody
trusts enough isn't a fix — so the engine withholds a recommendation rather than quietly
blending them (`tests/test_scenarios.py::test_strict_confidence_policy_withholds_recommendation_rather_than_split_unconfidently`).

### Frontend (`web/`)

Next.js App Router, TypeScript, Tailwind, hand-added shadcn-style primitives
(`components/ui/*`), Recharts. `lib/types.ts` mirrors `api/app/models.py` by hand — keep them
in sync when either changes. `lib/api.ts` is the only place that calls the backend.

```
app/
  page.tsx                        /               executive estate dashboard + Insight panel
  infrastructure/page.tsx         /infrastructure  compute target inventory + compatibility detail
  analyze/page.tsx                /analyze         workload analyzer (template picker → run analysis)
  recommendations/[id]/page.tsx   /recommendations/[id]   recommendation detail + scenario simulation
  workloads/page.tsx              /workloads       active workload inventory
components/
  recommendations/                summary, split-allocation panel, candidate comparison table,
                                   evidence panel, and recommendation-workspace.tsx — the client
                                   component that owns the scenario picker and swaps in the
                                   comparison view, all rendering Recommendation/ScenarioComparison
                                   exactly as the API returns them
  scenarios/                      state-snapshot-card.tsx (the compact BEFORE/AFTER card) and
                                   scenario-comparison-view.tsx (EVENT banner + BEFORE → AFTER +
                                   the change-explanation callout + full AFTER detail)
  infrastructure/                 client-side inventory table + detail panel
  charts/                         Recharts wrappers (vendor utilization)
  ui/                              button, card, badge, table, tabs, progress, separator, alert
```

Server components fetch from the API on every request (`cache: "no-store"` in `lib/api.ts`) —
there is no client-side data layer to keep in sync. The scenario catalog (`GET /api/scenarios`)
and every scenario's outcome (`POST /api/workloads/{id}/scenario`) come entirely from the API —
the frontend hardcodes no scenario parameter and no recommendation; it only renders what the
response contains. Applying a scenario doesn't navigate away: `RecommendationWorkspace` holds
the returned `ScenarioComparison` in state and swaps the whole page body for the BEFORE/EVENT/
AFTER view, with a **Reset** to return to the plain recommendation. The AFTER record is still
independently stored server-side, so "View this recommendation as its own page" is a real,
shareable, permanent link like any other.

---

## Running the demo

Two terminals.

**Backend** (from `api/`):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend** (from `web/`):

```bash
npm install
npm run dev
```

Open `http://localhost:3000`. `web/.env` already points `NEXT_PUBLIC_API_BASE_URL` at
`http://localhost:8000`.

Run the engine tests:

```bash
cd api && source .venv/bin/activate && pytest tests/ -v
```

### The demo flow

1. **`/`** — the estate dashboard. Read the KPI row, then the Forgeway Insight card: the
   engine has already flagged that `llama-3.1-70b-chat` is cheaper on AMD MI300X than its
   current H100 placement (seeded at API startup, so this is live on first load).
2. **`/infrastructure`** — the seven compute targets. Click Gaudi 3 or Trainium2 to see a hard
   compatibility rejection that's a *software* limitation, not a hardware one.
3. **`/analyze`** — the Llama 3.1 70B realtime-inference template is preselected. Click **Run
   analysis**.
4. **`/recommendations/[id]`** — MI300X is recommended over the current H100 placement, with
   confidence and full evidence provenance. Expand any candidate row for its complete
   feasibility checklist — including *why* L40S, Gaudi 3, Trainium2, Jetson Thor, and the local
   lab system are each infeasible, for different reasons.
5. In the **Scenario simulation** card, click **Demand Spike**. The page swaps to a BEFORE /
   EVENT / AFTER view: MI300X alone (before) can't hold the SLO at 70 req/s, the engine projects
   what happens if you don't react, and recommends a 40/60 split across MI300X and H100
   (after) — with an explicit callout explaining why the recommendation changed.
6. Click **Reset**, then try **Strict Confidence Policy**. Neither candidate reaches 95%
   confidence, so the engine withholds a recommendation rather than presenting one below the
   bar — same BEFORE/AFTER shape, an honest "no recommendation" AFTER state.
7. Try **Cost Priority** or **Performance Priority** — MI300X already leads on both cost and
   latency, so the ranking doesn't flip, but the callout still shows the weighted score moving
   in response, proving the mechanism engaged even where the winner didn't change.
8. **`/workloads`** — the other four workloads for estate context; the AMD MI300X, L40S,
   Trainium2, and Jetson Thor placements each show why they're already correctly placed.

---

## What's implemented vs. not

**Implemented:** the full feasibility → prediction → SLO check → normalize → weight →
confidence-gate → rank → recommend → explain pipeline; every metric (value, confidence,
provenance, range when available); policy (vendor/region/budget) as a real constraint;
per-workload `ObjectiveWeights` and `min_confidence_pct` that can change the ranking or the
recommendation outright; capacity-aware split placement that itself respects the confidence
gate; six named scenario presets, each backend-owned and mutation-free, with a BEFORE/EVENT/
AFTER comparison and an explicit change explanation; every route in the product spec,
fixture-driven.

**Not implemented (by design, this build):** any real infrastructure integration — no cloud
API calls, no live telemetry, no Kubernetes. No persistence beyond an in-memory store (restart
the API and every simulated recommendation is gone; the baseline Insight reseeds). No custom
workload authoring in `/analyze` — only the fixture workload library. No LLM in the decision
path — the deterministic engine decides; nothing here calls a model to place a workload.

---

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).
