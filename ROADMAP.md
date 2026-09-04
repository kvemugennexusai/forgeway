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
  **Verified against a real AMD GPU** (a Radeon RX 9070 XT, RDNA4, over
  SSH — [`docs/discovery.md`](docs/discovery.md#verified-against-real-hardware))
  — every expected `rocm-smi` field name and casing matched, and the real
  run surfaced a fix: architecture now resolves from rocm-smi's own `GFX
  Version` field (e.g. `gfx1201`) instead of guessing from the product
  name, since that field turned out to actually exist and be far more
  reliable.
- A ROCm benchmark path — `forgeway bench` dispatches its GPU telemetry
  sampler by vendor (`nvidia-smi` or `rocm-smi`,
  `api/app/benchmark/rocm_gpu_sampler.py`); the `vllm bench latency` command
  itself is identical on either vendor. **The telemetry sampler is verified
  against the same real AMD GPU** (a live power/memory reading came back
  correctly); **an actual `vllm bench latency` run on ROCm is not** — see
  [`docs/benchmarking.md`](docs/benchmarking.md#gpu-vendor-dispatch). The
  real install gap this surfaces: `pip install vllm` only gets the CUDA
  build; ROCm needs vLLM's Docker image or a from-source build against a
  ROCm PyTorch — not installed on the test machine yet.

## Next

- **Verify a real `vllm bench latency` run on ROCm** — install a
  ROCm-capable vLLM on the same AMD test machine (a heavier, separate step
  from what's been verified so far — see the v0.1 note above) and confirm
  `run_vllm_bench_latency(..., gpu_vendor="amd")`'s subprocess
  orchestration and `parser.py`'s assumptions about vLLM's output shape
  hold up against a live run. This is the one piece of ROCm support still
  "implemented against the documented shape" rather than confirmed live.
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
