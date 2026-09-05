# Forgeway v0.1.1 — limited technical preview

**Local evaluation only.** This build has no authentication of any kind and is not intended to
be exposed beyond `localhost`/your own LAN — see [Deployment scope](README.md#deployment-scope)
and [`SECURITY.md`](SECURITY.md) before running it anywhere else.

This is a preview release for a small group of testers. Please read "How to give feedback"
below — that's the main thing we need from you.

## What's in this preview

- **Decision engine**: feasibility → prediction → SLO check → normalize → weight →
  confidence-gate → rank → recommend → explain, over a vendor-neutral
  `ComputeTarget`/`AIWorkload`/`PerformanceEvidence` contract
  (`forgeway/v0.1` — [`docs/schemas.md`](docs/schemas.md)). Deterministic, no LLM anywhere in
  the decision path.
- **CLI**: `forgeway discover` (real local NVIDIA or AMD GPU detection), `forgeway bench` (a
  real `vllm bench latency` run, CUDA or ROCm), `forgeway bench-profile`/`forgeway compare-runs`
  (versioned cross-vendor benchmark comparison), and `forgeway analyze` (the same decision
  engine the web app uses, against a fixture or your own YAML workload).
- **Web demo**: an estate dashboard, workload analyzer, five fixture workloads, six scenario
  presets (demand spike, capacity loss, cost/performance priority, strict confidence), and
  `/import` — upload a real `forgeway discover`/`forgeway bench` result and include it as a
  candidate alongside the fixture catalog, browser-local only.
- **Hardware support**: local NVIDIA (`nvidia-smi`) and local AMD ROCm (`rocm-smi`) discovery
  and benchmarking. Both are live-verified end to end on real hardware — see
  [`docs/discovery.md#verification-status`](docs/discovery.md#verification-status) and
  [`docs/cross-vendor-validation.md`](docs/cross-vendor-validation.md) for the precise scope and
  the one remaining thin gap. No Intel or cloud-vendor discovery yet.
- **Evidence honesty pass** (new in this preview): every number the demo shows now carries an
  honest provenance label. The demo fixtures' baseline figures — previously mislabeled
  `MEASURED`/"Production telemetry" — are now correctly labeled `MODELED` (synthetic demo
  baselines), and the generated `examples/*.v0_1.json` files and their documentation now say
  plainly which ones came from real hardware (none of the four core examples did; two illustrate
  the `/import` flow with hand-constructed, schema-valid inputs run through real code, also not
  from real hardware) and which represent real live-hardware runs (`docs/cross-vendor-validation.md`,
  `docs/discovery.md`). No placement behavior changed — only labels and documentation.
- **README screenshots**: the estate dashboard, a recommendation with a feasibility checklist
  expanded, and the demand-spike scenario view, captured from this build.

## Installation

Requires Python 3.10+ (tested on 3.14) and, if you want to run the web demo, Node.js for
`web/` (Next.js 15 / React 19).

```bash
git clone https://github.com/kvemugennexusai/forgeway
cd forgeway/api
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt                       # registers the `forgeway` console script
cd ..
forgeway analyze examples/workload.yaml               # no GPU required
```

See [README.md](README.md#quick-start) for the full quick start (including `forgeway discover`
and `forgeway bench`, which need real NVIDIA/AMD hardware) and
[README.md#running-the-demo](README.md#running-the-demo) for the web UI.

## Try this sequence

1. **Install** per the CLI quick start above.
2. **Analyze the sample workload**:
   ```bash
   forgeway analyze examples/workload.yaml
   ```
   Expect: `Recommended: MI300X 192GB` (AMD), ~30.5% cheaper than the current H100 placement,
   78% confidence.
3. **Apply a policy change** and confirm the recommendation flips:
   ```bash
   forgeway analyze examples/workload.yaml --policy examples/policy.yaml
   ```
   `examples/policy.yaml` restricts the workload to NVIDIA-only, single-region. Expect the
   recommendation to change to `H100 80GB SXM5`, since MI300X is now a denied vendor — see the
   file's own comments for why.
4. **Report back**: anything that failed during setup, and anywhere the CLI's or web app's
   recommendation/explanation was confusing, surprising, or seemed wrong — see below.

If you also want to try the web demo or a real hardware discovery/benchmark run, see
[README.md](README.md) — both are optional for this sequence.

## Limitations

- **No authentication** — local/LAN use only. See [Deployment scope](README.md#deployment-scope).
- **No server-side persistence** — an in-memory store; restart the API and every simulated
  recommendation is gone. Imported hardware/evidence lives in browser `localStorage` only.
- **Two hardware vendors, one benchmark path** (`vllm bench latency`, offline latency only — it
  does not measure time-to-first-token or true concurrent-request serving throughput). See
  [`docs/benchmarking.md`](docs/benchmarking.md#why-vllm-bench-latency-and-what-it-does-and-doesnt-measure)
  before treating a benchmark number as representative of production serving performance.
- **The web demo's dashboard and five sample workloads are fixture data**, not live
  infrastructure — see "What is experimental / simulated?" in [README.md](README.md).
- **No custom workload authoring** in `/analyze` — only the fixture workload library (an
  imported target can stand in as an extra candidate for one of those workloads).
- See [README.md#whats-implemented-vs-not](README.md#whats-implemented-vs-not) for the complete,
  current list.

## How to give feedback

Please open a GitHub issue using the **Preview feedback** template:
https://github.com/kvemugennexusai/forgeway/issues/new/choose

We're specifically interested in:
- Setup/installation failures (include your OS, Python version, and the exact error).
- Recommendations or explanations that seemed confusing, surprising, or wrong.
- Anything in this release that implied more than it actually does.

**Please omit secrets** (API keys, tokens, internal hostnames, etc.) from any pasted output —
this is a public repository.

## Known open questions

- `web/package-lock.json` gained a `"license": "Apache-2.0"` metadata line during this
  session's local testing (an `npm ci` auto-sync from `web/package.json`'s existing `license`
  field) — harmless, but called out here since it's unrelated to this release's actual changes.
