# forgeway/v0.1 serialization examples

Four real instances of Forgeway's versioned data contracts (see
[`docs/schemas.md`](../docs/schemas.md)), generated directly from this
repo's actual demo fixtures and engine — not hand-written.

| File | Schema | Source |
|---|---|---|
| `compute_target.v0_1.json` | `ComputeTarget` | the `nvidia-h100-dc` fixture row |
| `ai_workload.v0_1.json` | `AIWorkload` | the `wl-llama70b-rt` fixture row |
| `performance_evidence.v0_1.json` | `PerformanceEvidence` | the MEASURED H100/llama70b performance-profile row, via `PerformanceEvidence.from_performance_profile()` |
| `placement_decision.v0_1.json` | `PlacementDecision` | the real baseline decision for `wl-llama70b-rt`, computed by running the actual `app.core.engine` pipeline against the real fixtures, via `PlacementDecision.from_candidates()` |

Every file is byte-for-byte what `model_dump_json(indent=2)` produces for
these objects — `api/tests/test_v0_1_schemas.py` proves the same pipeline
this file was generated from (`_ranked_candidates()` + `from_candidates()`)
produces this exact recommendation.

Two more, illustrating the web import flow
([`docs/importing-results.md`](../docs/importing-results.md)) rather than
this repo's own fixtures — also real, generated objects, not hand-written:

| File | Schema | Source |
|---|---|---|
| `discovered-target.json` | `ComputeTarget` | an illustrative `forgeway discover --json` result for a local NVIDIA RTX 6000 Ada box, built by constructing a real `ComputeTarget` and calling `.model_dump_json()` |
| `benchmark-result.json` | `PerformanceEvidence` | the real `build_performance_evidence()` function (`app/benchmark/evidence.py`) run against a parsed `vllm bench latency` result for `meta-llama/Llama-3.1-70B-Instruct` on that target, tagged with the real `wl-llama70b-rt` workload id via the `--workload-id` mechanism (`docs/importing-results.md`) — an honest pairing, since the benchmarked model actually matches that workload's family/parameter count. Includes both P50/P99 percentiles so the canonical latency alias is present. |

Both validate successfully against the live `/api/import/*` endpoints —
they're meant to be uploaded on `/import` as a working end-to-end example.

**Regenerating:** these files are not hand-kept — if the demo's fixtures or
`app.core.engine` change, rerun the committed generator (with the `api/`
virtualenv active):

```bash
python api/scripts/generate_examples.py
```

`api/tests/test_v0_1_schemas.py` checks that the committed files still
parse and still match the demo's known behavior, but it does not
regenerate them — that's this script's job, run by hand when something
upstream changes.
