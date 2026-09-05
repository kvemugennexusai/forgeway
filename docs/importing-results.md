# Importing a real benchmark result into the web demo

How to take a real `forgeway discover` + `forgeway bench` result and use it
in the web demo's workload analyzer, alongside — never merged into — the
fixture catalog. No accounts, no database, no cloud sync: everything here
is validated by the real backend schema and stored only in your browser.

```
forgeway discover --json  >  ComputeTarget JSON
forgeway bench --json     >  PerformanceEvidence JSON
                                    |
                                    v
                        /import  (web UI)  →  browser localStorage
                                    |
                                    v
                        /analyze  →  included as an extra candidate
```

## Why two files, not one

The task this supports is literally "upload a `PerformanceEvidence`
record" — but `PerformanceEvidence` alone can't describe hardware. It has
no memory, precision, or pricing fields (see
[`docs/schemas.md`](schemas.md#3-performanceevidence)), and those are
exactly what the engine's hard-compatibility gate
(`app/core/engine/feasibility.py`) checks before it ever looks at
performance numbers. Inventing a `ComputeTarget` from an evidence record
alone — guessing memory or precision to make it fit — is exactly the kind
of fabricated data Forgeway's evidence path has been built to avoid at
every other step (see [`docs/decision-engine.md`](decision-engine.md)).

So the import flow asks for both real, independently-produced records:

1. **`ComputeTarget`** — the JSON `forgeway discover --json` printed:
   what the machine actually is (vendor, memory, architecture,
   precisions, location).
2. **`PerformanceEvidence`** — the JSON `forgeway bench --json` printed:
   what was actually measured running one workload on that machine.

Each is validated and stored independently. Evidence with no matching
imported (or reference) target is still kept and shown, with an explicit
warning that it won't be used in analysis yet — never silently discarded,
never silently paired with the wrong hardware.

## Using it

1. Run the CLI end-to-end on the machine you want to add
   ([`docs/discovery.md`](discovery.md), [`docs/benchmarking.md`](benchmarking.md)):

   ```bash
   forgeway discover --json > my-target.json
   forgeway bench --model <a model that matches an existing workload> --workload-id <that workload's id> --json > my-evidence.json
   ```

   **`--workload-id` matters — see "Tagging evidence with a real workload
   id" below.** Without it, the evidence still imports and displays fine,
   but it will never be picked up during analysis for any workload,
   because the engine matches evidence to a workload by exact id, and
   `--workload-id` defaults to the `--model` string (which is never a
   workload id). Whatever you do, don't set `--workload-id` to a workload
   whose model your benchmark doesn't actually match — see below.

2. Open the web demo, go to **Import result** in the sidebar
   (`/import`). To see the full pipeline immediately without any real GPU
   hardware, upload the two files already checked into this repo:
   `examples/discovered-target.json` and `examples/benchmark-result.json`
   — schema-valid and honestly labeled, but illustrative (hand-constructed
   inputs run through the real code path, not from an actual GPU — see
   `examples/README.md`) for `wl-llama70b-rt`.
3. Upload `my-target.json` in the **Compute target** dropzone, then
   `my-evidence.json` in the **Performance evidence** dropzone.
4. Go to **Analyze workload** (`/analyze`). If anything was imported, a
   `YOUR MEASURED COMPUTE` note appears above **Run analysis**, naming how
   many imported targets/evidence records will be included. Run the
   analysis as normal.
5. On the recommendation page, every candidate in **Candidate comparison**
   is labeled either `YOUR MEASURED COMPUTE` (imported) or
   `REFERENCE COMPUTE` (fixture) — never ambiguous which is which. Your
   imported target is evaluated by the exact same 11-step engine as every
   fixture target: it can be recommended, feasible-but-not-chosen, or
   honestly rejected with a real reason (insufficient memory, unsupported
   precision, region mismatch, ...), exactly like any other candidate.

## What's validated, and the errors you'll see

Both uploads go through the real backend schema
(`POST /api/import/compute-target`, `POST /api/import/performance-evidence`
— `app/routers/imports.py`), not a hand-rolled frontend check. FastAPI's
own Pydantic validation produces a structured `422` for every failure
case, which the import panel turns into a plain-language message:

| Problem | Example trigger | What you see |
|---|---|---|
| Malformed JSON | A truncated or hand-edited file | `"<file>" is not valid JSON — …` (caught before the file ever reaches the server) |
| Unsupported schema version | `"schema_version": "forgeway/v0.2"` or missing entirely | `Input should be 'forgeway/v0.1'` |
| Missing required field | A `ComputeTarget` JSON with no `memory_gb_per_device` | `Field required` at that field's path |
| Wrong type / malformed evidence | `"confidence": "high"` instead of a number | Pydantic's own type-coercion error at that field's path |
| Compute target id collision | Uploading a `ComputeTarget` whose `id` already exists in the reference fixture catalog | Rejected client-side before upload, with an explicit "never silently merged" message — re-export with a different id |

Nothing here is a fabricated frontend validation layer reimplementing the
schema; every rule enforced is the same Pydantic model
(`app/core/schemas/compute.py`, `app/core/schemas/performance_evidence.py`)
the engine itself trusts.

## Storage: browser-local, additive-only, no accounts

- Imported targets and evidence live in `localStorage`
  (`web/lib/imported-storage.ts`), keyed `forgeway.imported.targets` /
  `forgeway.imported.evidence`. Nothing is uploaded to a server-side store
  or database, and nothing syncs across browsers or devices — clearing
  site data or opening a different browser starts empty.
- Importing never edits or replaces the reference fixture catalog
  (`app/data/loader.py`). An id collision on a `ComputeTarget` is
  rejected outright, not merged — see the table above. The same rule
  applies to evidence: `imported_evidence` naming a reference-catalog
  `compute_target_id` that wasn't also imported as a target is rejected
  (400) rather than silently gathered as a scoring candidate for that
  reference target — otherwise it could outrank and replace the
  reference target's own real evidence via ordinary
  MEASURED/confidence/recency tie-breaking, with no id-collision signal
  to catch it.
- `POST /api/analyze` accepts imported data as part of the request body
  (`imported_targets`, `imported_evidence` on `AnalyzeRequest` —
  `app/models.py`) rather than persisting it anywhere server-side; the
  server holds nothing about your import after the response comes back.
  Both collision checks (target and evidence) are enforced server-side in
  `app/routers/analyze.py`, so a stale or tampered request can't sneak a
  colliding id past the client-side check.
- "Clear all imported data" on `/import` wipes both keys; removing a
  single target or evidence record removes just that one.

## The metric-key bridge (why a real `forgeway bench` run is usable at all)

The engine's evidence selection (`app.core.engine.evidence_selection`,
[`docs/decision-engine.md`](decision-engine.md)) only scores candidates
against two canonical metric keys:
`throughput_tokens_per_s_per_replica` / `p99_latency_ms_per_replica`. Until
this pass, `forgeway bench`'s own saved records used different keys
(`output_token_throughput_tokens_per_s`, `p99_latency_ms`, ...) and were
never actually selectable — a known gap `docs/decision-engine.md`
previously documented as out of scope. Since this import flow's whole
point is a working CLI-to-web pipeline, `build_performance_evidence()`
(`app/benchmark/evidence.py`) now also stamps the canonical aliases onto
every record it builds:

- Throughput is **always** aliased — it's arithmetically derived either
  way, so no new claim is being made.
- Latency is aliased **only when a real P99 percentile was captured**
  (`vllm bench latency --percentiles ... 99`). The plain average latency
  is never relabeled as a P99 figure — doing so would assert a
  statistical equivalence that isn't true, exactly the kind of
  fabrication this project avoids everywhere else. A run without a
  captured P99 still imports and displays correctly; it just won't carry
  enough for the engine to select it as comparable evidence.

See `api/tests/test_benchmark_evidence.py` for both the positive case
(aliases present, engine-selectable) and the negative case (no P99
captured → no latency alias, never fabricated).

## Tagging evidence with a real workload id

The engine matches evidence to a workload by an **exact** `workload_id`
string ([`docs/decision-engine.md`](decision-engine.md)) — there is no
fuzzy matching on model family or name. `build_performance_evidence()`
(`app/benchmark/evidence.py`) sets `workload_id` to the benchmarked
`--model` string by default, and a HuggingFace model string like
`meta-llama/Llama-3.1-8B-Instruct` will never equal a Forgeway workload id
like `wl-llama70b-rt` — so a default `forgeway bench` run's evidence,
imported as-is, will display correctly but can **never** be selected for
any existing workload during analysis.

`forgeway bench --workload-id <id>` overrides this, tagging the saved
evidence with a real Forgeway workload id instead. **This is only honest
when the benchmarked `--model` actually corresponds to that workload** —
same model family, same parameter count. Tagging an unrelated model's
numbers with someone else's workload id would misrepresent what was
measured, exactly the kind of fabrication this project avoids everywhere
else. Concretely: this repo's own demo workloads (`wl-llama70b-rt` is a
Llama 3.1 **70B** workload) don't correspond to `forgeway bench`'s own
default, most-likely-to-actually-run-on-a-dev-machine model
(Llama 3.1 **8B** Instruct, per `docs/benchmarking.md`) — so don't tag an
8B benchmark run as `wl-llama70b-rt`. Use `--workload-id` for your own
real workloads outside this demo, or when you've actually benchmarked a
model that genuinely matches one of the five demo workloads.

Nothing server-side verifies that the tag is honest — like every other
provenance claim in Forgeway, this is a promise the person producing the
evidence is trusted to keep, not something the schema can check for them.

## Current limitations

- Requires both files to be uploaded as a pair to be usable in analysis;
  evidence for a target that was never (or not yet) imported is kept and
  shown, but flagged as unusable until the matching target arrives.
- No cross-check that an uploaded `PerformanceEvidence.workload_id`
  actually corresponds to a workload in this demo's library, or that
  `--workload-id` was used honestly — if it doesn't match any of the five
  demo workloads exactly, it simply won't be considered for any of them;
  if it does match, nothing verifies the tag was applied to a genuinely
  comparable model (see above).
- Import is one file at a time per dropzone (no batch/multi-file upload).
- No edit-in-place: fixing a typo in an imported record means removing it
  and re-uploading a corrected file.
