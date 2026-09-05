# Roadmap

Forgeway is an early public technical preview. This is a concise,
honest snapshot of what's shipped and what's next — not a commitment to
dates. See `README.md` for what "simulated" vs. "real" means for each
item below, and `docs/architecture.md` for the underlying core/product
boundary.

## v0.1 (shipped)

- Decision engine: feasibility → prediction → SLO check → normalize →
  weight → confidence-gate → rank → recommend → explain, over a
  vendor-neutral `ComputeTarget`/`AIWorkload`/`PerformanceEvidence`
  contract (`forgeway/v0.1` — [`docs/schemas.md`](docs/schemas.md)).
- NVIDIA local hardware discovery (`forgeway discover`, via `nvidia-smi`
  — [`docs/discovery.md`](docs/discovery.md)).
- One real benchmark path (`forgeway bench`, `vllm bench latency` on a
  local NVIDIA GPU, `provenance: MEASURED` —
  [`docs/benchmarking.md`](docs/benchmarking.md)).
- CLI placement analysis (`forgeway analyze`) calling the exact same
  engine as the web demo and API.
- Web demo: fixture-driven dashboard, workload analyzer, scenario
  simulation (six presets), and `/import` — upload a real
  discovery/benchmark result and use it in analysis, browser-local only
  ([`docs/importing-results.md`](docs/importing-results.md)).
