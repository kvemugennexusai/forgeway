# Benchmarking — `forgeway bench`

Forgeway's first real benchmark runner: measure one LLM inference workload
on the local NVIDIA GPU and normalize the result into
[`PerformanceEvidence`](schemas.md#3-performanceevidence) (`forgeway/v0.1`,
`provenance: MEASURED`).

```
$ forgeway bench \
    --model meta-llama/Llama-3.1-8B-Instruct \
    --input-tokens 512 \
    --output-tokens 128 \
    --concurrency 1
```

## Scope (v0.1)

- **Hardware:** local NVIDIA CUDA systems (reuses [`forgeway
  discover`](discovery.md)'s `NvidiaDiscoveryAdapter`) and local AMD ROCm
  systems (reuses its `RocmDiscoveryAdapter`) — see that doc for
  supported-platform details. `forgeway bench` uses whichever
  `forgeway discover` finds first to pick both the compute target and the
  matching GPU telemetry sampler (`nvidia-smi` or `rocm-smi` — see "GPU
  vendor dispatch" below).
- **Runtime:** [vLLM](https://github.com/vllm-project/vllm) only, via its
  `vllm bench latency` subcommand — the command itself is identical on
  either vendor; only the *install* of vLLM differs (see Dependencies).
- **Model:** any model `vllm bench latency --model <id>` can load, but this
  path is built and prioritized for
  **`meta-llama/Llama-3.1-8B-Instruct`**, as scoped for this milestone.
- **Workload id:** the saved evidence's `workload_id` defaults to `--model`
  (never a real Forgeway workload id, so never selectable by the placement
  engine for any workload — but also never colliding with one). Pass
  `--workload-id <id>` to tag the evidence with a real, existing workload
  id instead — only honest when `--model` actually corresponds to that
  workload (same family/parameter count). See
  [`docs/importing-results.md`](importing-results.md#tagging-evidence-with-a-real-workload-id).

This is deliberately **one benchmark path**, not a generic framework — see
`api/app/benchmark/__init__.py`. Adding another runtime or a second
model-specific path is future work, not this one.

## GPU vendor dispatch

`vllm bench latency` runs identically regardless of vendor — PyTorch/HIP
handle device dispatch underneath the benchmark itself, so
`api/app/benchmark/vllm_runner.py` doesn't branch on vendor for the
subprocess it launches. The only vendor-specific piece is **GPU telemetry
sampling** (peak memory, average power) while the benchmark runs:
`app/benchmark/gpu_sampler.py` (`nvidia-smi`) or
`app/benchmark/rocm_gpu_sampler.py` (`rocm-smi`), selected by
`run_vllm_bench_latency`'s `gpu_vendor` parameter — `forgeway bench` sets it
automatically from whatever `forgeway discover` found
(`ComputeTarget.vendor`). `PerformanceEvidence`'s memory/power metric
`source` strings name whichever tool actually produced the sample
(`api/app/benchmark/evidence.py::_TELEMETRY_TOOL_BY_VENDOR`).

**Verification status of the ROCm side, precisely (this is the one place
it's stated in full — see `docs/discovery.md#verification-status` for the
five states used and the matching discovery-side status; README.md and
ROADMAP.md summarize this section rather than restating it independently):**

- **`rocm_gpu_sampler.sample_gpu_once()`, `run_vllm_bench_latency(...,
  gpu_vendor="amd")`'s full dispatch path (the exact code `forgeway bench`
  itself calls), and an actual `vllm bench latency` run on ROCm: all LIVE
  VERIFIED.** A real run completed end to end on a real AMD Radeon RX 9070
  XT (inside AMD's official `rocm/vllm` Docker image, via `forgeway
  bench-profile` — see `docs/cross-vendor-validation.md`), producing a
  real `PerformanceEvidence` record with a real `peak_gpu_memory_used_mb`
  reading (15,529.70 MB) and real latency/throughput metrics. The one
  thing not literally exercised is the plain `forgeway bench` CLI
  entrypoint (`cmd_bench`) itself — a thin wrapper around the exact same
  now-proven functions, invoked via `forgeway bench-profile` instead in
  this run.
- **That same sampler function's persisted automated test suite
  (`api/tests/test_benchmark_rocm_gpu_sampler.py`) remains IMPLEMENTED BUT
  NOT LIVE VERIFIED, not "tested with captured real output."** Unlike the
  discovery adapter's test suite (which includes a regression test using
  real captured JSON verbatim), this suite still uses hand-built fixtures
  constructed from rocm-smi's documented field names — the live run above
  didn't change this file, only proved the code it tests works for real.
- **`evidence.py`'s `_TELEMETRY_TOOL_BY_VENDOR["amd"]` source-string
  mapping: LIVE VERIFIED** (exercised for real by the same run above,
  producing `source` strings naming `rocm-smi`) — its own dedicated test
  suite (`test_benchmark_evidence.py`) still only covers `vendor="nvidia"`
  directly, though `test_cross_vendor_runners.py`'s `RocmVllmBenchmarkRunner`
  tests do exercise the `vendor="amd"` branch with mocked subprocess output.

## Cross-vendor benchmark profiles

`forgeway bench-profile <profile.yaml>` and `forgeway compare-runs <a.json>
<b.json>` (`api/app/benchmark/cross_vendor.py`) let a single, versioned
`BenchmarkProfile` — e.g.
[`benchmarks/profiles/llama-8b-cross-vendor-v0.1.yaml`](../benchmarks/profiles/llama-8b-cross-vendor-v0.1.yaml)
— drive the *same* `vllm bench latency` configuration on an NVIDIA machine
and an AMD machine, and then check whether the two resulting evidence
records are honestly comparable before anyone treats them as such. See
[`docs/cross-vendor-validation.md`](cross-vendor-validation.md) for the
full validation procedure.

**Precise status: LIVE VERIFIED.** `forgeway bench-profile` ran for real on
both a real NVIDIA DGX Spark and a real AMD Radeon RX 9070 XT against the
identical `qwen2.5-1.5b-cross-vendor` profile, and `forgeway compare-runs`
correctly classified the pair `PARTIALLY COMPARABLE` — every critical
dimension matched (model, precision, quantization, tokens, concurrency,
tensor parallelism); only soft dimensions (vLLM patch version, driver
version) differed, exactly as expected across two independently-built
vendor Docker images. `BenchmarkProfile` validation, `compare_evidence`'s
comparability policy, and both `CudaVllmBenchmarkRunner` /
`RocmVllmBenchmarkRunner` are also covered by unit and integration tests
(`api/tests/test_cross_vendor_profile.py`,
`test_cross_vendor_comparability.py`, `test_cross_vendor_runners.py`,
`test_cli_bench_profile.py`, `test_decision_cross_vendor.py`) using mocked
subprocess output — the live run proved the real thing works; the tests
keep proving it on every future change without needing hardware. See
`docs/cross-vendor-validation.md` for the full story, including why the
model changed twice (the gated primary profile, then a 7B open-model
substitute whose bf16 weights didn't fit the AMD card's 16GB VRAM) and
every real bug the live run surfaced along the way. It is accurate to say
**"Forgeway has been live-validated running the same benchmark profile on
NVIDIA and AMD hardware."** What's *not* separately proven: `forgeway
analyze`/the decision engine consuming these two specific saved records
(that behavior is proven via synthetic evidence in
`test_decision_cross_vendor.py`, not a fresh live run on top of these
files), and the 7B/Llama-8B profiles running successfully on this
particular AMD card (the opposite was demonstrated for the 7B one).

Two design points worth being explicit about:

- **Nothing here changes the decision engine.** `app.core.engine` and
  `app.engine.decision` are untouched — `api/tests/test_decision_cross_vendor.py`
  proves (with synthetic NVIDIA + AMD `ComputeTarget`/`PerformanceEvidence`
  pairs) that the existing, unmodified pipeline already ranks two vendors'
  MEASURED evidence by SLO and objective weights alone, with no
  vendor-specific scoring anywhere.
- **`forgeway compare-runs` never declares a winner.** It shows both
  records' metrics side by side and states comparability explicitly
  (`DIRECTLY COMPARABLE` / `PARTIALLY COMPARABLE` / `NOT COMPARABLE`, with
  reasons) — a recommendation requires workload SLOs and objectives, which
  is `forgeway analyze`'s job, not this command's. Cost is shown only when
  both sides carry a real, matching `cost_basis`; a freshly discovered
  target's placeholder pricing (`docs/discovery.md`) means cost is usually
  reported as "not compared," never guessed into a false winner.

## Why `vllm bench latency`, and what it does and doesn't measure

vLLM ships three benchmark subcommands: `latency`, `throughput`, and
`serve`. `serve` measures a real OpenAI-compatible server under load
(TTFT, inter-token latency, request throughput) but requires standing up
and tearing down a server process alongside the benchmark client — two
cooperating processes to orchestrate reliably. `latency` runs a single,
self-contained offline generation pass — one subprocess, no server
lifecycle to manage — which is why it was chosen for a first, reliable
path.

The tradeoff: **`vllm bench latency` cannot report time-to-first-token
(TTFT)** — it measures full-completion latency, not a streaming response,
so there is no "first token" event to time. Per Forgeway's
never-fabricate-a-metric rule, TTFT is simply never included in the
resulting `PerformanceEvidence` for this path — not omitted silently: both
the human-readable CLI output and this doc call it out explicitly.

## What's captured

| Requested | Captured as | How |
|---|---|---|
| End-to-end latency | `end_to_end_latency_ms` | vLLM's own reported average latency across `--iterations` timed runs |
| P50 / P99 | `p50_latency_ms`, `p99_latency_ms` | vLLM's own percentiles — computed and included in its output JSON unconditionally (live-verified 2026-09-04; current vLLM versions have no `--percentiles` flag at all — see `app/benchmark/vllm_runner.py`'s module constants) |
| Output token throughput | `output_token_throughput_tokens_per_s` | **derived**, not measured directly: `(output_tokens × concurrency) ÷ measured avg latency` — the same arithmetic any latency benchmark uses to turn a stopwatch time into a rate |
| Request throughput | `request_throughput_requests_per_s` | derived the same way: `concurrency ÷ measured avg latency` |
| GPU memory usage | `peak_gpu_memory_used_mb` | the peak of real `nvidia-smi`/`rocm-smi` samples (by vendor) polled once per second while the benchmark subprocess runs (not a single before/after snapshot) |
| Average power | `avg_gpu_power_draw_w` | the mean of those same real power-draw samples — a genuine time-averaged figure, not a two-point guess. Omitted entirely if the driver/tool reports no value for power (common on some GPU/driver combinations without power-management support) |
| TTFT | *not captured* | see above — not measurable by this benchmark path |
| GPU model, driver, etc. | via `compute_target_id` | cross-reference the `ComputeTarget` from `forgeway discover` — not duplicated into `PerformanceEvidence` itself |

Every metric's `confidence` follows a fixed convention, not a computed
statistical interval: **95** for anything vLLM reports directly or is
arithmetically derived from it, **90** for peak GPU memory, **85** for
average power (sampled by a separate, best-effort poller, not vLLM
itself). `PerformanceEvidence.confidence` (the top-level field) is the
weakest of whichever metrics actually made it into the record — the same
weakest-link convention used everywhere else in Forgeway.

## Dependencies

- A GPU with enough VRAM for the model — **Llama 3.1 8B Instruct needs
  roughly 16GB+ VRAM** for its weights in bf16/fp16 plus KV cache headroom;
  less with quantization, but this runner doesn't configure quantization
  for you.
- **NVIDIA:** the NVIDIA driver + `nvidia-smi` on `PATH` (same requirement
  as `forgeway discover`), and [vLLM](https://pypi.org/project/vllm/)
  installed the standard way (`pip install vllm`) — a large package with
  its own CUDA/PyTorch requirements, but a single `pip install`.
- **AMD ROCm:** the ROCm stack + `rocm-smi` on `PATH` (same requirement as
  `forgeway discover`'s ROCm adapter), and **a ROCm-capable vLLM build —
  materially more involved than the NVIDIA path.** `pip install vllm`
  installs vLLM's CUDA build; it will not run on an AMD GPU. Getting `vllm
  bench latency` actually working on ROCm requires either vLLM's published
  ROCm Docker image or building vLLM from source against a ROCm-enabled
  PyTorch — see [vLLM's ROCm installation
  docs](https://docs.vllm.ai/en/latest/getting_started/installation/gpu.html)
  for the current instructions, which change more often than this file
  does. `forgeway bench` itself doesn't attempt to install or detect any of
  this for you; `is_vllm_available()` only checks that a `vllm` binary is
  on `PATH` at all, not that it was built for the GPU actually present.
- **A Hugging Face account with access to the gated Llama 3.1 license**,
  and either `huggingface-cli login` run once or an `HF_TOKEN` environment
  variable set. `meta-llama/Llama-3.1-8B-Instruct` will not download
  without this — vLLM will report a clear authentication/access error,
  which surfaces through this runner as a `BenchmarkError`.

## Installing and running

```bash
cd api
source .venv/bin/activate
pip install -r requirements.txt   # registers the `forgeway` console script
pip install vllm                  # not in requirements.txt — heavy, CUDA-specific,
                                  # and irrelevant to everything else `forgeway` does
huggingface-cli login             # or: export HF_TOKEN=...

forgeway bench \
  --model meta-llama/Llama-3.1-8B-Instruct \
  --input-tokens 512 \
  --output-tokens 128 \
  --concurrency 1
```

Also supported:

```bash
forgeway bench --model meta-llama/Llama-3.1-8B-Instruct --json   # full PerformanceEvidence JSON
forgeway runs                                                     # list locally stored runs
```

## Expected runtime

**Estimated, not measured** — this repository's development environment
has no CUDA GPU, so nothing below has been timed against real hardware:

- Model load (first run): roughly 30s–2min, depending on disk speed and
  whether the model is already cached locally by Hugging Face's hub cache.
- The benchmark itself, at the default `--iterations 3
  --warmup-iterations 1` for the example command above (512 input tokens,
  128 output tokens, batch size 1): likely under a minute on a modern
  datacenter GPU (e.g. H100, A100), once the model is loaded.
- Total default `--timeout-s` is 600s (10 minutes) — generous headroom for
  slower hardware or a larger `--concurrency`/`--output-tokens`, not a
  reflection of expected normal runtime.

## Where results are saved

`~/.forgeway/benchmarks/<run_id>.json` (the `PerformanceEvidence` record)
and `<run_id>.raw_vllm_output.json` (the exact JSON vLLM produced for that
run) — see "Reproducibility caveats" below for why the raw file is kept.
Override the directory with the `FORGEWAY_BENCH_DIR` environment variable.
`forgeway runs` lists everything found there.

## Current limitations

- **One model path prioritized, not enforced.** `--model` accepts any
  string vLLM can load; only `meta-llama/Llama-3.1-8B-Instruct` is what
  this milestone actually prioritized and reasoned about.
- **No TTFT** (see above) — a real limitation of `vllm bench latency`
  specifically, not of Forgeway's schema (`PerformanceEvidence.metrics` is
  an open dict; a future `serve`-based path could add it).
- **GPU telemetry is sampled, not continuous.** Peak memory and average
  power come from polling `nvidia-smi` once per second
  (`--sample-interval` isn't exposed as a CLI flag yet) while the
  subprocess runs — real measurements, but a coarser picture than
  instrumenting the process itself would give.
- **No pre-flight VRAM check.** If the model doesn't fit, vLLM will fail
  with its own out-of-memory error, surfaced here as a `BenchmarkError`
  with vLLM's stderr tail included — there's no earlier, friendlier check.
- **Single-node, single-GPU only.** `--device-index` selects which GPU to
  sample telemetry from and matches what `--batch-size` runs on, but there
  is no multi-GPU tensor-parallel orchestration here.
- **The engine's canonical metric keys are aliased conditionally, not
  always.** `forgeway bench` saves its own descriptive keys
  (`end_to_end_latency_ms`, `output_token_throughput_tokens_per_s`, etc.)
  *and* the decision engine's canonical keys
  (`p99_latency_ms_per_replica` / `throughput_tokens_per_s_per_replica` —
  see `docs/decision-engine.md`). Throughput is always aliased (it's
  arithmetically derived either way); the P99 latency alias is only added
  when a real P99 percentile was actually captured (`--percentiles`
  including `99`) — an average latency is never relabeled as a P99
  figure, since that would assert a statistical equivalence that isn't
  true. A run without a captured P99 still saves and imports correctly; it
  just isn't comparable evidence for the engine yet. See
  `docs/importing-results.md` for how this feeds the web import flow.

## Reproducibility caveats

- **This runner's JSON parsing has now been verified against live vLLM
  installations on both vendors** (live-verified 2026-09-04, via `forgeway
  bench-profile` — see `docs/cross-vendor-validation.md`) — see "GPU
  vendor dispatch" and "Cross-vendor benchmark profiles" earlier in this
  doc for the precise, current status. `api/app/benchmark/parser.py`'s key
  names (`avg_latency`, `percentiles`) matched real output exactly on both
  a real NVIDIA vLLM build and a real ROCm vLLM build; the one real
  surprise that live run caught was a *removed* CLI flag
  (`--percentiles`), not a JSON-shape mismatch — see `app/benchmark/vllm_runner.py`'s
  module constants. The parser remains written defensively regardless — a
  missing or renamed key results in that metric being omitted (or, for the
  one truly required field, a clear `BenchmarkError`), never a fabricated
  value — since a future vLLM release changing this shape again is still a
  real, plausible risk; two live-verified versions are not a guarantee
  against a third, different one.
- **This is exactly why the raw vLLM output is saved alongside the parsed
  record** (`<run_id>.raw_vllm_output.json`) — if a real run's numbers look
  wrong, or `forgeway bench` fails to parse something, that file is the
  ground truth to check first, before assuming this adapter's logic.
- **Confidence values are a fixed convention** (95 / 90 / 85 — see above),
  not a statistically computed interval from run-to-run variance, even
  though vLLM's own multiple iterations could in principle support one.
- **No two runs are guaranteed identical.** GPU clock behavior, thermal
  state, other processes on the machine, and vLLM/CUDA/driver version
  drift over time all affect these numbers — a single `forgeway bench` run
  is one data point, not a certified benchmark result.
