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
