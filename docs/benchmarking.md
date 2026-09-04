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

- **`rocm_gpu_sampler.sample_gpu_once()` (the sampling function itself):
  LIVE VERIFIED.** Run directly, one-off, over SSH against a real AMD
  Radeon RX 9070 XT, and it returned a real reading
  (`GpuSample(power_draw_w=10.0, memory_used_mb=301.6...)`) — confirming
  both the `rocm-smi -d <index> --showmeminfo vram --showpower --json`
  query and the field names it parses (`Average Graphics Package Power
  (W)`, `VRAM Total Used Memory (B)`) against a live device. The same
  session also validated the ROCm discovery adapter
  (`docs/discovery.md#verification-status`).
- **That same function's persisted automated test suite
  (`api/tests/test_benchmark_rocm_gpu_sampler.py`): IMPLEMENTED BUT NOT
  LIVE VERIFIED, not "tested with captured real output."** Unlike the
  discovery adapter's test suite (which now includes a regression test
  using the real captured JSON verbatim), this suite still uses hand-built
  fixtures constructed from rocm-smi's documented field names — the real
  verification above was an ad hoc call, not a change to this file.
- **`run_vllm_bench_latency(..., gpu_vendor="amd")`'s dispatch wrapper, the
  `forgeway bench` CLI path end-to-end on ROCm, and
  `evidence.py`'s `_TELEMETRY_TOOL_BY_VENDOR["amd"]` source-string mapping:
  IMPLEMENTED BUT NOT LIVE VERIFIED.** The live run above called
  `sample_gpu_once()` directly, bypassing this wrapper, `cmd_bench`, and
  the evidence-building step entirely — none of those have been exercised
  against real hardware, and no test fixture exercises the `vendor="amd"`
  branch of `_TELEMETRY_TOOL_BY_VENDOR` either (existing evidence tests use
  `vendor="nvidia"` only).
- **An actual `vllm bench latency` run on ROCm: IMPLEMENTED BUT NOT LIVE
  VERIFIED.** The test machine didn't have vLLM's ROCm build installed
  (see Dependencies below), so neither the subprocess orchestration nor
  the parser's assumptions about vLLM's output shape have been confirmed
  against a live ROCm run.

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
| P50 / P99 | `p50_latency_ms`, `p99_latency_ms` | vLLM's own percentiles, when it reports them (requested via `--percentiles 50,99`) |
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

- **This runner's JSON parsing has not been verified against a live vLLM
  installation.** There is no CUDA or ROCm GPU in this repository's
  development environment, so `api/app/benchmark/parser.py`'s key names
  (`avg_latency`, `percentiles`) reflect vLLM's documented
  `vllm bench latency --output-json` shape as best known at the time this
  was written, not a shape confirmed by actually running it. The parser is
  written defensively — a missing or renamed key results in that metric
  being omitted (or, for the one truly required field, a clear
  `BenchmarkError`), never a fabricated value — but a full schema mismatch
  in a future vLLM release is a real, plausible risk.
- **The ROCm telemetry sampler itself is the one exception to the bullet
  above — see "GPU vendor dispatch" earlier in this doc for the precise,
  current status** (`rocm_gpu_sampler.sample_gpu_once()` has been LIVE
  VERIFIED against a real AMD GPU; its persisted test suite and the
  `forgeway bench` dispatch path around it have not). Stated once there,
  not repeated here, specifically to avoid this file contradicting itself
  the way it previously did.
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
