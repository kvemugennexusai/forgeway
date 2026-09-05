# Forgeway

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-D22128?logo=apache&logoColor=white)](LICENSE)
[![Schema forgeway/v0.1](https://img.shields.io/badge/schema-forgeway%2Fv0.1-blue)](docs/schemas.md)
[![FastAPI](https://img.shields.io/badge/FastAPI-%3E%3D0.115-009688?logo=fastapi&logoColor=white)](api/pyproject.toml)
[![Pydantic](https://img.shields.io/badge/Pydantic-%3E%3D2.9-E92063?logo=pydantic&logoColor=white)](api/pyproject.toml)
[![Next.js](https://img.shields.io/badge/Next.js-15-black?logo=next.js&logoColor=white)](web/package.json)
[![React](https://img.shields.io/badge/React-19-149ECA?logo=react&logoColor=white)](web/package.json)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)](web/package.json)
[![Last commit](https://img.shields.io/github/last-commit/kvemugennexusai/forgeway)](https://github.com/kvemugennexusai/forgeway/commits/main)

**Forgeway is an open-source workload intelligence layer for heterogeneous AI compute.** It
evaluates workload requirements, compute capabilities, performance evidence, SLOs, and policy
to determine where AI workloads should run — which targets are **feasible**, what the predicted
outcome on each is, how they **rank**, which one it **recommends**, and **why** — including what
loses and why, and how the recommendation changes under a demand spike or a capacity loss.

> A fresh, independent build — not a fork or port of any prior project. New repo, own history.

### Why it exists

Placing an AI workload — which GPU, which region, which vendor — is usually a spreadsheet, a
gut call, or whoever's on-call that week. Forgeway makes that decision an explicit, typed,
re-runnable function: the same inputs always produce the same recommendation, every number
carries its own confidence and provenance (measured vs. published vs. modeled), and the engine
will tell you honestly when it doesn't have enough evidence to recommend anything, rather than
guessing.

### What can I run today?

- **The CLI**, on any machine: `forgeway discover` (real local NVIDIA hardware, if present),
  `forgeway bench` (a real vLLM benchmark, if you have a CUDA GPU), and `forgeway analyze` (the
  real decision engine, against this repo's fixture workloads or your own YAML) — see
  **Quick start** below.
- **The web demo**: a fixture-driven dashboard, workload analyzer, and scenario simulator, plus
  `/import` — upload a real `forgeway discover`/`forgeway bench` result and let the same engine
  score it alongside the fixture catalog. See "Running the demo" below.

### What hardware is supported today?

**Local NVIDIA CUDA-capable GPUs** (via `nvidia-smi`) **and local AMD ROCm-capable GPUs** (via
`rocm-smi`), for both discovery ([`docs/discovery.md`](docs/discovery.md)) and benchmarking
([`docs/benchmarking.md`](docs/benchmarking.md)) — `vllm bench latency` runs identically on
either vendor, with only GPU telemetry sampling (`nvidia-smi` vs. `rocm-smi`) actually
vendor-specific. No Intel or cloud-vendor discovery yet.

**Precise verification status of the AMD/ROCm side** (this is the one place in this README it's
stated — see [`docs/discovery.md`](docs/discovery.md#verification-status) for the full detail,
the five states used, and why they're worth being this exact about):

- ROCm hardware discovery, including architecture resolution: **LIVE VERIFIED**, and its test
  suite is **TESTED WITH CAPTURED REAL OUTPUT** — run against a real AMD Radeon RX 9070 XT over
  SSH via the actual `forgeway discover` CLI.
- The ROCm GPU telemetry sampler (`rocm_gpu_sampler.sample_gpu_once()`) and the
  `run_vllm_bench_latency(gpu_vendor="amd")` dispatch path it's called through — the same
  code `forgeway bench` itself calls — are now **LIVE VERIFIED**: a real `vllm bench latency`
  run completed on a real AMD Radeon RX 9070 XT (inside AMD's official `rocm/vllm` Docker
  image) via `forgeway bench-profile`, capturing a real `peak_gpu_memory_used_mb` reading
  (15,529.70 MB) alongside real latency/throughput metrics — see
  [`docs/cross-vendor-validation.md`](docs/cross-vendor-validation.md). The one thing not
  literally exercised is the plain `forgeway bench` CLI entrypoint itself — a thin wrapper
  around the exact same now-proven functions, invoked via `forgeway bench-profile` instead in
  this run — so this is as close to fully verified as this distinction allows.
- Getting a working ROCm vLLM install remains **materially heavier than NVIDIA's `pip install
  vllm`** (see [`docs/benchmarking.md`](docs/benchmarking.md#dependencies)) — the live run
  above used AMD's official `rocm/vllm` Docker image specifically because of that gap, not a
  plain host install.

See [`ROADMAP.md`](ROADMAP.md) and [`docs/adding-an-accelerator.md`](docs/adding-an-accelerator.md)
for how a new vendor gets added. The decision engine itself is hardware-agnostic — it scores
whatever `ComputeTarget`s it's given, real or fixture — the discovery/benchmark *adapters* are
what's vendor-specific.

### What is experimental / simulated?

- **The web demo's dashboard and five sample workloads are fixture data**, not live
  infrastructure — every compute target, workload, and baseline performance figure in the demo
  ships as a JSON fixture (`api/app/fixtures/`), clearly labeled with its own provenance
  (`MEASURED` / `PUBLISHED` / `MODELED`). There are no real cloud/infrastructure integrations —
  Forgeway does not schedule, provision, or migrate anything.
- **Discovery and benchmarking cover two vendors (NVIDIA, AMD), one benchmark path**
  (`vllm bench latency`). Real output, limited scope — see the docs linked above for exactly
  what's measured vs. estimated. Notably, that one benchmark path is **offline latency only**: it
  does not measure time-to-first-token or true concurrent-request serving throughput — the two
  numbers that matter most for a `realtime-inference` SLO, which is exactly the workload class
  this demo's flagship recommendation is about. See
  [`docs/benchmarking.md`](docs/benchmarking.md#why-vllm-bench-latency-and-what-it-does-and-doesnt-measure)
  before treating a `forgeway bench` number as representative of production serving latency.
- **AMD/ROCm support is now live-verified end to end** (discovery, GPU telemetry sampling, and
  a real `vllm bench latency` run all completed on real AMD hardware) — see "What hardware is
  supported today?" above for the precise breakdown and the one remaining thin gap (the plain
  `forgeway bench` CLI entrypoint itself vs. the equivalent, already-proven `bench-profile`
  path). Stated once above, not repeated here.
- **Steps that require real NVIDIA hardware can't be verified on most machines.** `forgeway
  discover`, `forgeway bench`, and the "hardware found" half of `forgeway analyze` all fail
  cleanly (not silently) without an NVIDIA GPU — which is most contributors' and evaluators'
  machines. `forgeway analyze` against the fixture catalog, and every web demo feature except
  actually running `forgeway discover`/`forgeway bench` yourself, work on any machine.
- **Scenario simulation** (demand spike, capacity loss, policy changes) recomputes the real
  engine against a hypothetical input — it's a real re-run, not a live projection from telemetry.
- **`/import`** stores uploaded hardware/evidence in browser `localStorage` only — no server-side
  persistence, no accounts, nothing shared across devices.
- **No LLM or machine learning anywhere in the decision path** — every step (feasibility,
  scoring, ranking) is a deterministic, unit-tested function over typed data.

See "What's implemented vs. not" further down for the complete list.

---

## Quick start

Requires Python 3.10+. From the repo root:

```bash
# 1. install
cd api
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt        # registers the `forgeway` console script

# 2. discover — real local NVIDIA hardware, if present (cleanly reports "none found" otherwise)
forgeway discover

# 3. bench — a real vLLM benchmark (requires a CUDA GPU + vLLM installed; see docs/benchmarking.md)
forgeway bench --model meta-llama/Llama-3.1-8B-Instruct --input-tokens 512 --output-tokens 128

# 4. analyze — the real decision engine against a workload (works on any machine, no GPU required)
forgeway analyze examples/workload.yaml
```

Steps 1 and 4 work on any machine with no GPU. Step 2 works on any machine but only finds
hardware on one with an NVIDIA GPU and driver installed. Step 3 needs a CUDA GPU and vLLM. See
"CLI: hardware discovery", "CLI: benchmarking", and "CLI: placement analysis" below for the full
detail on each, and "End-to-end: CLI benchmark → web import → analyze" for how all four (plus the
web UI) connect.

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
> this demo. See [`docs/architecture.md`](docs/architecture.md)
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
  import/page.tsx                 /import          upload + validate a real ComputeTarget/PerformanceEvidence pair
components/
  recommendations/                summary, split-allocation panel, candidate comparison table,
                                   evidence panel, and recommendation-workspace.tsx — the client
                                   component that owns the scenario picker and swaps in the
                                   comparison view, all rendering Recommendation/ScenarioComparison
                                   exactly as the API returns them
  import/                         import-panel.tsx — upload dropzones, validation-error display,
                                   and the "your measured compute" list, backed by
                                   lib/imported-storage.ts (browser localStorage only)
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
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
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

### Testing from another device on your LAN

By default the backend only binds to `127.0.0.1` and the frontend points at `localhost` — neither
is reachable from another device. To test from a phone, tablet, or another computer on the same
network as the host:

```bash
# find the host's LAN IP first, e.g. on macOS:
ipconfig getifaddr en0

# backend — bind to all interfaces, not just 127.0.0.1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# frontend — point at the host's LAN IP instead of localhost (gitignored, won't affect anyone else)
echo "NEXT_PUBLIC_API_BASE_URL=http://<host-LAN-IP>:8000" > web/.env.local
cd web && npm run dev
```

`npm run dev` prints a `Network:` URL — open that (not `localhost`) on the other devices. CORS
already allows private-LAN origins (`192.168.x.x`, `10.x.x.x`, `172.16-31.x.x`, any port,
alongside `localhost`) as well as `http`-only, never a public/internet-routable origin — see
`api/app/main.py`'s `CORSMiddleware` config and `api/tests/test_cors.py`.

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

## CLI: hardware discovery

`forgeway discover` detects local NVIDIA CUDA hardware (via `nvidia-smi`) or local AMD ROCm
hardware (via `rocm-smi`, tried if NVIDIA's tooling isn't found) and prints it as a
`ComputeTarget` — the same schema the demo fixtures use, human-readable by default or as JSON
with `--json`. Independent of the web demo above; see [`docs/discovery.md`](docs/discovery.md).
Already available after the backend setup above (`pip install -r requirements.txt` registers the
`forgeway` console script):

```bash
cd api && source .venv/bin/activate
forgeway discover
```

## CLI: benchmarking

`forgeway bench` runs one LLM inference benchmark — `vllm bench latency`, prioritizing
`meta-llama/Llama-3.1-8B-Instruct` — on the local NVIDIA or AMD GPU `forgeway discover` finds, and
normalizes the real, measured result into a `PerformanceEvidence` record (saved locally;
`forgeway runs` lists past runs). Requires vLLM (a CUDA build for NVIDIA; a ROCm build — more
involved to install — for AMD) and a matching GPU, separately from the setup above; see
[`docs/benchmarking.md`](docs/benchmarking.md) for dependencies, limitations, and reproducibility
caveats.

```bash
forgeway bench --model meta-llama/Llama-3.1-8B-Instruct --input-tokens 512 --output-tokens 128 --concurrency 1
```

The saved evidence's `workload_id` defaults to `--model` — never a real Forgeway workload id, so
never selectable by the placement engine for any workload (see below), but also never colliding
with one. Pass `--workload-id <id>` to tag it with a real workload id instead, **only when
`--model` actually corresponds to that workload** (same family/parameter count) — see
[`docs/importing-results.md`](docs/importing-results.md#tagging-evidence-with-a-real-workload-id).

### Cross-vendor benchmark profiles

`forgeway bench-profile <profile.yaml>` runs a versioned, fully-specified `BenchmarkProfile` —
e.g. [`benchmarks/profiles/llama-8b-cross-vendor-v0.1.yaml`](benchmarks/profiles/llama-8b-cross-vendor-v0.1.yaml)
— so the *same* configuration (model, precision, tensor parallelism, token counts, concurrency)
can be run on an NVIDIA machine and an AMD machine without silently varying between them.
`forgeway compare-runs <a.json> <b.json>` then checks whether two such runs are honestly
comparable (`DIRECTLY COMPARABLE` / `PARTIALLY COMPARABLE` / `NOT COMPARABLE`, with explicit
reasons) and shows them side by side — it never declares a cost or performance "winner"; that
requires workload SLOs and objective weights, which is `forgeway analyze`'s job. See
[`docs/benchmarking.md`](docs/benchmarking.md#cross-vendor-benchmark-profiles) and
[`docs/cross-vendor-validation.md`](docs/cross-vendor-validation.md) for the full detail.

**Precise status: LIVE VERIFIED.** `forgeway bench-profile` ran for real on both a real NVIDIA
DGX Spark and a real AMD Radeon RX 9070 XT against the identical profile, and `forgeway
compare-runs` correctly classified the pair `PARTIALLY COMPARABLE` (every critical dimension —
model, precision, quantization, tokens, concurrency, tensor parallelism — matched exactly; only
soft dimensions — vLLM patch version, driver version — differed, as expected across two
independently-built vendor Docker images). Every piece — profile validation, the comparability
policy, both vendors' runner classes — is also covered by unit/integration tests using mocked
subprocess output; the decision-engine ranking behavior specifically is proven via synthetic
evidence (`api/tests/test_decision_cross_vendor.py`), not by rerunning `forgeway analyze` on
these two live files. It is accurate to say **"Forgeway has been live-validated running the same
benchmark profile on NVIDIA and AMD hardware."** The model actually used for this proof was
`Qwen/Qwen2.5-1.5B-Instruct`, not the primary Llama 3.1 8B profile (gated, no HF credentials on
either test machine) or even the first open-model substitute, Qwen2.5 7B (its bf16 weights alone
didn't fit the AMD card's 16 GB VRAM) — see
[`docs/cross-vendor-validation.md`](docs/cross-vendor-validation.md) for that whole story, the
exact commands and output, and every real bug the live run surfaced and fixed along the way.

## CLI: placement analysis

`forgeway analyze` runs **the exact same decision engine the web app uses**
(`app/engine/decision.py::run_decision` — steps 1-11, unchanged: evaluate hard compatibility,
reject infeasible targets, evaluate SLOs, score feasible targets, rank them, explain the
recommendation) against a workload defined in a YAML file, and returns a vendor-neutral
`PlacementDecision` (`docs/schemas.md`). See [`docs/decision-engine.md`](docs/decision-engine.md)
for how evidence selection works; nothing about it changes when the caller is the CLI instead of
an HTTP request — that's the whole point.

```bash
forgeway analyze examples/workload.yaml
forgeway analyze examples/workload.yaml --json                          # full PlacementDecision JSON
forgeway analyze examples/workload.yaml --policy examples/policy.yaml   # override its enterprise policy
```

`examples/workload.yaml` is the demo's own flagship `wl-llama70b-rt` fixture, not a fabricated
example — comparing its output to the web app's own `/analyze` page for the same workload is a
direct, literal proof the CLI and the web UI never diverge into separate placement logic.
`examples/policy.yaml` is a stricter policy (NVIDIA-only, single-region) that flips the
recommendation from AMD's MI300X to NVIDIA's H100 — see the file's own comments for why.

By default, `analyze` evaluates the fixture catalog **and** (best-effort) whatever
`forgeway discover` finds on the local machine — pass `--skip-discovery` to use the fixture
catalog only. A locally saved `forgeway bench` run for a matching workload/target is picked up
the same way any other evidence is (`docs/decision-engine.md`) — but only if it was saved with
`--workload-id` set to that workload's real id (see above); `forgeway bench`'s own default
(`workload_id` = the `--model` string) never matches an existing demo workload, so a default run
doesn't affect any existing demo workload's recommendation.

## Web: importing a real benchmark result

`/import` lets you upload the `ComputeTarget` + `PerformanceEvidence` JSON the CLI above produces,
validate it against the real schema, and use it in `/analyze` — labeled `YOUR MEASURED COMPUTE`,
never merged into or confused with the `REFERENCE COMPUTE` fixture catalog. Stored only in your
browser (`localStorage`); no accounts, no server-side persistence. See
[`docs/importing-results.md`](docs/importing-results.md).

## End-to-end: CLI benchmark → web import → analyze

The three CLI commands plus the web import above form one coherent pipeline, each step's output
usable by the next:

```bash
forgeway discover --json > my-target.json                                              # 1. what hardware is here?
forgeway bench --model <model> --workload-id <a real workload id it matches> --json \
  > my-evidence.json                                                                   # 2. how does it perform?
forgeway analyze examples/workload.yaml                                                # 3. where should this workload run? (CLI path)
forgeway runs                                                                           # (list every benchmark run saved along the way)
```

Then, in the browser: open `/import`, upload `my-target.json` and `my-evidence.json`, then run
`/analyze` on the matching workload — the same result as step 3 above, but through the web UI,
with your real hardware included as a candidate alongside the fixture catalog.

**`--workload-id` only makes sense when your benchmarked model genuinely matches an existing
workload** (same family/parameter count) — `forgeway bench`'s own default model
(Llama 3.1 8B Instruct) doesn't correspond to any of this demo's five workloads, so a plain
`forgeway bench` run (no `--workload-id`) imports and displays correctly but is honestly never
picked up during analysis. To see the full pipeline working end-to-end without needing matching
GPU hardware, skip step 2 and upload the pair already checked into this repo instead —
`examples/discovered-target.json` + `examples/benchmark-result.json`, a real, honestly-tagged
pair for `wl-llama70b-rt` (see `examples/README.md`) — then run `/analyze` on that workload.

None of this touches the web demo's in-memory store or UI persistently. `forgeway analyze` does
read the same fixture catalog the web app reads (`app/data/loader.py`) as its base target list —
that's what makes `examples/workload.yaml` directly comparable to the web app's own `/analyze`
page — but it never writes to the demo's store. The web import flow similarly never writes
anything server-side; imported data lives only in your browser. Requires the full backend setup
above, plus vLLM and a CUDA GPU for step 2 specifically (`docs/benchmarking.md`); steps 1, 3, and
the web import all work on any machine — step 1 reports "no supported accelerator" cleanly
without one, and step 3 falls back to the fixture catalog alone.

---

## What's implemented vs. not

**Implemented:** the full feasibility → prediction → SLO check → normalize → weight →
confidence-gate → rank → recommend → explain pipeline; every metric (value, confidence,
provenance, range when available); policy (vendor/region/budget) as a real constraint;
per-workload `ObjectiveWeights` and `min_confidence_pct` that can change the ranking or the
recommendation outright; capacity-aware split placement that itself respects the confidence
gate; six named scenario presets, each backend-owned and mutation-free, with a BEFORE/EVENT/
AFTER comparison and an explicit change explanation; every route in the product spec,
fixture-driven; two real hardware discovery adapters (`forgeway discover`, local NVIDIA GPUs via
`nvidia-smi` and local AMD GPUs via `rocm-smi` — see [`docs/discovery.md`](docs/discovery.md))
and one real benchmark path across both vendors (`forgeway bench`, `vllm bench latency`,
`provenance: MEASURED`, dispatching its GPU telemetry sampler by vendor — see
[`docs/benchmarking.md`](docs/benchmarking.md)) — see "What hardware is supported today?" above
for the precise, current AMD/ROCm verification status (now live-verified end to end); a versioned
cross-vendor benchmark profile plus a comparability policy (`forgeway bench-profile`, `forgeway
compare-runs` — see "Cross-vendor benchmark profiles" above; live-verified on real NVIDIA+AMD
hardware, correctly classified `PARTIALLY COMPARABLE` — [`docs/cross-vendor-validation.md`](docs/cross-vendor-validation.md));
the placement engine's evidence path is
unified across fixture data and any real, locally saved `forgeway bench` run for a matching
workload/target (`MEASURED > PUBLISHED > MODELED` — see
[`docs/decision-engine.md`](docs/decision-engine.md)); `forgeway analyze` exposes that same
engine directly (`app/engine/decision.py::run_decision`, unchanged) against a YAML-defined
workload, and can add a locally discovered target to the fixture catalog it scores against. The
web UI can now do the equivalent: `/import` validates and stores a real `ComputeTarget` +
`PerformanceEvidence` pair in the browser, and `/analyze` includes it as an extra candidate,
labeled `YOUR MEASURED COMPUTE` and never merged into the `REFERENCE COMPUTE` fixture catalog —
see [`docs/importing-results.md`](docs/importing-results.md).

**Not implemented (by design, this build):** the web demo's own fixture catalog and baseline
scenarios still run entirely on fixtures — no cloud API calls, no live telemetry feeding it, no
Kubernetes; `forgeway discover` and `forgeway bench` themselves still only run from the CLI (the
web UI consumes their *output* via `/import`, not the tools themselves). No persistence beyond
an in-memory store server-side, and browser-local-only storage for imports (restart the API and
every simulated recommendation is gone, the baseline Insight reseeds; clear browser data and
every imported target/evidence record is gone too). No custom workload authoring in `/analyze` —
only the fixture workload library, though an imported target can stand in as an extra candidate
for one of those fixture workloads. No LLM in the decision path — the deterministic engine
decides; nothing here calls a model to place a workload.

---

## Contributing and roadmap

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for local setup, test commands, and how to add benchmark
evidence, a discovery adapter, or a workload fixture. See [`ROADMAP.md`](ROADMAP.md) for what's
next (AMD ROCm discovery is first).

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).
