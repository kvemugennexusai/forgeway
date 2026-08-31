# Forgeway data contracts — forgeway/v0.1

This formalizes the four vendor-neutral data contracts behind Forgeway's
[reusable core](architecture.md): **ComputeTarget**,
**AIWorkload**, **PerformanceEvidence**, and **PlacementDecision**. Every
one carries `schema_version: "forgeway/v0.1"`. Code lives in
`api/app/core/schemas/v0_1/`; serialized instances are in
[`examples/`](../examples/); validation tests are in
`api/tests/test_v0_1_schemas.py`.

## Migration approach

Two of these four concepts were already the codebase's single canonical
type; the other two didn't exist as a unified object yet. The migration
treats them differently, on purpose:

- **ComputeTarget** and **AIWorkload** — there was no duplicated ad hoc
  structure to replace. `app.core.schemas.compute.ComputeTarget` and
  `app.core.schemas.workload.Workload` already were this codebase's one
  definition of each concept, used by the fixtures, the engine, the HTTP
  routes, and (via `lib/types.ts`) the frontend. "Migrating" them means
  formalizing them in place: each gained a `schema_version` field, and
  `ComputeTarget` gained `accelerator_count` (a read-only alias for
  `capacity_units_total`) and `runtime_support` (a new field, `None` for
  every current fixture — see below). `AIWorkload` is a plain alias for the same `Workload`
  class, not a new type, so every existing import, route, and test is
  unaffected — no rename happened anywhere else in the codebase.
- **PerformanceEvidence** and **PlacementDecision** — these formalize
  concepts that were only ever *implicit*, spread across
  `PerformanceProfile`/`Prediction` and `CandidateEvaluation`/
  `Recommendation` respectively. Rather than redesign `app.core.engine` or
  `app.engine.decision` to produce these new shapes directly (real
  redesign risk, explicitly out of scope), each is built via an additive
  `from_*()` converter that takes exactly what the engine already computes
  and produces the formal, versioned record. Nothing in `app.core.engine`
  or `app.engine.decision` changed to support this.

"Migration is working" is proven in `api/tests/test_v0_1_schemas.py` by
running the real core pipeline against the real demo fixtures and checking
the converted result against the same known behavior
`api/tests/test_engine.py` already asserts (e.g. `PlacementDecision`
recommends `amd-mi300x` for `wl-llama70b-rt`, exactly like the live demo
does).

## 1. ComputeTarget

`api/app/core/schemas/compute.py`. One piece of AI compute capacity.

| Field | Type | Notes |
|---|---|---|
| `schema_version` | `"forgeway/v0.1"` | |
| `id`, `vendor`, `model`, `architecture` | `str` | |
| `tier` | `"datacenter" \| "edge" \| "lab"` | |
| `location` | `str` | free-text region/site; policy region checks token-match it |
| `memory_gb_per_device` | `float` | |
| `interconnect` | `str` | |
| `supported_precisions` | `list[str]` | |
| `runtime_support` | `Optional[list[str]]` | **new, `None` by default** — structured runtime/framework qualification (e.g. `"vLLM"`). `None` means "not known"; an empty list is reserved for "known: this target qualifies no runtimes" — a distinct, stronger claim nothing in this codebase can make yet. Not populated by today's fixtures; that information currently lives only in `unsupported_workload_classes[].reason` free text. |
| `capacity_units_total`, `capacity_units_allocated` | `int` | |
| `accelerator_count` | `int`, computed | **new** — read-only alias for `capacity_units_total`. In this fixture format one capacity unit is one physical accelerator; this is not separately stored data. |
| `free_capacity_units`, `utilization_pct` | computed | unchanged |
| `price_per_hr_per_unit` | `Metric` | pricing/economics, with its own provenance |
| `status` | `"healthy" \| "degraded" \| "offline"` | |
| `unsupported_workload_classes` | `list[UnsupportedWorkloadClass]` | |
| `notes` | `str` | |
| `observed_gpu_utilization_pct`, `observed_memory_utilization_pct` | `Optional[float]` | **new** — live discovery telemetry (see [`docs/discovery.md`](discovery.md)), deliberately separate from `utilization_pct` above: that field is Forgeway's own placement-bookkeeping concept (capacity units *Forgeway* has assigned), not instantaneous hardware busyness. `None` for every fixture. |
| `discovered_at` | `Optional[datetime]` | **new** — when a discovery adapter produced this record; `None` for fixture-sourced targets. |

