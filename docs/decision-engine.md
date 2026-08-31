# The decision engine's unified evidence path

How the placement decision engine (`app/engine/decision.py`,
`app/core/engine/`) decides which `PerformanceEvidence` record to score a
candidate against — connecting real, locally saved `forgeway bench` runs
(`docs/benchmarking.md`) to the same engine that already scores this
demo's fixtures. The 11-step decision philosophy is unchanged: evaluate
hard compatibility, reject infeasible targets, evaluate SLOs, score
feasible targets, rank them, explain the recommendation. Only *where a
candidate's performance numbers come from* changed.

## The pipeline, updated

```
1-2. Load workload, load compute targets.        (unchanged)
3.   Evaluate hard compatibility.                 (unchanged — app/core/engine/feasibility.py)
4.   Return explicit rejection reasons.           (unchanged)
5.   Retrieve the prediction for a feasible target:
       a. Gather every PerformanceEvidence candidate for this
          (workload, target) pair — fixture-derived AND any real,
          locally saved `forgeway bench` run.      (app/engine/evidence_gateway.py — NEW)
       b. Select the one to actually score against. (app/core/engine/evidence_selection.py — NEW)
       c. Extract the prediction from it.           (app/core/engine/scoring.py — CHANGED)
6.   Check SLO constraints.                       (unchanged, hard reject)
7-8. Normalize + weight.                          (unchanged)
9.   Apply confidence requirements.                (unchanged — reads whatever confidence the
                                                    selected evidence carries)
10.  Rank candidates.                              (unchanged)
11.  Return recommendation plus reasoning.         (unchanged)
```

Steps 3, 6-10 are byte-for-byte the same code as before this milestone.
Step 5 is the only thing that changed: it used to read exactly one
`PerformanceProfile` fixture row per (workload, target) pair; it now reads
*every* `PerformanceEvidence` candidate available for that pair and picks
one.

## Where evidence comes from

`app/engine/evidence_gateway.py::gather_evidence_candidates(workload_id,
target_id, *, benchmark_runs)` returns every candidate for one pair;
`resolve_evidence(...)` — the function `decision.py`'s three
evidence-consuming call sites actually use — gathers and selects in one
call, so none of them repeats the gather-then-select pattern separately.

1. **The fixture row**, if one exists — `app/data/loader.py`'s
   `PerformanceProfile`, wrapped as `PerformanceEvidence` via
   `PerformanceEvidence.from_performance_profile()` (the same conversion
   `docs/schemas.md` already documented; it's now also how fixture data
   enters the engine, not just an export format).
2. **Any real, locally saved `forgeway bench` run** (`app/benchmark/store.
   list_runs()`) whose `workload_id` and `compute_target_id` match this
   pair exactly — no fuzzy matching, no matching on model family or
   partial name. A real benchmark run becomes a *candidate* the moment
   it's saved, with no separate wiring needed per run. Whether it's
   actually *selected* depends on whether it carries the engine's
   canonical metric keys — `forgeway bench` now stamps those onto every
   run it saves (throughput always, P99 latency only when a real P99 was
   captured — see `docs/benchmarking.md`'s "current limitations"), so a
   run with a captured P99 is selectable; one without isn't
   (`tests/test_decision_evidence_integration.py` proves both cases).
3. **Evidence imported through the web UI** (`docs/importing-results.md`)
   — a `PerformanceEvidence` record a user uploaded and validated in
   their browser, passed into `run_decision(..., imported_evidence=...)`
   for that one request only. Not persisted anywhere server-side; see
   "Three callers" below.

`benchmark_runs` is fetched **once per `run_decision()` call**, not once
per target — `run_decision()` calls `list_runs()` a single time, appends
the caller's `imported_evidence` (if any — web-imported evidence never
touches disk, so this is a plain in-memory list concatenation, not another
read), and passes the combined list to every `resolve_evidence()` call for
that decision. Re-reading and re-parsing every locally saved benchmark
file once per target in the estate would be needless, repeated disk I/O;
this way it's one filesystem read regardless of how many targets are
evaluated. (If `~/.forgeway/benchmarks` grows very large, this is still a
full-directory read on every `/api/analyze` call — acceptable for a
fixture-scale demo, worth revisiting with caching if it ever becomes a hot
path.)

