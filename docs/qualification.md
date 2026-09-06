# Qualification records — `forgeway qualify`

Whether a workload even *runs* on a piece of hardware is a different kind
of fact from how *confident* Forgeway is in a measured number. Before this
feature, the only place that first fact lived was
`ComputeTarget.unsupported_workload_classes` — a hand-authored
`{workload_class, reason}` blob with no source, no timestamp, and no
evidence link. Two real fixture entries were literally vendor-behavior
claims asserted as fact: Trainium2's "Neuron SDK realtime
continuous-batching serving path not qualified for this workload class in
the current release snapshot," never tested, no citation. This page is
about the type and the pipeline that replace that pattern:
`QualificationRecord` (`api/app/core/schemas/v0_1/qualification.py`), a
staged way to actually check it
(`api/app/qualification/checker.py`), and a small persistent databank
(`api/app/qualification/store.py`).

## What a qualification is about

Never a whole vendor. A `QualificationSubject` is the exact combination:

- `vendor`, `hardware_model`, `architecture`
- `runtime`, `runtime_version`, `backend` (e.g. `"cuda"`/`"rocm"` — mirrors
  `app.benchmark.cross_vendor.EnvironmentInfo.backend`)
- `model`, `precision`
- `deployment_config` (tensor-parallel degree, quantization, ...)
- `workload_class`, and optionally `slo`

`slo` is part of the subject's identity, not a detail layered on top: a
general "does this run at all" fact (`slo=None`) and a "does it meet this
exact SLO" fact (`slo` set) are different claims, never conflated. Two
fields — `model` and `precision` — accept the documented wildcard `"*"`
("any model"/"any precision"), used only by general, workload-class-level
facts (see "Feasibility integration" below) — a real measured claim about
one specific model always names it.

`QualificationSubject.subject_key()` is a deterministic hash of the whole
object; a record's `id` is `qual-<subject_key()>`. Two checks of the same
subject resolve to the same record — the databank is a **current-state
store, not an audit log**: re-checking a subject overwrites its previous
record, the same philosophy as `forgeway discover` overwriting the
previous view of "this machine now."

## The four states

| State | Meaning | Who can produce it |
|---|---|---|
| `unknown` | Nobody has checked, or an automated check couldn't get far enough to say anything | The default (no record at all), or any automated stage failure |
| `unsupported` | A documented constraint applies | **Only a human**, via `forgeway qualify-import` with a real, citable `source` |
| `smoke_tested` | It ran | `run_qualification_pipeline()`, when every stage passes and no SLO was given |
| `measured_pass` / `measured_fail` | A specific SLO was actually evaluated | `run_qualification_pipeline()`, when every stage passes and an SLO was given — a real pass/fail outcome from comparing the smoke test's own metrics to it |

**Deliberate, enforced invariant:** the automated pipeline
(`app.qualification.checker`) never produces `state="unsupported"`. That
state means a documented constraint — a real source a human supplies, not
an inference Forgeway draws from one failed run (which could be
transient, environment-specific, or a version-specific bug, not a
fundamental incompatibility). Every automated stage failure downgrades to
`unknown` instead. If you believe a vendor's stack behaves a certain way,
that's a thing to test against a pinned version (run `forgeway qualify`
and see what actually happens), not a fact to hand-author as
`unsupported` without evidence.

Every record also carries `source`, `environment`, `timestamp`,
`evidence_reference` (required — and validated — for the two `measured_*`
states), and an optional `review_date`.

## Staged checking

`app.qualification.checker.RuntimeChecker` (mirrors
`app.discovery.adapter.DiscoveryAdapter`'s minimal, no-registry
convention) runs four stages in order, stopping at the first failure — a
later stage presupposes every earlier one:

1. **`runtime_present`** — is the runtime actually usable on this
   machine at all. Never just "is a plugin/entry point registered for
   it" — vLLM has both built-in platform support and external plugins,
   and a registered entry point proves nothing about whether it
   actually initializes, reaches a device, or runs. `VllmRuntimeChecker`
   checks `is_vllm_available()` (is `vllm` actually on `PATH`).
2. **`device_reachable`** — does this runtime's own tooling still see a
   device of the target's vendor right now (reuses
   `app.discovery.adapter.discover_all()`).
3. **`config_supported`** — best-effort *structural* checks only (does
   the requested tensor-parallel degree fit the discovered device
   count, is the precision mappable to a real `--dtype` flag). Passing
   this stage does not guarantee runtime acceptance — only the smoke
   test below genuinely proves that.
4. **`smoke_test_passed`** — a real, minimal (single-iteration, tiny
   token counts) `vllm bench latency` invocation. Its result is saved as
   a real `PerformanceEvidence` via the existing benchmark store, so
   it's inspectable with `forgeway runs` like any other real run.

Only one concrete `RuntimeChecker` ships today, `VllmRuntimeChecker`. A
runtime with no checker (Neuron included) has no automated path at all —
see `docs/adding-an-accelerator.md`.

## The databank

