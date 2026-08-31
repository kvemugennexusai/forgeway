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

## Next

- **AMD ROCm discovery adapter** — the second `DiscoveryAdapter`
  ([`docs/adding-an-accelerator.md`](docs/adding-an-accelerator.md)).
  Likely followed by a matching benchmark path once a runtime target is
  chosen (`vllm` on ROCm, or a ROCm-native tool).
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

## Not planned

- Cloud API integrations, live telemetry ingestion, or a persistent
  database for the web demo itself — see README.md's "What's implemented
  vs. not" for the current, deliberate scope of the demo/API as distinct
  from the reusable core.