- AMD ROCm local hardware discovery (`forgeway discover`, via `rocm-smi`
  — [`docs/discovery.md`](docs/discovery.md#amd-rocm-rocm-smi)), the second
  `DiscoveryAdapter` ([`docs/adding-an-accelerator.md`](docs/adding-an-accelerator.md)).
  **LIVE VERIFIED, and its test suite is TESTED WITH CAPTURED REAL OUTPUT**
  (a Radeon RX 9070 XT, RDNA4, over SSH — see
  [`docs/discovery.md`](docs/discovery.md#verification-status) for the
  precise states used and the full detail) — every expected `rocm-smi`
  field name and casing matched, and the real run surfaced a fix:
  architecture now resolves from rocm-smi's own `GFX Version` field (e.g.
  `gfx1201`) instead of guessing from the product name, since that field
  turned out to actually exist and be far more reliable.
- A ROCm benchmark path — `forgeway bench` dispatches its GPU telemetry
  sampler by vendor (`nvidia-smi` or `rocm-smi`,
  `api/app/benchmark/rocm_gpu_sampler.py`); the `vllm bench latency` command
  itself is identical on either vendor. **LIVE VERIFIED end to end** — a
  real run completed on a real AMD Radeon RX 9070 XT (AMD's official
  `rocm/vllm` Docker image, via `forgeway bench-profile`), producing a
  real `PerformanceEvidence` record with a real `peak_gpu_memory_used_mb`
  reading (15,529.70 MB) — see
  [`docs/benchmarking.md`](docs/benchmarking.md#gpu-vendor-dispatch) and
  [`docs/cross-vendor-validation.md`](docs/cross-vendor-validation.md).
  The one thing not literally exercised is the plain `forgeway bench` CLI
  entrypoint itself (`cmd_bench`) — a thin wrapper around the exact same
  now-proven functions, invoked via `forgeway bench-profile` instead. The
  real install gap this surfaced: `pip install vllm` only gets the CUDA
  build; the live run used AMD's official `rocm/vllm` Docker image
  specifically because of that gap.
- A cross-vendor benchmark profile + comparability policy (`forgeway
  bench-profile`, `forgeway compare-runs` —
  [`benchmarks/profiles/llama-8b-cross-vendor-v0.1.yaml`](benchmarks/profiles/llama-8b-cross-vendor-v0.1.yaml),
  [`docs/benchmarking.md#cross-vendor-benchmark-profiles`](docs/benchmarking.md#cross-vendor-benchmark-profiles)):
  one versioned workload definition an NVIDIA and an AMD run can both use
  verbatim, a deterministic `compare_evidence` policy (critical dimensions
  — model/precision/quantization/concurrency/tensor-parallelism/etc. — vs.
  soft ones — runtime/driver version, accelerator count), and proof (via
  synthetic evidence, `api/tests/test_decision_cross_vendor.py`) that the
  unmodified decision engine already ranks NVIDIA and AMD MEASURED evidence
  for the same workload with no vendor-specific scoring. **LIVE VERIFIED**
  — `forgeway bench-profile` ran for real on a real NVIDIA DGX Spark and a
  real AMD Radeon RX 9070 XT against the identical
  `qwen2.5-1.5b-cross-vendor` profile, and `forgeway compare-runs`
  correctly returned `PARTIALLY COMPARABLE` (every critical dimension
  matched; only vLLM patch version and driver version — both soft —
  differed, as expected across independently-built vendor images). See
  [`docs/cross-vendor-validation.md`](docs/cross-vendor-validation.md) for
  the full story — including why the model changed twice (the primary
  profile's Llama 3.1 8B is gated; the first open substitute, Qwen2.5 7B,
  didn't fit the AMD card's 16GB VRAM in bf16 at all) and six real bugs
  the live run found and fixed. It is now accurate to say Forgeway has
  been live-validated running the same benchmark profile on NVIDIA and AMD
  hardware — not yet demonstrated: the 7B/Llama-8B profiles specifically
  succeeding on this AMD card (the opposite was shown for the 7B one), and
  a fresh `forgeway analyze` run consuming these exact two saved records
  (that behavior is proven via synthetic evidence, not live, so far).

## Next

- **Run `forgeway analyze` against the live cross-vendor evidence pair**
  captured in `results/nvidia-run.json` / `results/amd-run.json` (see
  `docs/cross-vendor-validation.md`) — steps 10-15 of that checklist,
  the one part not yet exercised on top of a real run (proven so far only
  via `api/tests/test_decision_cross_vendor.py`'s synthetic evidence).
- **Live-validate the 7B/Llama-8B cross-vendor profiles specifically** —
  the `qwen2.5-1.5b-cross-vendor` profile proved the pipeline; the larger
  profiles remain `IMPLEMENTED BUT NOT LIVE VERIFIED` (worse: the 7B one is
  live-*disproven* on a 16GB AMD card in full bf16 — see
  `docs/cross-vendor-validation.md`'s "Why the model changed twice"). A
  quantized or tensor-parallel-split variant, or a bigger-VRAM AMD card,
  would be the way to actually close this, not more flag-tuning.
- **Fix `BenchmarkError`'s stderr-truncation UX gap** — a long wrapper
  traceback can push the real root-cause exception (e.g. a
  `torch.OutOfMemoryError`) past the last-2000-characters window this
  session's own debugging kept hitting; see
  `docs/cross-vendor-validation.md`'s "Real bugs found and fixed" #6 for
  the concrete repro. Not fixed this pass — flagged for whoever picks it
  up next.
- **Additional workloads** — more of the fixture library
  (`api/app/fixtures/workloads.json`) covering other model families and
  workload classes, so the decision engine's feasibility/scoring logic is
  exercised against a wider variety of real-shaped constraints, not just
  the flagship 70B realtime-inference case.
- **An evidence catalog** — today, real evidence only exists per-machine
  (`~/.forgeway/benchmarks/`) or per-browser-session (`/import`); no
  shared, queryable store of `PerformanceEvidence` across runs, machines,
  or contributors exists yet. This is the natural next step once there's
  more than one benchmark path feeding it.

## Later

- **Scheduler / orchestrator integrations** — Forgeway recommends; it
  does not place, migrate, or schedule anything today. Actually *acting*
  on a recommendation (a Kubernetes scheduler hook, a cloud provider API
  call) is explicitly out of scope for this preview and would be a
  significant, separate design effort — not a small addition to the
  existing engine.
- A second discovery/benchmark vendor beyond AMD (Intel, cloud-specific
  accelerators), once the ROCm adapter has proven the extension seam in
  practice.
- **Jetson discovery adapter (`tegrastats`/`jtop`)** — Jetson boards are
  integrated SoCs, not discrete GPUs; `nvidia-smi` doesn't work on them the
  way it does on datacenter/desktop NVIDIA hardware (see
  `api/app/discovery/nvidia.py`'s own scope note), so this needs its own
  adapter against a different tool and a much narrower set of honestly
  reportable fields — not a variant of the existing NVIDIA adapter. Also a
  different workload class (small-footprint edge inference) than this
  demo's current datacenter LLM-serving fixtures, so it likely wants its
  own fixture workload(s) to be meaningful, not just a new discovery path.

## Not planned

- Cloud API integrations, live telemetry ingestion, or a persistent
  database for the web demo itself — see README.md's "What's implemented
  vs. not" for the current, deliberate scope of the demo/API as distinct
  from the reusable core.