Two layers, merged: a bundled fixture
(`api/app/fixtures/qualifications.json`, demo-shipped) and a local
directory of real checks (`~/.forgeway/qualifications` by default,
override with `FORGEWAY_QUALIFICATION_DIR` — same convention as
`forgeway bench`'s `FORGEWAY_BENCH_DIR`). A local record for a subject
overrides the fixture's for that same subject; a lookup falls back to the
fixture when nothing local exists; `None` when neither has one — "nobody
has checked" is a valid, common, non-error outcome.

**Staleness.** `review_date` in the past (`app.qualification.store.
is_stale()`) means *revalidate, or discount this* — it never silently
becomes a rejection, and symmetrically never silently becomes an
acceptance either. A stale record's existing pass/fail signal is kept
exactly as it was; only the human-readable detail gets a "this record is
stale" note appended.

## CLI

```bash
# Evaluate if something is already in the databank; if not, run the
# staged checks and add a record.
forgeway qualify benchmarks/profiles/llama-8b-cross-vendor-v0.1.yaml \
  --workload-class realtime-inference

# ...and actually evaluate a specific SLO against the smoke test's own
# metrics (measured_pass/measured_fail instead of smoke_tested):
forgeway qualify benchmarks/profiles/llama-8b-cross-vendor-v0.1.yaml \
  --workload-class realtime-inference --slo-from examples/workload.yaml

# Force a re-check even if a record for this exact subject already exists.
forgeway qualify ... --force

# Hand-author a record (the only path for a runtime with no RuntimeChecker
# yet, or a genuinely documented constraint with a real source):
forgeway qualify-import my-neuron-constraint.json

# List everything in the databank (fixture + local, merged):
forgeway qualifications
```

`forgeway qualify`'s deployment config (built from the profile:
tensor-parallel degree always, quantization/max-model-len when set) is
deliberately never empty — these are genuinely config-specific claims,
not general "does this workload class run at all" facts. That's why they
don't automatically feed the coarse feasibility check below; see "What's
deferred."

## Feasibility integration

`app/engine/qualification_check.py::evaluate_databank_qualification()`
adds one more, additive `FeasibilityCheck` to `forgeway analyze`'s
hard-compatibility checklist, appended by `app/engine/decision.py` right
after `app.core.engine.feasibility.evaluate_feasibility()`'s own checks —
**not inside `app.core.engine.feasibility` itself**. `app.core` is proven
decoupled from any I/O source (`api/tests/test_core_isolation.py`), and
the databank is real filesystem I/O — the same reason evidence gathering
lives in `app.engine.evidence_gateway`, not `app.core`.

This check only ever looks up the **coarse** subject: `vendor` +
`hardware_model` from the target, `runtime="vllm"` (Forgeway's only real
runtime today), `model="*"`, `precision="*"`, `workload_class` from the
workload, `deployment_config={}`, `slo=None`. Precision is deliberately
wildcarded, not taken from the workload: precision *compatibility* is
already its own, independent check (`evaluate_feasibility`'s
"architecture: precision/runtime compatible") — this check is about
workload-class software qualification, the same axis
`unsupported_workload_classes` already keeps precision-agnostic, and
mirrors that scope exactly. The existing
`"software: workload class qualified"` check is completely untouched and
runs independently — both checks are proven not to affect each other
(`api/tests/test_engine_qualification.py`).

Outcome mapping:

- no record, or `state="unknown"` → passes, not blocking.
- `state="unsupported"` → fails; `detail` is the record's own `source`
  verbatim, never a Forgeway-invented explanation.
- `state="smoke_tested"` → passes.
- A stale record never flips the outcome — see "Staleness" above.

## Worked example: the Trainium2 migration

`api/app/fixtures/compute_targets.json`'s `aws-trainium2` entry used to
carry `unsupported_workload_classes: [{"workload_class":
"realtime-inference", "reason": "Neuron SDK realtime continuous-batching
serving path not qualified..."}]` — the exact anti-pattern this feature
exists to stop. That entry is gone. In its place,
`api/app/fixtures/qualifications.json` carries a coarse
(`model="*"`, `precision="*"`) `unknown` record for
`(aws, "Trainium2 (trn2)", vllm, realtime-inference)`, with a `source`
stating plainly that no verifiable Neuron SDK documentation was found to
back the previous claim.

Concretely, in `forgeway analyze examples/workload.yaml`, Trainium2 is
still `REJECTED` — but now for the honest reason: there's no
`PerformanceEvidence` on file for it at all
(`api/app/fixtures/performance_profiles.json` has no `aws-trainium2`
row), not an invented vendor-behavior claim. Gaudi 3's fixture has the
exact same shaped claim (`compute_targets.json`, "Continuous-batching
low-latency serving runtime not qualified... on Gaudi 3") and was
**deliberately left untouched** this pass — a real next candidate for the
same migration, not done here to keep this change reviewable.

## What's deferred

- **`measured_pass`/`measured_fail` records aren't consulted by the
  decision engine.** They're config-pinned and SLO-pinned by design (see
  "The four states"), so they never match the coarse subject the
  feasibility check looks up. Using them correctly means extending
  `app.core.engine.evidence_selection`'s comparability rule (today: "has
  the required metric keys," nothing about precision/config/workload
  class) — `docs/decision-engine.md` already flags that as an explicit
  next step, not something this phase does.
- **Only vLLM has a real `RuntimeChecker`.** Neuron and any other runtime
  can only ever reach `unknown` (no record) or a hand-authored
  `unsupported`/`unknown` via `forgeway qualify-import` — never
  `smoke_tested`/`measured_*` until someone writes a real checker for it
  (`docs/adding-an-accelerator.md`).
- **Gaudi 3's identical-shaped fixture claim wasn't migrated** — see
  "Worked example" above.