## 2. AIWorkload

`api/app/core/schemas/workload.py`. `AIWorkload` is the formal, versioned
name for the existing `Workload` class (`AIWorkload = Workload` — same
class object, not a subtype). One deployable AI workload to place.

| Field | Type | Notes |
|---|---|---|
| `schema_version` | `"forgeway/v0.1"` | |
| `id`, `name` | `str` | |
| `workload_class` | `"realtime-inference" \| "batch-inference" \| "training"` | |
| `model_family` | `str` | |
| `model_params_billion` | `float` | required in v0.1 — every current workload has a known parameter count; a genuinely-unknown case can relax this in a later version if one shows up |
| `precision` | `str` | |
| `weights_footprint_gb`, `kv_cache_overhead_gb` | `float` | memory footprint |
| `baseline_concurrency` | `int`, `tokens_per_request` | `Optional[float]` | request/concurrency characteristics |
| `slo` | `SLO` (`p99_latency_ms`, `min_throughput_tokens_per_s`, `availability_pct`) | latency + throughput + availability SLO, one struct |
| `policy` | `EnterprisePolicy` | enterprise policy (vendor/region allow-list, budget ceiling) |
| `objective_weights` | `ObjectiveWeights` | optimization weights (cost/performance/headroom) |
| `min_confidence_pct` | `float` | |
| `current_placement` | `CurrentPlacement` | |

## 3. PerformanceEvidence

`api/app/core/schemas/performance_evidence.py`. A portable record of
what's known about running one workload on one compute target — built via
`PerformanceEvidence.from_performance_profile(profile)` (fixture data) or
by a real `forgeway bench` run (`docs/benchmarking.md`).

Originally introduced as a v0.1-only formal contract; promoted into
`app.core.schemas` proper (same move already made for `ComputeTarget` and
`Workload`/`AIWorkload`) now that the placement engine actually consumes
it — see [`docs/decision-engine.md`](decision-engine.md).
`app.core.schemas.v0_1.PerformanceEvidence` still re-exports the same
class under the same formal name; nothing importing it needs to change.

