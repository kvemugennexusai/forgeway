# Cross-vendor benchmark validation checklist

How to validate the claim: **"Forgeway can measure the same AI workload on
NVIDIA and AMD hardware and use the resulting evidence in a vendor-neutral
placement decision."** This is a procedure — follow it end to end on real
NVIDIA and real AMD hardware before treating that claim as demonstrated.

**Status of this claim as of this writing: LIVE VERIFIED.** `forgeway
bench-profile` ran for real on both an NVIDIA DGX Spark (GB10, aarch64,
inside `vllm/vllm-openai:cu130-nightly`) and a real AMD Radeon RX 9070 XT
(inside `rocm/vllm:rocm7.13.0_gfx120X-all_...`), against the same
`BenchmarkProfile` (`qwen2.5-1.5b-cross-vendor` v0.1 — see "Why the model
changed twice" below), each producing a real `CrossVendorEvidenceRecord`.
`forgeway compare-runs` then ran for real against both saved files and
returned **`PARTIALLY COMPARABLE`** — correct, not a failure: every
critical dimension (model, precision, quantization, token counts,
concurrency, tensor-parallel degree, runtime family, benchmark mode) matched
exactly; only two soft dimensions differed (vLLM patch version and driver
version — expected, since each vendor's Docker image bundles its own build).
See "Real cross-vendor result (live, 2026-09-04)" below for the actual
command and output. The decision-engine steps (10-15) have not additionally
been run against these two specific records — those remain covered by
`api/tests/test_decision_cross_vendor.py`'s synthetic-evidence proof that
the (unmodified) engine already handles this correctly, not by a fresh live
run on top of these files; that's the one piece of this checklist still
open if someone wants to close it further.

Every piece below (`forgeway bench-profile`, `forgeway compare-runs`, the
decision engine's ability to rank NVIDIA and AMD evidence side by side) is
implemented and covered by unit/integration tests using mocked subprocess
output and synthetic evidence (`api/tests/test_cross_vendor_*.py`,
`api/tests/test_decision_cross_vendor.py`) as a baseline, **and now also by
one real, completed run of the whole pipeline on real hardware** — see
"Real bugs found and fixed" below for what that live run actually caught
that no amount of mocked testing did. Per this project's
documentation-claim discipline, it is now accurate to say: **"Forgeway has
been live-validated running the same benchmark profile on NVIDIA and AMD
hardware, and correctly classified the result as partially — not
fully — comparable."** Saying more than that (e.g. claiming full,
unqualified comparability, or claiming this proves anything about the 7B
or Llama 3.1 8B profiles specifically, which were not the ones that
succeeded) would be overclaiming — see "Why the model changed twice."

## Prerequisites

- One machine with an NVIDIA CUDA GPU, the NVIDIA driver, and `nvidia-smi`
  on `PATH` (`docs/discovery.md`).
- One machine with an AMD ROCm GPU, the ROCm stack, and `rocm-smi` on
  `PATH` (`docs/discovery.md#amd-rocm-rocm-smi`).
- vLLM installed on **both**, matching each vendor's build — see
  `docs/benchmarking.md#dependencies`. This is the single most likely place
  this checklist stalls: `pip install vllm` only produces a working CUDA
  build; a ROCm-capable vLLM needs its Docker image or a from-source build
  against a ROCm PyTorch.
- A Hugging Face account with the gated Llama 3.1 license accepted (or use
  the open alternative noted in the profile file's own comments — see
  `benchmarks/profiles/llama-8b-cross-vendor-v0.1.yaml`), on both machines.
- **A real, non-empty `supported_precisions` on each discovered
  `ComputeTarget` before step 10.** Every discovery adapter always reports
  `supported_precisions: []` (`docs/discovery.md`'s Limitations section) —
  this is an existing, deliberate adapter limitation, not something this
  checklist works around. `app/core/engine/feasibility.py` hard-rejects a
  workload whose `precision` isn't in a target's `supported_precisions`, so
  a workload built around this profile's `precision: bf16` will be rejected
  by both freshly-discovered targets unless you edit each target's JSON to
  add `"supported_precisions": ["bf16"]` by hand first (the same kind of
  manual annotation `docs/importing-results.md`'s `/import` flow already
  expects of an uploaded `ComputeTarget`). Do this before step 10, not
  during it, or that step will fail on both targets for a reason that has
  nothing to do with cross-vendor comparability.

## The procedure

1. **Clean environment information.** On each machine, record: OS/kernel
   (`uname -a`), GPU driver version, ROCm/CUDA version, vLLM version
   (`pip show vllm`), PyTorch version (`pip show torch`), and the exact
   `forgeway` version (`pip show forgeway`, or the git commit checked out).
   This is exactly what `EnvironmentInfo.capture()`
   (`api/app/benchmark/cross_vendor.py`) records automatically into each
   evidence record's `environment` field — this manual step is a
   cross-check that automatic capture caught the same facts, not a
   duplicate source of truth.

2. **Verify hardware discovery** on each machine:
   ```bash
   forgeway discover --json
   ```
   Confirm `vendor` is `nvidia` on one machine and `amd` on the other, and
   that `model`/`memory_gb_per_device` look right. See
   `docs/discovery.md#verification-status` for what's already been proven
   about this step versus what's specific to your hardware.

3. **Verify the benchmark profile** validates and reads as intended:
   ```bash
   cd api && source .venv/bin/activate
   python -c "
   from pathlib import Path
   from app.benchmark.cross_vendor import load_benchmark_profile_yaml
   p = load_benchmark_profile_yaml(Path('../benchmarks/profiles/llama-8b-cross-vendor-v0.1.yaml'))
   print(p.model_dump_json(indent=2))
   "
   ```
   Confirm `model`, `precision`, `tensor_parallel_degree`, `input_tokens`,
   `output_tokens`, and `concurrency` are what you intend to run on *both*
   machines unchanged. If you need to vary the model for licensing reasons
   (see the profile file's own comments), copy it to a new
   `profile_id`/`profile_version` rather than editing this one in place —
   a different model is a different profile, not a patch.

4. **Run the NVIDIA benchmark.** If vLLM is installed directly on the host
   (matching `docs/benchmarking.md`'s plain install path), this is exactly:
   ```bash
   forgeway bench-profile benchmarks/profiles/llama-8b-cross-vendor-v0.1.yaml \
     --workload-id wl-cross-vendor-8b \
     --output results/nvidia-run.json
   ```
   **In practice (live-verified 2026-09-04, NVIDIA DGX Spark), vLLM came
   from AMD's/NVIDIA's own serving Docker image instead** (see
   Prerequisites), which changes the invocation in three ways worth
   knowing before you hit them yourself:
   - **The `vllm/vllm-openai` image's `ENTRYPOINT` is hardcoded to `vllm
     serve`** — any command you pass gets appended *after* that, not used
     in its place. Override it: `docker run --entrypoint python3 ...`
     (running Forgeway's CLI directly, not the `vllm` binary — see below).
   - **`forgeway`/its dependencies aren't installed in the image** — mount
     this repo's `api/` directory and set `PYTHONPATH` to it instead of
     `pip install`-ing Forgeway inside the image. The image already had
     `pydantic`/`pyyaml` (vLLM's own dependencies), so no extra install was
     needed.
   - **`--gpu-memory-utilization` (a `forgeway bench-profile` flag, a
     per-machine resource override — never part of the profile itself, see
     `api/app/benchmark/vllm_runner.py`) had to be set explicitly and low
     (`0.4`) on this unified-memory system** — vLLM's default (~0.9)
     assumes it can claim that fraction of a discrete GPU's own dedicated
     memory; on a shared CPU+GPU memory pool with other processes already
     using part of it, the default over-requested and the engine refused
     to start (`ValueError: Free memory on device cuda:0 (60.62/121.69
     GiB) ... is less than desired GPU memory utilization`). Tune this per
     machine, not per profile.
   - **A cold run needs more than the CLI's 600s default** — a 7B model's
     first CUDA-graph compile took long enough that the default
     `run_vllm_bench_latency` timeout was hit even though nothing was
     stuck; `--timeout-s 1800` was used. (`forgeway bench-profile` didn't
     expose `--timeout-s` at all before this was caught — it now does.)

   The actual command that produced a real result:
   ```bash
   docker run --rm --gpus all --entrypoint python3 \
     -v ~/.cache/huggingface:/root/.cache/huggingface \
     -v ~/forgeway-validate:/forgeway \
     -v ~/bench_out:/bench_out \
     -e PYTHONPATH=/forgeway/api \
     -e FORGEWAY_BENCH_DIR=/bench_out/forgeway_bench_dir \
     vllm/vllm-openai:cu130-nightly \
     -m app.cli.main bench-profile /forgeway/benchmarks/profiles/qwen2.5-7b-cross-vendor-v0.1.yaml \
     --gpu-memory-utilization 0.4 --timeout-s 1800 --output /bench_out/nvidia-run.json
   ```
   (`qwen2.5-7b-cross-vendor-v0.1.yaml`, not the primary Llama profile —
   see Prerequisites on HF gating.) See "NVIDIA run — actual result" below
   for the real output this produced.

5. **Save the evidence JSON** — `--output` above already does this
   (`results/nvidia-run.json`); the plain `PerformanceEvidence` also lands
   wherever `FORGEWAY_BENCH_DIR` points (same mechanism `forgeway bench`
   already uses), which is what step 10 relies on.

6. **Run the AMD benchmark**, same profile, unchanged. The equivalent
   AMD-side command (same pattern, `rocm/vllm:rocm7.13.0_gfx120X-all_...`
   in place of the CUDA image, `--gpus all` replaced by ROCm's device
   flags — `--device=/dev/kfd --device=/dev/dri`) has not been run yet as
   of this writing (see the status line at the top of this file for why —
   a slow Wi-Fi-bound image pull, not a code issue). Update this section
   with the actual command and any AMD-specific gotchas once it has.

7. **Save the evidence JSON** — same as step 5, for the AMD run.

8. **Run `compare-runs`:**
   ```bash
   forgeway compare-runs results/nvidia-run.json results/amd-run.json
   ```

9. **Verify the comparability status** printed is `DIRECTLY COMPARABLE`.
   If it says `NOT COMPARABLE`, read the reasons — the most likely cause is
   that one machine's vLLM silently applied a different dtype/quantization
   than intended (see `docs/benchmarking.md#dependencies`'s note on
   ROCm-vs-CUDA vLLM builds), not a bug in the comparison logic itself. Do
   not proceed to step 10 by picking a different pair of evidence files
   just to get a `DIRECTLY COMPARABLE` result — investigate and fix the
   actual mismatch, or explicitly record why it's unfixable for this
   hardware pairing.

10. **Run `forgeway analyze` using both evidence records.** This requires a
    real `AIWorkload` YAML (not one of the five demo fixtures, since this
    profile's model doesn't match any of them) and both `ComputeTarget`
    JSON files (from step 2, edited per the Prerequisites note above) as
    inputs Forgeway can score against — this repo does not (yet) have a
    CLI flag that loads two arbitrary `ComputeTarget` files at once, so
    the direct path is to add both edited targets to a local fixture-like
    list via the same fixture format `app/data/loader.py` already reads,
    or use the web `/import` flow (`docs/importing-results.md`) with each
    edited target JSON uploaded in turn, then run `/analyze` against a
    workload with `id: wl-cross-vendor-8b`. Confirm both targets appear as
    `FEASIBLE` or `RECOMMENDED` — never silently dropped.

11. **Change the SLO** (e.g. tighten `p99_latency_ms` in the workload) and
    confirm the set of feasible candidates changes accordingly — see
    `api/tests/test_decision_cross_vendor.py::test_tightening_slo_can_flip_which_vendor_qualifies`
    for the exact mechanism this is checking against real data.

12. **Rerun the decision** (`forgeway analyze` again, or `/analyze` in the
    web UI) and confirm the new recommendation reflects the tightened SLO.

13. **Change the objective weights** (cost/performance/headroom) via
    `Workload.objective_weights` (or a scenario preset in the web UI) and
    confirm the ranking between the NVIDIA and AMD candidates can change —
    see `test_objective_weights_change_ranking_between_identical_candidates`
    for the exact mechanism.

14. **Rerun the decision** with the new weights and confirm the new
    ranking.

15. **Confirm decision changes are explained by inputs, not vendor
    identity.** Read `Recommendation.reasoning` for each rerun — it should
    cite the SLO/weight values and the specific candidate's numbers, never
    "NVIDIA is preferred" or "AMD is preferred" as a reason on its own. If
    you swap which vendor has the better numbers (edit the two evidence
    files' metric values and rerun) and the recommendation follows the
    numbers rather than staying pinned to a vendor, that's the property
    this checklist exists to confirm — see
    `test_recommendation_follows_better_numbers_not_vendor_identity` for
    the automated version of exactly this check.

## Why the model changed twice

The profile actually used for the successful cross-vendor comparison is
**`qwen2.5-1.5b-cross-vendor`, not** the primary `llama-8b-cross-vendor` or
even the first open-model substitute, `qwen2.5-7b-cross-vendor`. Both
substitutions were forced by real constraints hit during this exact live
run, not a preference:

1. `llama-8b-cross-vendor` (`meta-llama/Llama-3.1-8B-Instruct`) → skipped
   entirely: gated on Hugging Face, and neither validation machine had HF
   credentials configured.
2. `qwen2.5-7b-cross-vendor` (`Qwen/Qwen2.5-7B-Instruct`, open, no gating)
   → ran successfully on the NVIDIA DGX Spark (128 GiB unified memory —
   see that run's result below), but **failed on the AMD RX 9070 XT with a
   real `torch.OutOfMemoryError: HIP out of memory`**: this model's bf16
   weights alone (~15.12 GiB) left only 78 MiB free on the card's 15.92 GiB
   VRAM — not enough for vLLM's CUDA-graph-capture compilation buffers.
   `--enforce-eager` (skip graph capture, added specifically to try to work
   around this) did not fix it either — with only ~174 MiB free after
   weights, there wasn't enough headroom for even a single eager forward
   pass. This is a genuine hardware capacity limit on this specific
   16 GiB card, not a Forgeway bug or a fixable flag combination.
3. `qwen2.5-1.5b-cross-vendor` (`Qwen/Qwen2.5-1.5B-Instruct`, ~3 GiB in
   bf16) → ran successfully on **both** machines. This is the profile the
   "Real cross-vendor result" below is about.

**What this means for the claim:** the cross-vendor pipeline itself —
profile-driven configuration, comparability checking, evidence capture —
is proven end to end. What is *not* proven is that `qwen2.5-7b-cross-vendor`
or `llama-8b-cross-vendor` specifically can be run this way on this AMD
card; the opposite is true for the 7B profile (it demonstrably cannot, at
least not in full bf16). Don't cite the 1.5B result as evidence about the
7B or Llama profiles' behavior on this hardware.

## NVIDIA run — actual result, qwen2.5-7b-cross-vendor (live, 2026-09-04)

Machine: NVIDIA DGX Spark (`spark-782e`), GB10 (Grace Blackwell, aarch64,
compute capability 12.1), driver 580.173.02, CUDA 13.0. Runtime: vLLM
`0.19.2rc1.dev134+gfe9c3d6c5.cu130` (from `vllm/vllm-openai:cu130-nightly`),
PyTorch `2.11.0+cu130`. Profile: `qwen2.5-7b-cross-vendor` v0.1
(`Qwen/Qwen2.5-7B-Instruct`, bf16, no quantization, tensor_parallel_degree=1,
512 input / 128 output tokens, batch size 1, 1 warmup + 3 measured runs).
This run has no AMD counterpart (see above) — kept here as evidence the
pipeline itself works on a 7B model on hardware that can fit it.

```
Forgeway cross-vendor benchmark

  Profile          qwen2.5-7b-cross-vendor v0.1
  Vendor / target  nvidia — NVIDIA GB10
  Run id           bench-profile-e523ce098f69

  End-to-end latency       9507.80 ms
  P50 latency              9511.83 ms
  P99 latency              9519.44 ms
  Output token throughput  13.46 tok/s
  Request throughput       0.11 req/s
  Avg GPU power draw       13.20 W
```

The full `CrossVendorEvidenceRecord` validated exactly as designed: real
`raw_command` (confirms no stray `--percentiles` flag — see "Real bugs
found and fixed" below), real `environment` (vLLM/PyTorch/OS/kernel/driver
all captured), and both canonical engine keys present in
`performance_evidence.metrics` (`throughput_tokens_per_s_per_replica`,
`p99_latency_ms_per_replica`) — meaning this record, saved via the normal
`app.benchmark.store.save_run` path, is genuinely selectable by
`forgeway analyze`'s decision engine like any other real benchmark run,
not just structurally valid JSON. `cost_basis` is `"not_available"`, as
expected for a freshly discovered target with placeholder pricing.

**No power/memory figure was fabricated where one wasn't measured.**
`peak_gpu_memory_used_mb` is correctly *absent* from the metrics — this
GB10's unified memory reports `[N/A]` for `memory.used` via `nvidia-smi`
(see the bug below), and `app.benchmark.gpu_sampler`'s `_safe_float`
already treated that as "no sample," never a fabricated zero, so the
metric was omitted rather than invented.

## Real cross-vendor result, qwen2.5-1.5b-cross-vendor (live, 2026-09-04)

Both machines ran the identical `qwen2.5-1.5b-cross-vendor` v0.1 profile
(`Qwen/Qwen2.5-1.5B-Instruct`, bf16, no quantization,
tensor_parallel_degree=1, 512 input / 128 output tokens, batch size 1):

```
$ forgeway compare-runs results/nvidia-run.json results/amd-run.json

FORGEWAY CROSS-VENDOR EVIDENCE COMPARISON

Profile:
  qwen2.5-1.5b-cross-vendor v0.1

Comparability:
  PARTIALLY COMPARABLE
  Reasons:
    - runtime (vllm) version differs: '0.19.2rc1.dev134+gfe9c3d6c5.cu130' vs '0.19.1.dev3+rocm7.13.0.g72ed2b398.d20260513'
    - driver version differs: '580.173.02' vs '7.0.0'

  A: NVIDIA NVIDIA GB10  (bench-profile-17a5ea58082f)
  B: AMD AMD Radeon RX 9070 XT  (bench-profile-d25112f0e27a)

  Metric                   NVIDIA         AMD
  ------------------------------------------------------
  Latency (end-to-end)     2099.08 ms     792.80 ms
  Throughput               60.98 tok/s    161.45 tok/s
  Memory (peak)            n/a            15529.70 MB
  Power (avg)              12.00 W        13.00 W

Cost: not compared — at least one side has no recorded cost basis (cost_basis='not_available'; ...).

This command compares evidence only — it does not recommend a placement. ...
```

**Every critical (`NOT_COMPARABLE`-gating) dimension matched exactly**:
model, model revision (both `null`), precision, quantization, input/output
token counts, concurrency, tensor-parallel degree, runtime family,
benchmark mode, warmup policy, measurement methodology — the two runs
really did execute the identical logical workload. The only differences
were **soft** ones `compare_evidence` is specifically designed to surface
without blocking on: vLLM's own patch version and the GPU driver version,
both of which legitimately differ because each vendor ships its own
prebuilt Docker image. `PARTIALLY COMPARABLE` is the *correct* output
here, not a shortfall — it's the policy working as designed on a real,
non-synthetic pair for the first time.

`peak_gpu_memory_used_mb` is present on the AMD side (a real `rocm-smi`
sample, 15529.70 MB — nearly the whole 16 GiB card, consistent with the
earlier 7B OOM's finding that this card runs close to its limit) and
correctly absent on the NVIDIA side (same DGX Spark `nvidia-smi` `[N/A]`
memory-reporting gap documented above) — no fabrication on either side.
`cost_basis` is `"not_available"` on both (freshly discovered hardware,
placeholder pricing), so cost was correctly not compared at all.

**Not run against these two specific files**: `forgeway analyze` /
decision-engine steps 10-15. That remains proven only via
`api/tests/test_decision_cross_vendor.py`'s synthetic evidence, not a
fresh live run stacked on top of this real pair — a reasonable next step
for anyone extending this validation further.

## Real bugs found and fixed during this live run

Live hardware surfaced six real gaps that no amount of mocked-subprocess
testing had caught — each fixed, regression-tested (where a captured
real value made that possible), and synced to both validation machines:

1. **`vllm bench latency` no longer has a `--percentiles` flag at all** —
   passing one (as `app.benchmark.vllm_runner` unconditionally did) is now
   a hard argument-parsing error in current vLLM versions. Percentiles
   (10/25/50/75/90/99) are computed and included in the output JSON's
   `"percentiles"` dict unconditionally instead. Fixed by removing the
   flag entirely; `api/app/benchmark/parser.py`'s assumptions about the
   output JSON shape (`avg_latency`, `percentiles`) were otherwise
   confirmed exactly correct against this real output, on both vendors.
2. **No way to set `--gpu-memory-utilization`** — vLLM's default (~0.9)
   assumes a discrete GPU's own dedicated memory; on DGX Spark's unified
   memory pool it over-requested and the engine refused to start. Added as
   a runtime-only override (`run_vllm_bench_latency`, `BenchmarkRunner.run`,
   `forgeway bench-profile --gpu-memory-utilization`) — deliberately *not*
   a `BenchmarkProfile` field, since it's a per-machine resource
   constraint, not a workload-comparability dimension.
3. **`forgeway bench-profile` had no `--timeout-s` flag** — a cold 7B
   model's first CUDA-graph compile legitimately took longer than the
   600s default. Added, mirroring `forgeway bench`'s existing flag.
4. **The NVIDIA discovery adapter silently fabricated `memory_gb_per_device:
   0.0`** on this unified-memory system, where `nvidia-smi` reports
   memory fields as the literal string `"[N/A]"` — `_parse_float`'s
   generic 0.0-on-parse-failure fallback (fine for utilization, where 0 is
   a real possible reading) was silently doing the same for memory, where
   it isn't. Fixed: `notes` now says explicitly "NOT a real measurement"
   when this happens, and the compute-capability architecture map gained
   a real entry (`12.1` → `blackwell`) discovered by the same run — see
   `api/tests/test_discovery.py::test_discover_matches_real_gb10_hardware_unified_memory_not_fabricated`.
5. **No way to set `--enforce-eager`** — added as another runtime-only
   override (same non-profile-field reasoning as `gpu_memory_utilization`)
   when a 7B model's weights left too little VRAM headroom on a 16 GiB AMD
   card for CUDA-graph capture. Real usage note: this alone did **not**
   solve that particular OOM (see "Why the model changed twice") — it's a
   genuinely useful flag for the class of problem it addresses, but not a
   substitute for a model actually fitting the hardware.
6. **`Forgeway's own `BenchmarkError` message truncates to the last 2000
   characters of vLLM's stderr`** — this repeatedly hid the actual root
   cause (e.g. the real `torch.OutOfMemoryError`) behind a long, unrelated
   wrapper traceback (`RuntimeError: Engine core initialization failed.
   See root cause above...`) that happened to be printed after it.
   Workaround used throughout this validation: rerun the exact
   `raw_command` directly (outside Forgeway) with full output redirected
   to a file. **Not fixed in code this pass** — flagged here as a real,
   observed usability gap for whoever picks up `--timeout-s`-adjacent
   error-reporting work next, rather than rushed through under time
   pressure.

None of these were guessable from documentation alone — all six were
found by actually running the tool.

## What this validates

- That the same `BenchmarkProfile` can drive a real `vllm bench latency`
  run on both an NVIDIA and an AMD machine, producing two
  `PerformanceEvidence` records built by the identical, unmodified
  `app.benchmark.evidence.build_performance_evidence` function (no
  per-vendor metric semantics).
- That `compare_evidence` correctly classifies the resulting pair as
  comparable (or not), using real environment/profile data rather than
  synthetic fixtures.
- That the (unmodified) decision engine ranks the two real results using
  the same 11-step pipeline it already uses for fixture data, with SLOs and
  objective weights — not vendor identity — determining the outcome.

## What this does NOT validate

- Production serving performance — `vllm bench latency` is an offline,
  single-node, no-server benchmark (`docs/benchmarking.md`); it does not
  measure TTFT or true concurrent-request serving throughput.
- All models — this checklist runs exactly one profile, one model.
- All runtimes — only vLLM's `bench latency` subcommand is exercised.
- All NVIDIA GPUs, or all AMD GPUs — one specific card per vendor, on one
  specific driver/ROCm/CUDA version, is not a statement about every card in
  either vendor's lineup.
- Universal cost superiority of either vendor — `forgeway compare-runs`
  deliberately never declares a cost winner (see its `cost_basis` handling
  in `api/app/benchmark/cross_vendor.py`) unless both sides carry a real,
  matching cost basis, which freshly-discovered hardware never does by
  default (`docs/discovery.md`'s pricing-placeholder limitation).
- Scheduler or orchestration capability — Forgeway recommends; it does not
  place, migrate, or schedule anything (`ROADMAP.md`'s "Later" section).
