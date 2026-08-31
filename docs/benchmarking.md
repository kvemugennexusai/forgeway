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

- **Hardware:** local NVIDIA CUDA systems only (reuses
  [`forgeway discover`](discovery.md)'s `NvidiaDiscoveryAdapter` — see that
  doc for supported-platform details).
- **Runtime:** [vLLM](https://github.com/vllm-project/vllm) only, via its
  `vllm bench latency` subcommand.
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
`api/app/benchmark/__init__.py`. Adding AMD, another runtime, or a second
model-specific path is future work, not this one.

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
| GPU memory usage | `peak_gpu_memory_used_mb` | the peak of real `nvidia-smi` samples polled once per second while the benchmark subprocess runs (not a single before/after snapshot) |
| Average power | `avg_gpu_power_draw_w` | the mean of those same real `nvidia-smi` power-draw samples — a genuine time-averaged figure, not a two-point guess. Omitted entirely if the driver reports `N/A` for power (common on some GPU/driver combinations without power-management support) |
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

- An NVIDIA GPU with enough VRAM for the model — **Llama 3.1 8B Instruct
  needs roughly 16GB+ VRAM** for its weights in bf16/fp16 plus KV cache
  headroom; less with quantization, but this runner doesn't configure
  quantization for you.
- NVIDIA driver + `nvidia-smi` on `PATH` (same requirement as
  `forgeway discover`).
- [vLLM](https://pypi.org/project/vllm/) installed in the same environment
  as `forgeway` (`pip install vllm`) — a large package with its own CUDA
  and PyTorch requirements; see vLLM's own installation docs for your
  platform.
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
  installation.** There is no CUDA GPU in this repository's development
  environment, so `api/app/benchmark/parser.py`'s key names
  (`avg_latency`, `percentiles`) reflect vLLM's documented
  `vllm bench latency --output-json` shape as best known at the time this
  was written, not a shape confirmed by actually running it. The parser is
  written defensively — a missing or renamed key results in that metric
  being omitted (or, for the one truly required field, a clear
  `BenchmarkError`), never a fabricated value — but a full schema mismatch
  in a future vLLM release is a real, plausible risk.
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