## Evidence selection: comparability before provenance

`app/core/engine/evidence_selection.py::select_evidence(candidates, *,
required_metrics)` — the one function that decides which evidence a
candidate is scored against.

**The rule: comparability gates before provenance preference.** A
candidate that doesn't carry the metrics the engine actually needs is not
"more relevant" just because its provenance outranks another's:

1. **Comparability first.** Filter to candidates that carry every key in
   `required_metrics` (today: `p99_latency_ms_per_replica` and
   `throughput_tokens_per_s_per_replica` —
   `app.core.schemas.LATENCY_METRIC_KEY` / `THROUGHPUT_METRIC_KEY`). A
   MEASURED record missing one of these is not usable, full stop — it is
   never preferred over a complete MODELED record just because MEASURED
   generally outranks MODELED. This is deliberately a strict, exact-match
   notion of "comparable" (has the numbers we need), not a fuzzy
   similarity score across `configuration` strings, input/output token
   counts, or anything else — see "What's out of scope" below.
2. **Provenance preference among the usable ones.**
   `MEASURED > PUBLISHED > MODELED` (`app.core.schemas.PROVENANCE_RANK`).
3. **Ties broken by confidence, then recency.** Among candidates tied on
   provenance, higher `confidence` wins; among ties on both, the most
   recently recorded (`timestamp`) wins. Simple, documented tie-breakers —
   not a statistical judgment.

If nothing survives step 1, `select_evidence` returns `None` — the honest
"no usable evidence" signal, never an invented number.

**Precondition:** every candidate passed in must already describe the same
`(workload_id, compute_target_id)` pair — gathering and matching is
`gather_evidence_candidates`'s job, not `select_evidence`'s. Passing
mixed-pair candidates raises `ValueError` rather than silently picking a
"best" evidence that's actually about the wrong workload or target.

## What a candidate's Metric carries

Every `Metric` returned to the placement engine (`Prediction.latency_p99_ms`,
`Prediction.throughput_tokens_per_s`) now carries:

| Field | Source |
|---|---|
| `value` | from the selected evidence's metric |
| `provenance` | from the selected evidence's metric — never upgraded or relabeled |
| `confidence` | from the selected evidence's metric |
| `evidence_reference` | **new** — `benchmark_run_id` for a real `forgeway bench` run, or a synthetic `fixture-evidence:<target_id>:<workload_id>` descriptor for fixture-derived evidence. Always traceable back to *which* record this number came from. |
| `range_low` / `range_high` | from the selected evidence's metric, when known |

`retrieve_prediction()` (`app/core/engine/scoring.py`) does not choose
between competing evidence — by the time it's called, `select_evidence`
has already decided. Its only job is extracting the two required metrics
by their canonical keys and stamping `evidence_reference` on each.

## Missing or insufficient evidence

If `gather_evidence_candidates` finds nothing, or nothing it finds
survives `select_evidence`'s comparability filter, `score_candidate`
receives `evidence=None` — unchanged behavior from before this milestone:
the candidate is marked infeasible with an explicit reason ("No
trustworthy performance evidence on file..."), never scored from a
guess. This is the existing policy for missing evidence, applied exactly
as before; nothing about "trust the evidence you have" changed, only
*which* evidence that is.

The **confidence threshold policy** (`Workload.min_confidence_pct`) is
completely unaffected by this change — it still gates on
`CandidateEvaluation.confidence_pct`, which is still `Prediction`'s
weakest-link confidence across latency, throughput, and cost. What changed
is that this confidence can now genuinely reflect a real measured run's
confidence, not only a fixture's. `tests/test_decision_evidence_integration.py`
proves this concretely: at an 85% confidence bar, MI300X's old MODELED
evidence (confidence 78, further capped by its own pricing confidence)
doesn't qualify and H100 is recommended solo; once a real, high-confidence
MEASURED run for MI300X is introduced, MI300X's evidence is preferred over
the old MODELED row (MEASURED > MODELED), its confidence rises enough to
clear the 85% bar, and — because it already wins on weighted score once
both candidates qualify (same math as the workload's own default-confidence
baseline) — the recommendation switches from H100 to MI300X.

## Three callers, one engine

`run_decision()` has three callers: the web app's routers (`/api/analyze`,
the estate insight panel, both simulation types), the CLI's
`forgeway analyze` (`docs/benchmarking.md`'s sibling command, README.md's
end-to-end CLI flow), and `/api/analyze` again but with a user's
browser-imported targets/evidence attached
(`docs/importing-results.md`) — the same route, not a fourth code path.
None of the three reimplements any part of the 11-step pipeline —
`forgeway analyze` calls the identical function, then reframes its
`candidates` as a vendor-neutral `PlacementDecision`
(`PlacementDecision.from_candidates(workload, record.candidates)`,
`docs/schemas.md`) instead of the product's own `Recommendation` shape.