| Field | Type | Notes |
|---|---|---|
| `schema_version` | `"forgeway/v0.1"` | |
| `compute_target_id`, `workload_id` | `str` | |
| `configuration` | `Optional[str]` | free-text run description (replica count, tensor-parallel degree, ...) when known — not populated by today's fixtures |
| `metrics` | `dict[str, Metric]` | today always `throughput_tokens_per_s_per_replica` + `p99_latency_ms_per_replica` (`app.core.schemas.THROUGHPUT_METRIC_KEY` / `LATENCY_METRIC_KEY` — the canonical keys `app.core.engine.evidence_selection` requires); a dict (not two fixed fields) so a future metric doesn't need a schema change |
| `provenance` | `"MEASURED" \| "PUBLISHED" \| "MODELED"` | the *weakest* provenance among `metrics` — never claims better evidence than its least-certain input |
| `confidence` | `float` (0-100) | the weakest-link confidence among `metrics` |
| `source` | `str` | representative source string (today's fixtures give every metric in a row the same source) |
| `timestamp` | `Optional[datetime]` | `None` means "not recorded" — deliberately never defaulted to "now", since that would misrepresent migrated fixture data as a fresh measurement |
| `forgeway_version` | `str` | defaults to the running build (`app.core.version.FORGEWAY_VERSION`) |
| `benchmark_run_id` | `Optional[str]` | set by `forgeway bench` (`docs/benchmarking.md`) to correlate evidence with a specific saved run; `None` for fixture-derived evidence |

## 4. PlacementDecision

`api/app/core/schemas/v0_1/placement_decision.py`. A vendor-neutral summary
of one placement decision — new in v0.1, built via
`PlacementDecision.from_candidates(workload, candidates)`, where
`candidates` is the same `list[CandidateEvaluation]`
`app.core.engine.scoring`/`ranking` already produce.

| Field | Type | Notes |
|---|---|---|
| `schema_version` | `"forgeway/v0.1"` | |
| `workload_id`, `workload_name` | `str` | |
| `slo`, `current_placement` | `SLO`, `CurrentPlacement` | copied from the workload, for a self-contained record |
| `evaluated_targets` | `list[str]` | every target id considered |
| `feasible_targets` | `list[str]` | targets that passed hard compatibility (`CandidateEvaluation.feasible`) — independent of whether they were ultimately picked |
| `rejected_targets` | `list[RejectedTarget]` (`target_id`, `target_label`, `reasons`) | targets that didn't qualify to be ranked, with explicit reasons. **Can overlap with `feasible_targets`**: a target can be hardware-compatible and still be rejected for failing the SLO or the confidence requirement — that's a real, distinct fact worth keeping visible, not a bug. |
| `recommended_target_id` | `Optional[str]` | the single top-ranked target, if any |
| `score_breakdown` | `dict[str, ScoreBreakdown]` (`cost`, `performance`, `headroom`, `weighted_score`) | one entry per ranked candidate |
| `confidence` | `Optional[float]` | the recommended target's confidence |
| `improvement_vs_current_placement` | `Optional[ImprovementVsCurrentPlacement]` (`current_target_id`, `current_cost_per_hr`, `recommended_cost_per_hr`, `cost_savings_pct`, `slo_met`) | |
| `evidence_references` | `list[EvidenceReference]` (`label`, `source`) | pointers to where the recommendation's numbers came from, not full evidence bodies |

### Known v0.1 limitation

A **split placement** across multiple targets (this demo's greedy-split
fallback for demand that overflows a single target — see
`app/engine/decision.py::_greedy_split`) has no representation in
`PlacementDecision` v0.1. `recommended_target_id` is only set when a single
target was ranked #1 outright; a split scenario currently yields
`recommended_target_id = None` with no further detail. The product API's
`Recommendation.split_allocation` is the only place that information exists
today. A future schema version can add it once there's a concrete second
consumer that needs it.

## Provenance convention

Every evidence-bearing value in Forgeway — a `Metric`, a
`PerformanceEvidence` record, a `CurrentPlacement` — carries one of three
provenance values, and a record is never allowed to claim better provenance
than its weakest contributing input:

- `MEASURED` — from production telemetry or a real benchmark run.
- `PUBLISHED` — from a vendor's or cloud provider's published spec/pricing.
- `MODELED` — estimated (a performance model, an amortized cost estimate);
  never presented as `MEASURED`.

`Metric` also carries an `evidence_reference` field (`Optional[str]`) —
traceable back to *which* record a value came from: a real
`benchmark_run_id` when it came from a `forgeway bench` run selected via
`app.core.engine.evidence_selection`, a synthetic
`fixture-evidence:<target_id>:<workload_id>` descriptor for fixture data,
or `None` for metrics outside the evidence-selection path (e.g.
`ComputeTarget.price_per_hr_per_unit`, which has its own `source` string
and isn't part of `PerformanceEvidence`). See
[`docs/decision-engine.md`](decision-engine.md).

## Examples

[`examples/`](../examples/) has one real, generated instance of each
schema — see `examples/README.md` for exactly which fixture/decision each
one came from.

## What's out of scope for this pass

- `PerformanceEvidence` and `ComputeTarget` are now validated as HTTP
  request/response bodies (`POST /api/import/performance-evidence`,
  `POST /api/import/compute-target` — `app/routers/imports.py`,
  [`docs/importing-results.md`](importing-results.md)) — a stateless
  echo-back-if-valid pair used by the web import flow, not a stored
  resource. No route yet serves `PlacementDecision` over HTTP: the CLI's
  `forgeway analyze --json` emits it directly (README.md's end-to-end CLI
  flow), and nothing over HTTP returns that shape today. Adding an HTTP
  route for it is a reasonable next step once there's an actual second
  consumer that needs the versioned shape over the wire.
- `runtime_support` is real and typed but `None` for every current fixture —
  there's no structured runtime/framework data to populate it with yet.
- Split-placement decisions aren't representable in `PlacementDecision`
  v0.1 (see above).
