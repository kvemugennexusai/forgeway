# Hardware discovery — `forgeway discover`

The first real Forgeway hardware discovery capability: detect the local
machine's compute hardware and describe it as a
[`ComputeTarget`](schemas.md#1-computetarget) (`forgeway/v0.1`), the same
schema the demo's fixtures already use.

```
$ forgeway discover
Forgeway discovery: local compute target

  Vendor / model   nvidia — NVIDIA H100 80GB HBM3
  Devices          1
  Memory / device  79.6 GB
  Architecture     hopper
  Tier / location  lab — local (gpu-box-01)
  Status           healthy
  Utilization      12% GPU, 8% memory (observed)
  Discovered at    2026-08-30T14:03:11.482113+00:00

  Discovered via nvidia-smi on gpu-box-01 (Linux-6.8.0-x86_64). Driver
  version: 550.90.07. CUDA version: 12.4. Free device memory — GPU 0:
  77.6/79.6 GB free. price_per_hr_per_unit is a placeholder — there is no
  real hourly cost for locally discovered hardware; set it manually
  before using this target in cost-based placement decisions.
  supported_precisions is not auto-detected in this adapter — set it
  manually based on this GPU's known capabilities.

Run `forgeway discover --json` for the full ComputeTarget record.
```

```
$ forgeway discover --json
```
```json
{
  "schema_version": "forgeway/v0.1",
  "id": "local-nvidia-gpu-box-01",
  "vendor": "nvidia",
  "model": "NVIDIA H100 80GB HBM3",
  "tier": "lab",
  "location": "local (gpu-box-01)",
  "architecture": "hopper",
  "memory_gb_per_device": 79.6,
  "interconnect": "not probed",
  "supported_precisions": [],
  "capacity_units_total": 1,
  "capacity_units_allocated": 0,
  "runtime_support": null,
  "price_per_hr_per_unit": {
    "value": 0.0,
    "confidence": 0,
    "provenance": "MODELED",
    "range_low": null,
    "range_high": null,
    "source": "No pricing available for locally discovered hardware."
  },
  "status": "healthy",
  "unsupported_workload_classes": [],
  "notes": "Discovered via nvidia-smi on gpu-box-01 (Linux-6.8.0-x86_64). Driver version: 550.90.07. CUDA version: 12.4. Free device memory — GPU 0: 77.6/79.6 GB free. price_per_hr_per_unit is a placeholder — there is no real hourly cost for locally discovered hardware; set it manually before using this target in cost-based placement decisions. supported_precisions is not auto-detected in this adapter — set it manually based on this GPU's known capabilities.",
  "observed_gpu_utilization_pct": 12.0,
  "observed_memory_utilization_pct": 8.0,
  "discovered_at": "2026-08-30T14:03:11.482113Z",
  "free_capacity_units": 1,
  "utilization_pct": 0.0,
  "accelerator_count": 1
}
```

Both outputs above are illustrative (hand-assembled for this doc, since
they need a real NVIDIA GPU to produce) — `api/tests/test_discovery.py`
and `api/tests/test_cli.py` prove the actual field mapping and CLI
behavior against mocked `nvidia-smi` output.

## Supported platforms

**Local NVIDIA CUDA-capable and AMD ROCm-capable systems** — one machine,
discovered by running on it directly. `forgeway discover` tries each
adapter's `is_available()` in order (NVIDIA, then AMD ROCm — see
`api/app/cli/main.py`'s `ADAPTERS` list) and uses the first one whose
tooling is present. Explicitly out of scope for this pass: Intel, AWS
Trainium/Inferentia, Jetson-specific behavior (see `ROADMAP.md`'s "Later"
section — Jetson boards are integrated SoCs and need their own
`tegrastats`/`jtop`-based adapter, not a variant of either adapter here),
and any cloud/remote discovery (querying a fleet, an API, or a cluster).
See [`docs/architecture.md`](architecture.md) for where those fit in the
longer-term roadmap.

## Required tooling

- The `nvidia-smi` CLI tool, on `PATH` (ships with the NVIDIA driver —
  no separate install, and no `pynvml`/NVML Python bindings are used).
- No GPU access from inside a container without the NVIDIA container
  runtime configured — `nvidia-smi` simply won't be on `PATH` or won't see
  any devices in that case, which this adapter treats the same as "no
  NVIDIA hardware" (see Failure behavior below).

## Installing the CLI

```bash
cd api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # editable-installs this package (pyproject.toml is the
                                  # single source of truth for dependencies) and registers
                                  # the `forgeway` console script
forgeway discover
```

Without the editable install, the same command works as
`python -m app.cli.main discover`.

## What's captured

| Requested | Captured as | Notes |
|---|---|---|
| GPU model | `model` | from `nvidia-smi`'s `name` field |
| Number of devices | `capacity_units_total` / `accelerator_count` | count of GPUs `nvidia-smi` reports |
| Memory per device | `memory_gb_per_device` | from `memory.total`, first device |
| Driver version | in `notes` (free text) | no dedicated `ComputeTarget` field exists for this yet |
| CUDA version | in `notes` (free text) | parsed from `nvidia-smi`'s plain-text banner — there's no `--query-gpu` field for it. Best-effort: empty if unparseable, never fatal |
| Current (compute) utilization | `observed_gpu_utilization_pct` | averaged across devices when there's more than one |
| Memory utilization | `observed_memory_utilization_pct` | same |
| Free/available device memory | in `notes` (free text), per device | `nvidia-smi` reports `memory.free` per device; `ComputeTarget` has no memory-size-based capacity field to put it in as structured data (only `free_capacity_units`, a device-count concept), so it's surfaced as free text — the same treatment as driver/CUDA version — rather than dropped |
| Hostname | in `location` (`"local (<hostname>)"`) and `notes` | |
| OS/platform | in `notes` | `platform.platform()` |
| Timestamp | `discovered_at` | new field, added specifically for this — `None` for every fixture-sourced target |

`architecture` is a best-effort mapping from CUDA compute capability to an
architecture codename (e.g. `9.0` → `hopper`, `8.9` → `ada-lovelace`); an
unrecognized compute capability is labeled `"unknown (compute capability
X.Y)"` rather than guessed.

## Limitations

- **`supported_precisions` is always `[]`.** Precision support (fp16,
  bf16, fp8, int8, ...) depends on architecture and driver/library
  versions in ways `nvidia-smi` doesn't report; this adapter doesn't guess.
  Set it by hand before using a discovered target in placement decisions.
- **`price_per_hr_per_unit` is always a zero-value, zero-confidence
  placeholder.** There is no real hourly cost for hardware you already
  own or are already renting by some other arrangement — this field only
  matters for Forgeway's cost-based ranking once you supply a real number.
- **`interconnect` is always `"not probed"`.** Detecting NVLink/PCIe
  topology reliably (`nvidia-smi topo -m` output) was judged out of scope
  for a first adapter; revisit if it turns out to matter for a placement
  decision.
- **`tier` is always `"lab"`.** There's no signal yet to distinguish a
  real datacenter node from a workstation from this adapter's inputs.
- **Heterogeneous GPU machines are only partially modeled.** If a machine
  has more than one GPU *model*, `capacity_units_total` still counts every
  device, but `model`/`memory_gb_per_device`/`architecture` reflect only
  the first device reported — `notes` calls this out explicitly when it
  happens, but there's no per-device breakdown in the schema yet.
- **No structured free/available memory field.** Free memory per device is
  in `notes` as free text (see the table above), not a typed field —
  `ComputeTarget` has no memory-size-based capacity field to put it in
  (only device-count-based `free_capacity_units`). A future version could
  add one and stop relying on parsing `notes`.
- **No degraded/offline detection.** If `nvidia-smi` runs and returns data
  at all, `status` is always `"healthy"` — this adapter doesn't yet parse
  fault/throttle indicators out of `nvidia-smi`'s output.
- **Doesn't automatically feed the fixture catalog, the in-memory store,
  or the estate dashboard.** `forgeway discover` prints or emits JSON;
  getting a discovered target into an actual placement decision is manual:
  `forgeway analyze` picks up a locally discovered target automatically
  (best-effort, `--skip-discovery` to opt out), and the web UI's `/import`
  accepts an uploaded `ComputeTarget` JSON for that browser session (see
  [`docs/importing-results.md`](importing-results.md)) — neither is a live,
  continuously-refreshed inventory. See `docs/architecture.md`.

## AMD ROCm (`rocm-smi`)

The second discovery adapter (`api/app/discovery/rocm.py`), added following
[`docs/adding-an-accelerator.md`](adding-an-accelerator.md)'s extension seam
— `forgeway discover` tries it if `nvidia-smi` isn't found.

```bash
forgeway discover   # tries NVIDIA first, then AMD ROCm
```

Required tooling: the `rocm-smi` CLI, on `PATH` (ships with the ROCm stack —
no separate install). Queried as:

```
rocm-smi --showproductname --showuniqueid --showmeminfo vram --showuse --json
```

| Requested | Captured as | Notes |
|---|---|---|
| Card model | `model` | from rocm-smi's `Card series` field |
| Number of devices | `capacity_units_total` / `accelerator_count` | count of `cardN` entries rocm-smi reports |
| VRAM per device | `memory_gb_per_device` | from `VRAM Total Memory (B)`, first device |
| Driver version | in `notes` (free text) | best-effort, from a separate `rocm-smi --showdriverversion --json` call — never fatal if unparseable |
| Unique ID | in `notes` (free text), first device | from `Unique ID`, when reported |
| Current GPU utilization | `observed_gpu_utilization_pct` | averaged across devices when there's more than one, directly from `GPU use (%)` |
| Memory utilization | `observed_memory_utilization_pct` | **derived**, not directly reported — `VRAM Total Used Memory (B)` / `VRAM Total Memory (B)` per device, then averaged; unlike NVIDIA's adapter, rocm-smi's queried fields here don't include a ready-made memory-utilization percentage |
| Free/available VRAM | in `notes` (free text), per device | same treatment as NVIDIA's free-memory figures — no memory-size-based capacity field exists in `ComputeTarget` to put it in |

`architecture` primarily keys off rocm-smi's own `GFX Version` field (e.g.
`"gfx1201"`) — the real ROCm equivalent of CUDA's `compute_cap`, confirmed
present in real `--showproductname --json` output (see "Verified against
real hardware" below), even though it wasn't documented anywhere I could
find before actually running this against a real GPU. `_architecture_for`
(`api/app/discovery/rocm.py`) maps known `gfx*` targets to a codename (e.g.
`gfx1201` → `rdna4`, `gfx942` → `cdna3`), falling back to a product-name
substring match (`"rx 7"` → `rdna3`, etc.) only if `GFX Version` is somehow
absent, and to an explicit `"unknown"` label — naming whichever signal it
did have, model and/or gfx version — rather than guessing, if neither
resolves it.

**rocm-smi's JSON output shape is not as stable as nvidia-smi's CSV.** Its
key names and casing have varied across ROCm releases in the wild (e.g.
`"Card series"` vs `"Card Series"`) and there's no single documented schema
version the way `nvidia-smi --query-gpu`'s CSV fields are. This adapter does
case-insensitive field lookups (`_lookup()`) to absorb casing differences,
and raises a clean `DiscoveryError` — including the raw per-card fields it
saw — if a required field (`Card series`, `VRAM Total Memory (B)`) is
missing entirely, rather than crashing with a raw `KeyError`. If you hit
that on real AMD hardware, the error message has what's needed to extend
`_lookup()`'s field-name list for your ROCm version.

Same placeholder conventions as NVIDIA's adapter apply: `supported_precisions`
is always `[]`, `price_per_hr_per_unit` is always a zero-value/zero-confidence
placeholder, `interconnect` is always `"not probed"`, `tier` is always
`"lab"`, and heterogeneous multi-model machines only get the first device's
model/memory/architecture reflected (with an explicit note).

### Verification status

This project uses five precise states for any hardware-verification claim:
**NOT IMPLEMENTED**, **IMPLEMENTED BUT NOT LIVE VERIFIED** (code exists,
only exercised against hand-built fixtures matching a documented/assumed
shape), **IMPLEMENTED** (exists; verification status tracked separately),
**TESTED WITH CAPTURED REAL OUTPUT** (a persisted automated test uses
output verbatim-captured from real hardware, so it's regression-tested
without needing that hardware present), and **LIVE VERIFIED** (actually
executed against real hardware and confirmed correct). This section is the
one place ROCm's status is stated in full detail — README.md,
`docs/benchmarking.md`, and `ROADMAP.md` all summarize and link back here
rather than independently restating it, specifically to avoid the kind of
drift that previously left two of those files contradicting each other.

**ROCm discovery (this adapter, all fields including architecture
resolution): LIVE VERIFIED, and TESTED WITH CAPTURED REAL OUTPUT.** It has
been run against a real machine — an **AMD Radeon RX 9070 XT** (RDNA4,
`gfx1201`) — over SSH, via the actual `forgeway discover` CLI entrypoint,
not just this module's functions called directly. Real `rocm-smi --json`
output confirmed every field name this adapter expects (`Card Series`,
`VRAM Total Memory (B)`, `VRAM Total Used Memory (B)`, `GPU use (%)`,
`Unique ID`, `GFX Version`) — including the exact capitalization already
assumed — and the resulting `ComputeTarget` came back correct end-to-end
(`forgeway discover` on that machine reports `amd — AMD Radeon RX 9070
XT`, `15.9 GB`, `architecture: rdna4`). The `GFX Version` field's presence,
and the fix to key architecture off it instead of a product-name guess,
both came directly out of this real run.
`api/tests/test_discovery_rocm.py::test_discover_matches_real_rx9070xt_hardware`
now regression-tests against that machine's actual captured JSON verbatim,
not just a hand-built fixture — this is the "tested with captured real
output" half of the claim, in addition to the live run itself. rocm-smi
also emits a `WARNING:` line (e.g. about a GPU being in a low-power state)
— confirmed to land on stderr, never stdout, so it doesn't interfere with
this adapter's JSON parsing.

This is one real GPU on one ROCm version, not exhaustive coverage — a
different card, driver, or ROCm release could still expose a field-naming
variant this adapter's case-insensitive lookup doesn't yet handle. If you
hit that, the `DiscoveryError` message includes the raw per-card fields it
saw, which is what's needed to extend `_lookup()`'s field-name list.

**The ROCm GPU telemetry sampler used by `forgeway bench`
(`rocm_gpu_sampler.sample_gpu_once()`), the `run_vllm_bench_latency(...,
gpu_vendor="amd")` dispatch path it's called through, and an actual `vllm
bench latency` run on ROCm: all LIVE VERIFIED.** A real run completed end
to end on the same real AMD Radeon RX 9070 XT (inside AMD's official
`rocm/vllm` Docker image, via `forgeway bench-profile` — see
[`docs/cross-vendor-validation.md`](cross-vendor-validation.md)),
producing a real `PerformanceEvidence` record with a real
`peak_gpu_memory_used_mb` reading (15,529.70 MB) and real
latency/throughput metrics. See
[`docs/benchmarking.md`](benchmarking.md#gpu-vendor-dispatch) for the
exact breakdown, including the one thing not literally exercised: the
plain `forgeway bench` CLI entrypoint itself (`cmd_bench`) — a thin
wrapper around the exact same now-proven functions, invoked via `forgeway
bench-profile` instead in this run. That sampler function's own persisted
automated test suite (`api/tests/test_benchmark_rocm_gpu_sampler.py`)
remains hand-built fixtures, not captured real output, unlike this
adapter's — the live run proved the code works without changing that file.

## Failure behavior

If neither `nvidia-smi` nor `rocm-smi` is on `PATH` (no supported driver
installed, or running somewhere without GPU passthrough), `forgeway
discover` fails cleanly:

```
$ forgeway discover
forgeway discover: No supported accelerator was detected on this machine. Checked: NVIDIA, AMD ROCm. See docs/discovery.md for what's supported.
$ echo $?
1
```

No traceback, ever — a `DiscoveryError` is the only expected failure mode
and is always caught and reported as a single line to stderr with exit
code 1. Any other unexpected exception is also caught at the top level of
the CLI (`app/cli/main.py::main`) and reported the same way, as a safety
net — it should never happen, but a bug in an adapter still shouldn't
produce an unreadable stack trace for someone just trying to run the tool.