The one thing `forgeway analyze` needed that no existing caller did:
scoring against a *different* set of compute targets than the fixture
catalog (e.g. the fixture catalog plus a locally discovered target). Since
every existing caller was hardcoded to `app/data/loader.py::
load_compute_targets()`, `run_decision()` gained an optional `targets`
parameter — `None` (the default) preserves the exact prior behavior for
every existing caller; a caller that passes its own list uses that
instead. `_greedy_split` and `_build_unmitigated_projection` (previously
each calling `load_compute_targets()` independently) now receive the same
`targets_by_id` `run_decision()` itself resolved, rather than re-fetching
it — the same "resolve a shared resource once, thread it through" pattern
already used for `benchmark_runs` above.

The web import flow needed the same for evidence: an optional
`imported_evidence` parameter, `None` by default, appended to
`benchmark_runs` for that call only (see above). `/api/analyze`
(`app/routers/analyze.py`) is the only caller that ever passes non-empty
`imported_targets`/`imported_evidence` — it merges the request's
`imported_targets` with the fixture catalog first, rejecting (400) any id
collision, before calling `run_decision()`. Nothing is written to disk or
to the in-memory store as a result; the response is exactly as ephemeral
as any other `/api/analyze` call.

## The web UI

`ComputeTarget`/`Workload`/`Prediction`/`Metric` shapes are unchanged
except for `Metric`'s new, additive `evidence_reference` field —
`web/lib/types.ts` was updated to match. Every place the UI already
displays provenance (`ProvenanceBadge`, the evidence panel, the
infrastructure explorer) continues to work unchanged; nothing about *how*
provenance is rendered changed, only that the provenance shown can now
genuinely originate from a real benchmark run instead of only ever being
a fixture's.

## What's out of scope for this pass

- **The P99 latency alias only bridges when a real P99 was captured.**
  `forgeway bench`'s saved records now carry the engine's canonical
  metric keys (see `docs/benchmarking.md`), but bridging vLLM's
  `end_to_end_latency_ms` (an *average* over N iterations) to the
  engine's `p99_latency_ms_per_replica` (a *P99* figure implicitly
  describing steady-state per-replica capacity) would assert a
  statistical equivalence that isn't actually true if there's no real P99
  to alias from — so a run without `--percentiles ...,99` still isn't
  selectable, by design, not by omission
  (`tests/test_decision_evidence_integration.py` proves both the
  selectable and non-selectable cases).
- Today's flagship demo workload (`wl-llama70b-rt`, Llama 3.1 **70B**) and
  the benchmark runner's prioritized model (Llama 3.1 **8B** Instruct) are
  different models — a real 8B benchmark run would never be valid
  evidence for a 70B workload's placement decision regardless of the key
  names, so no fuzzy cross-model matching was ever considered.
- No new "comparability" signal beyond required-metric-keys was
  implemented — no similarity scoring across `configuration` strings, no
  matching on precision/workload-class/tensor-parallel degree. If a real
  need for that arises (e.g. two real benchmark runs for the same pair at
  different concurrency levels), extending comparability is the next step,
  not something this pass anticipated.
