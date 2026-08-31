# Adding an accelerator (a new discovery adapter)

How to add support for a new vendor/platform to `forgeway discover` —
e.g. AMD ROCm, Intel, or a cloud-specific accelerator (`ROADMAP.md` lists
AMD ROCm as the next one). This is the extension seam the project was
built around: one new class, one line to register it, nothing else
changes.

This doc covers **discovery** (describing hardware as a `ComputeTarget`).
Extending **benchmarking** to a second runtime or vendor is a related but
separate seam — see [`docs/benchmarking.md`](benchmarking.md)'s "Scope"
section; `app/benchmark/vllm_runner.py` and `app/benchmark/evidence.py`
are the files that would need an equivalent second path.

## The interface

`api/app/discovery/adapter.py`:

```python
class DiscoveryAdapter(ABC):
    name: str  # short, human-readable, e.g. "NVIDIA" or "AMD"

    @abstractmethod
    def is_available(self) -> bool:
        """Cheap, side-effect-free check. Must never raise — on any
        doubt, return False."""

    @abstractmethod
    def discover(self) -> ComputeTarget:
        """Only called after is_available() is True. Raises
        DiscoveryError if the tooling fails once actually invoked."""
```

Two methods, two responsibilities: **detection** (is this vendor's
tooling even present on this machine?) and **parsing** (turn that
tooling's real output into a typed `ComputeTarget`). Nothing else in the
codebase should need to change to add a new one.

## Steps

1. **Write the adapter class** in a new file, `api/app/discovery/<vendor>.py`
   — use `api/app/discovery/nvidia.py` as the template. Concretely, for
   each new vendor:
   - `is_available()`: the cheapest possible check that the vendor's
     query tool is on `PATH` (NVIDIA's uses `shutil.which("nvidia-smi")`).
     Never raise from here — return `False` on any doubt so the CLI moves
     on to the next adapter or reports "nothing found" cleanly.
   - `discover()`: shell out to the vendor's own query tool (subprocess,
     with an explicit `timeout`), parse its output defensively, and build
     a real `ComputeTarget`. Raise `DiscoveryError` — never let a raw
     `subprocess`/parsing exception escape — for: the binary missing
     after all (`FileNotFoundError`), a timeout, a non-zero exit code, or
     output that doesn't parse into the expected shape.
   - **Never guess a field you can't actually determine.** NVIDIA's
     adapter leaves `supported_precisions` empty and `price_per_hr_per_unit`
     a zero-confidence `MODELED` placeholder rather than inventing plausible
     values — follow the same rule for whatever your vendor's tooling
     genuinely can't tell you. Every real value your tool *can* report
     (memory, device count, driver/firmware version, utilization) should
     go in a real typed field or, if no field exists yet, `notes` as free
     text — see NVIDIA's adapter for how it surfaces free device memory
     and driver/CUDA version this way, since `ComputeTarget` has no
     dedicated field for either yet.
   - Set `discovered_at=datetime.now(timezone.utc)` so callers can tell a
     freshly discovered target from a fixture-sourced one (which always
     has `discovered_at=None`).

2. **Register it** in `api/app/cli/main.py`'s `ADAPTERS` list:

   ```python
   ADAPTERS: list[DiscoveryAdapter] = [NvidiaDiscoveryAdapter(), YourNewAdapter()]
   ```

   `run_discovery()` tries each adapter's `is_available()` in order and
   returns the first available one's `discover()` result — order matters
   only if a machine could plausibly have more than one vendor's tooling
   present at once.

3. **Write tests** that mock the vendor's tool output — no real hardware
   should ever be required to run the test suite. `api/tests/test_discovery.py`
   is the pattern: it patches `subprocess.run` (or the adapter's own thin
   wrapper around it) with hand-built CSV/text fixtures matching the real
   tool's documented output shape, and asserts the field mapping,
   architecture-name resolution, heterogeneous-hardware handling, and
   every `DiscoveryError` path (tool missing, non-zero exit, zero devices,
   unparseable output). Add the equivalent CLI-level test too
   (`api/tests/test_cli.py`) proving `forgeway discover` picks up the new
   adapter and produces clean output on both the human and `--json` paths.

4. **Document it**: add a section to `docs/discovery.md` (or a new
   `docs/discovery-<vendor>.md` if it's substantial enough to warrant its
   own page) covering what's captured, what's a placeholder/limitation,
   and required tooling — the same structure NVIDIA's section already
   follows. Update `README.md`'s "What hardware is supported today"
   line and `ROADMAP.md`.

## What you don't need to touch

- `app/data/loader.py`, `app/state.py`, the web UI — discovery output
  isn't automatically wired into any of them today (see
  `docs/architecture.md`); a new adapter doesn't change that.
- `app/core/schemas/compute.py` — `ComputeTarget` is vendor-neutral by
  design; a new adapter should never need a new field just to describe
  one more vendor's hardware. If you find yourself needing one (e.g. a
  genuinely new concept `ComputeTarget` has no place for), that's worth
  raising as its own discussion before adding it — see `CONTRIBUTING.md`.
- The placement engine (`app/core/engine/`) — it only ever sees a
  `ComputeTarget`, never which adapter produced it.
