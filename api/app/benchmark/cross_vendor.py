"""Cross-vendor benchmark profiles, comparability, and evidence records —
the machinery behind `forgeway bench-profile` and `forgeway compare-runs`
(docs/cross-vendor-validation.md).

Scope, deliberately narrow: this module makes it possible to run the SAME
declared workload configuration (a `BenchmarkProfile`) on NVIDIA and AMD
hardware and know, explicitly, whether the two results are safe to compare
— not to broaden what's benchmarked. It adds nothing to the decision engine
and nothing to app.core.schemas: everything here is additive, product-level
tooling built entirely on top of the existing, unchanged
`app.benchmark.vllm_runner` / `app.benchmark.evidence` pipeline and the
existing, unchanged `PerformanceEvidence` contract.

Design choice worth stating explicitly: comparability is judged from the
BenchmarkProfile actually used for each run (authoritative — bench-profile
passes the profile's own fields straight to the runner) plus a small set of
separately-captured environment facts (runtime/driver version, accelerator
count) that legitimately vary machine-to-machine even under an identical
profile. The former are "critical" dimensions (any mismatch -> NOT
COMPARABLE); the latter are "soft" dimensions (a mismatch there alone ->
PARTIALLY COMPARABLE, since per-replica metrics stay meaningful even when,
say, patch versions differ). This mirrors, and does not replace,
app.core.engine.evidence_selection's much narrower "comparable == has the
metric keys we need" rule — that rule decides what a single target scores
against; this one decides what a human can honestly set side by side across
two different targets/vendors.

Unit of comparison for this phase (see docs/cross-vendor-validation.md):
**per-replica / per-deployment performance for the exact profiled
configuration** — not per-device, not aggregate fleet throughput. A
`tensor_parallel_degree` mismatch is a critical (NOT COMPARABLE) dimension
precisely because it changes what "one replica" means; a raw
`accelerator_count` difference on the ComputeTarget (e.g. an 8-GPU box vs.
a 4-GPU box) is a soft dimension, because it doesn't change what a single
replica's own numbers mean.
"""
from __future__ import annotations

import importlib.metadata
import platform
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.benchmark.evidence import build_performance_evidence
from app.benchmark.parser import parse_vllm_latency_output
from app.benchmark.vllm_runner import DEFAULT_TIMEOUT_S, run_vllm_bench_latency
from app.core.schemas import ComputeTarget
from app.core.schemas.v0_1 import PerformanceEvidence
from app.core.version import FORGEWAY_VERSION

CROSS_VENDOR_SCHEMA_VERSION = "forgeway-cross-vendor/v0.1"

#: The one benchmark mode/methodology this module implements — both stated
#: explicitly on every record rather than assumed, so a comparison across a
#: hypothetical future second mode fails loudly instead of silently.
BENCHMARK_MODE = "vllm bench latency (offline, single-node, no server)"
MEASUREMENT_METHODOLOGY = "vllm bench latency (offline, single-node, no server)"

#: Forgeway's own vendor-neutral precision strings (e.g. the same
#: convention app.core.schemas.Workload.precision already uses — see
#: examples/workload.yaml's "fp8") mapped to the literal --dtype value
#: vLLM's CLI expects. Deliberately narrow and best-known, not exhaustive:
#: a precision with no entry here has --dtype simply omitted (vLLM's own
#: default applies) rather than guessing a flag value that might be wrong
#: — see docs/cross-vendor-validation.md for what this means for
#: comparability when it happens (still a critical ComparabilityKey field;
#: just not independently enforced on the command line for that value).
_VLLM_DTYPE_BY_PRECISION: dict[str, str] = {
    "bf16": "bfloat16",
    "bfloat16": "bfloat16",
    "fp16": "float16",
    "float16": "float16",
    "fp32": "float32",
    "float32": "float32",
}


class ProfileError(Exception):
    """The one expected failure mode for a malformed/missing benchmark
    profile — mirrors AnalyzeError/DiscoveryError/BenchmarkError. Callers
    catch this and print a clean message, never a raw traceback."""


# --------------------------------------------------------------------------
# The benchmark profile
# --------------------------------------------------------------------------


class BenchmarkProfile(BaseModel):
    """A versioned, fully-specified inference-benchmark configuration —
    everything two runs need to agree on to be a fair cross-vendor
    comparison. See benchmarks/profiles/llama-8b-cross-vendor-v0.1.yaml for
    the canonical instance and docs/cross-vendor-validation.md for how it's
    used end to end.

    Every field here is either used verbatim by `run_vllm_bench_latency`
    (so the two vendors' runs are provably configured identically, not just
    documented as if they were) or recorded purely for comparability/audit
    purposes (sampling_params, tokenizer_version, max_model_len,
    model_revision) where vllm bench latency itself has no matching flag —
    Forgeway does not silently vary those, but it also can't force a
    tokenizer/model revision vLLM doesn't expose a flag for; recorded
    honestly rather than either enforced-but-fake or omitted.
    """

    profile_id: str
    profile_version: str
    model: str
    model_revision: Optional[str] = None
    task: Literal["text-generation"] = "text-generation"
    runtime: Literal["vllm"] = "vllm"
    runtime_version_constraint: Optional[str] = None
    precision: str
    tensor_parallel_degree: int = 1
    input_tokens: int
    output_tokens: int
    concurrency: int
    batch_behavior: str
    warmup_runs: int
    measured_runs: int
    seed: Optional[int] = None
    sampling_params: dict = Field(default_factory=dict)
    tokenizer_version: Optional[str] = None
    quantization: Optional[str] = None
    max_model_len: Optional[int] = None
    env_vars: dict[str, str] = Field(default_factory=dict)
    notes: Optional[str] = None

    @field_validator("input_tokens", "output_tokens", "concurrency", "tensor_parallel_degree")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("must be >= 1")
        return v

    @field_validator("warmup_runs")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("must be >= 0")
        return v

    @field_validator("measured_runs")
    @classmethod
    def _at_least_one(cls, v: int) -> int:
        if v < 1:
            raise ValueError("must be >= 1 — a profile with zero measured runs produces no evidence")
        return v


def load_benchmark_profile_yaml(path: Path) -> BenchmarkProfile:
    """Loads and validates a BenchmarkProfile from a YAML file — mirrors
    app.cli.yaml_io.load_workload_yaml's error handling exactly (missing
    file / invalid YAML / schema violation all become one clean
    ProfileError, never a raw exception)."""
    if not path.exists():
        raise ProfileError(f"file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise ProfileError(f"invalid YAML in {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ProfileError(f"{path} must contain a YAML mapping (got {type(raw).__name__})")
    try:
        return BenchmarkProfile.model_validate(raw)
    except ValidationError as e:
        raise ProfileError(f"{path} is not a valid BenchmarkProfile:\n{e}") from e


# --------------------------------------------------------------------------
# Environment capture — best-effort, never fatal, never guessed
# --------------------------------------------------------------------------

#: Both discovery adapters write driver versions as dotted/hyphenated
#: version strings starting with a digit (e.g. "550.90.07", "7.0.0"); the
#: greedy character class below intentionally includes "." so a version's
#: own internal dots aren't mistaken for the sentence-terminating one — the
#: engine backtracks to leave exactly the trailing period for the literal
#: `\.` to match. Requiring a leading digit is also what correctly excludes
#: rocm.py's "Driver version: not discoverable." case without a separate
#: string comparison.
_DRIVER_VERSION_RE = re.compile(r"Driver version:\s*([0-9][0-9A-Za-z.\-]*)\.")
_CPUINFO_MODEL_RE = re.compile(r"^model name\s*:\s*(.+)$", re.MULTILINE)


def _best_effort_package_version(package: str) -> Optional[str]:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def _best_effort_driver_version(target: ComputeTarget) -> Optional[str]:
    """Both discovery adapters (app.discovery.nvidia, app.discovery.rocm)
    embed "Driver version: X." as free text in ComputeTarget.notes — there
    is no structured field for it (see docs/discovery.md). Extracted
    best-effort here rather than adding a field to the core ComputeTarget
    schema, which this module deliberately leaves untouched. Returns None,
    never raises, if the text isn't there or doesn't match."""
    match = _DRIVER_VERSION_RE.search(target.notes or "")
    return match.group(1) if match is not None else None


def _best_effort_cpu_model() -> Optional[str]:
    processor = platform.processor()
    if processor:
        return processor
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text()
    except OSError:
        return None
    match = _CPUINFO_MODEL_RE.search(cpuinfo)
    return match.group(1).strip() if match else None


class EnvironmentInfo(BaseModel):
    """What's reliably discoverable about the machine a run executed on.
    Every field is Optional and best-effort by design (section 6 of the
    cross-vendor spec: "do not require every field to exist; capture what
    is reliably discoverable") — a missing field here is preserved as
    missing, never guessed or defaulted to something plausible-looking."""

    runtime: str = "vllm"
    runtime_version: Optional[str] = None
    torch_version: Optional[str] = None
    os: Optional[str] = None
    kernel: Optional[str] = None
    cpu_model: Optional[str] = None
    driver_version: Optional[str] = None

    @classmethod
    def capture(cls, target: ComputeTarget) -> "EnvironmentInfo":
        return cls(
            runtime_version=_best_effort_package_version("vllm"),
            torch_version=_best_effort_package_version("torch"),
            os=platform.platform(),
            kernel=platform.release(),
            cpu_model=_best_effort_cpu_model(),
            driver_version=_best_effort_driver_version(target),
        )


# --------------------------------------------------------------------------
# Comparability
# --------------------------------------------------------------------------

ComparabilityStatus = Literal["COMPARABLE", "PARTIALLY_COMPARABLE", "NOT_COMPARABLE"]

#: Human-readable labels for CLI output — see `forgeway compare-runs`'s
#: "Comparability:" line in docs/cross-vendor-validation.md.
_STATUS_DISPLAY: dict[ComparabilityStatus, str] = {
    "COMPARABLE": "DIRECTLY COMPARABLE",
    "PARTIALLY_COMPARABLE": "PARTIALLY COMPARABLE",
    "NOT_COMPARABLE": "NOT COMPARABLE",
}


def display_status(status: ComparabilityStatus) -> str:
    return _STATUS_DISPLAY[status]


class ComparabilityKey(BaseModel):
    """The critical, workload/runtime dimensions two evidence records must
    agree on to be directly comparable — built straight from the
    BenchmarkProfile that configured the run, since bench-profile passes
    these exact values to the runner (not re-derived from telemetry, which
    would let a silent mismatch slip through as a rounding difference)."""

    profile_id: str
    profile_version: str
    model: str
    model_revision: Optional[str]
    precision: str
    quantization: Optional[str]
    input_tokens: int
    output_tokens: int
    concurrency: int
    tensor_parallel_degree: int
    runtime_family: str
    benchmark_mode: str
    warmup_policy: str
    measurement_methodology: str

    @classmethod
    def from_profile(cls, profile: BenchmarkProfile) -> "ComparabilityKey":
        return cls(
            profile_id=profile.profile_id,
            profile_version=profile.profile_version,
            model=profile.model,
            model_revision=profile.model_revision,
            precision=profile.precision,
            quantization=profile.quantization,
            input_tokens=profile.input_tokens,
            output_tokens=profile.output_tokens,
            concurrency=profile.concurrency,
            tensor_parallel_degree=profile.tensor_parallel_degree,
            runtime_family=profile.runtime,
            benchmark_mode=BENCHMARK_MODE,
            warmup_policy=f"warmup_runs={profile.warmup_runs},measured_runs={profile.measured_runs}",
            measurement_methodology=MEASUREMENT_METHODOLOGY,
        )


class ComparabilityVerdict(BaseModel):
    status: ComparabilityStatus
    reasons: list[str] = Field(default_factory=list)


#: (field name, human label) for every ComparabilityKey field checked as a
#: critical dimension — order is the order reasons are reported in.
_CRITICAL_FIELDS: list[tuple[str, str]] = [
    ("profile_id", "benchmark profile id"),
    ("profile_version", "benchmark profile version"),
    ("model", "model"),
    ("model_revision", "model revision"),
    ("precision", "precision"),
    ("quantization", "quantization"),
    ("input_tokens", "input token count"),
    ("output_tokens", "output token count"),
    ("concurrency", "concurrency"),
    ("tensor_parallel_degree", "tensor parallel degree"),
    ("runtime_family", "runtime family"),
    ("benchmark_mode", "benchmark mode"),
    ("warmup_policy", "warmup policy"),
    ("measurement_methodology", "measurement methodology"),
]


def compare_evidence(a: "CrossVendorEvidenceRecord", b: "CrossVendorEvidenceRecord") -> ComparabilityVerdict:
    """The comparability policy (see module docstring for the full
    rationale):

    1. Any mismatch on a _CRITICAL_FIELDS dimension -> NOT_COMPARABLE, with
       one explicit reason per mismatched field (both values named).
       Presence-vs-absence (e.g. one run has a model_revision, the other
       doesn't) counts as a mismatch — an undocumented revision on one side
       is a real gap in traceability, not something to wave through as
       "probably fine."
    2. Otherwise, a mismatch on a soft dimension (runtime version, driver
       version, or total accelerator count on the target) -> a real result,
       but PARTIALLY_COMPARABLE — per-replica metrics remain meaningful,
       the reason is still surfaced, not hidden.
    3. Otherwise -> COMPARABLE.

    Never returns anything other than one of the three ComparabilityStatus
    values, and never raises — an unusable pair (e.g. one profile-derived
    key literally can't be built) is a caller-side error before this
    function is ever reached."""
    reasons: list[str] = []
    for field_name, label in _CRITICAL_FIELDS:
        va = getattr(a.comparability_key, field_name)
        vb = getattr(b.comparability_key, field_name)
        if va != vb:
            reasons.append(f"{label} differs: {va!r} vs {vb!r}")
    if reasons:
        return ComparabilityVerdict(status="NOT_COMPARABLE", reasons=reasons)

    soft_reasons: list[str] = []
    if a.environment.runtime_version != b.environment.runtime_version:
        soft_reasons.append(
            f"runtime ({a.environment.runtime}) version differs: "
            f"{a.environment.runtime_version!r} vs {b.environment.runtime_version!r}"
        )
    if a.environment.driver_version != b.environment.driver_version:
        soft_reasons.append(
            f"driver version differs: {a.environment.driver_version!r} vs {b.environment.driver_version!r}"
        )
    if a.target.accelerator_count != b.target.accelerator_count:
        soft_reasons.append(
            f"accelerator count differs: {a.target.accelerator_count} vs {b.target.accelerator_count} "
            "(per-replica metrics remain comparable; this affects fleet-level totals, not this comparison)"
        )
    if soft_reasons:
        return ComparabilityVerdict(status="PARTIALLY_COMPARABLE", reasons=soft_reasons)

    return ComparabilityVerdict(status="COMPARABLE", reasons=[])


# --------------------------------------------------------------------------
# The cross-vendor evidence record
# --------------------------------------------------------------------------

CostBasis = Literal["cloud_hourly", "onprem_amortized", "fixture_reference", "user_supplied", "not_available"]


class CrossVendorEvidenceRecord(BaseModel):
    """What `forgeway bench-profile` saves, and what `forgeway compare-runs`
    reads — a superset of a plain PerformanceEvidence record, additive only
    (nothing in app.core.schemas changes; `performance_evidence` below is
    the exact, unmodified type the decision engine already consumes, saved
    separately via app.benchmark.store.save_run so it flows into
    `forgeway analyze` exactly as any other real benchmark run does — see
    docs/decision-engine.md).

    `cost_basis` defaults to "not_available" deliberately: every discovery
    adapter (app.discovery.nvidia, app.discovery.rocm) gives a freshly
    discovered ComputeTarget a zero-value, zero-confidence placeholder
    price (docs/discovery.md) — there is no real cost basis to label until
    a caller supplies one, and `forgeway compare-runs` must never present a
    cost comparison as if one existed when it doesn't (see
    docs/cross-vendor-validation.md's cost-normalization note)."""

    schema_version: Literal["forgeway-cross-vendor/v0.1"] = CROSS_VENDOR_SCHEMA_VERSION
    run_id: str
    profile_id: str
    profile_version: str
    target: ComputeTarget
    environment: EnvironmentInfo
    performance_evidence: PerformanceEvidence
    comparability_key: ComparabilityKey
    raw_command: list[str] = Field(default_factory=list)
    cost_basis: CostBasis = "not_available"
    forgeway_version: str = FORGEWAY_VERSION
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_performance_evidence(self) -> PerformanceEvidence:
        """The exact, unmodified PerformanceEvidence the decision engine
        consumes — a named accessor rather than reaching into the field
        directly, so a caller's intent (`app.engine`-facing evidence,
        specifically) is explicit at the call site."""
        return self.performance_evidence


# --------------------------------------------------------------------------
# The runner interface
# --------------------------------------------------------------------------


class BenchmarkRunner(ABC):
    """One vendor's way of turning a BenchmarkProfile + a discovered
    ComputeTarget into a CrossVendorEvidenceRecord. Both concrete runners
    below are intentionally thin: `vllm bench latency`'s command line and
    JSON parsing are identical on NVIDIA and ROCm (PyTorch/HIP handle
    device dispatch underneath — see app.benchmark.vllm_runner's module
    docstring), so all of that logic lives once, in `_run_profile()`
    below. Each concrete class supplies only its `vendor` string, which
    `_run_profile()` uses to select the matching GPU telemetry sampler
    (app.benchmark.gpu_sampler vs. app.benchmark.rocm_gpu_sampler) via the
    existing `run_vllm_bench_latency(gpu_vendor=...)` dispatch — no
    per-vendor metric or evidence code is duplicated anywhere in this
    module."""

    vendor: str

    @abstractmethod
    def run(
        self,
        profile: BenchmarkProfile,
        target: ComputeTarget,
        *,
        run_id: str,
        workload_id: Optional[str] = None,
        device_index: int = 0,
        gpu_memory_utilization: Optional[float] = None,
        timeout_s: Optional[float] = None,
        enforce_eager: bool = False,
    ) -> CrossVendorEvidenceRecord: ...


def _run_profile(
    runner: BenchmarkRunner,
    profile: BenchmarkProfile,
    target: ComputeTarget,
    *,
    run_id: str,
    workload_id: Optional[str],
    device_index: int,
    gpu_memory_utilization: Optional[float] = None,
    timeout_s: Optional[float] = None,
    enforce_eager: bool = False,
) -> CrossVendorEvidenceRecord:
    """The one real implementation shared by every BenchmarkRunner. Reuses
    app.benchmark.vllm_runner.run_vllm_bench_latency and
    app.benchmark.evidence.build_performance_evidence completely unchanged
    — this function's only job is threading BenchmarkProfile fields
    through to them and wrapping the result, never re-implementing
    anything they already do.

    `gpu_memory_utilization` is a per-machine override, not a
    BenchmarkProfile field — see run_vllm_bench_latency's docstring for
    why (a real requirement on unified-memory systems like DGX Spark)."""
    raw = run_vllm_bench_latency(
        model=profile.model,
        input_tokens=profile.input_tokens,
        output_tokens=profile.output_tokens,
        concurrency=profile.concurrency,
        iterations=profile.measured_runs,
        warmup_iterations=profile.warmup_runs,
        device_index=device_index,
        gpu_vendor=runner.vendor,
        env=profile.env_vars or None,
        dtype=_VLLM_DTYPE_BY_PRECISION.get(profile.precision.lower()),
        tensor_parallel_size=profile.tensor_parallel_degree,
        quantization=profile.quantization,
        max_model_len=profile.max_model_len,
        gpu_memory_utilization=gpu_memory_utilization,
        timeout_s=timeout_s if timeout_s is not None else DEFAULT_TIMEOUT_S,
        enforce_eager=enforce_eager,
    )
    parsed = parse_vllm_latency_output(raw.raw_json)
    evidence = build_performance_evidence(
        compute_target=target,
        model=profile.model,
        input_tokens=profile.input_tokens,
        output_tokens=profile.output_tokens,
        concurrency=profile.concurrency,
        parsed=parsed,
        gpu_samples=raw.gpu_samples,
        run_id=run_id,
        workload_id=workload_id,
    )
    return CrossVendorEvidenceRecord(
        run_id=run_id,
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
        target=target,
        environment=EnvironmentInfo.capture(target),
        performance_evidence=evidence,
        comparability_key=ComparabilityKey.from_profile(profile),
        raw_command=raw.cmd,
    )


class CudaVllmBenchmarkRunner(BenchmarkRunner):
    vendor = "nvidia"

    def run(
        self,
        profile: BenchmarkProfile,
        target: ComputeTarget,
        *,
        run_id: str,
        workload_id: Optional[str] = None,
        device_index: int = 0,
        gpu_memory_utilization: Optional[float] = None,
        timeout_s: Optional[float] = None,
        enforce_eager: bool = False,
    ) -> CrossVendorEvidenceRecord:
        return _run_profile(
            self,
            profile,
            target,
            run_id=run_id,
            workload_id=workload_id,
            device_index=device_index,
            gpu_memory_utilization=gpu_memory_utilization,
            timeout_s=timeout_s,
            enforce_eager=enforce_eager,
        )


class RocmVllmBenchmarkRunner(BenchmarkRunner):
    vendor = "amd"

    def run(
        self,
        profile: BenchmarkProfile,
        target: ComputeTarget,
        *,
        run_id: str,
        workload_id: Optional[str] = None,
        device_index: int = 0,
        gpu_memory_utilization: Optional[float] = None,
        timeout_s: Optional[float] = None,
        enforce_eager: bool = False,
    ) -> CrossVendorEvidenceRecord:
        return _run_profile(
            self,
            profile,
            target,
            run_id=run_id,
            workload_id=workload_id,
            device_index=device_index,
            gpu_memory_utilization=gpu_memory_utilization,
            timeout_s=timeout_s,
            enforce_eager=enforce_eager,
        )


#: vendor string (ComputeTarget.vendor) -> runner, mirroring the pattern
#: app.cli.main.ADAPTERS already uses for discovery adapters.
RUNNERS_BY_VENDOR: dict[str, BenchmarkRunner] = {
    "nvidia": CudaVllmBenchmarkRunner(),
    "amd": RocmVllmBenchmarkRunner(),
}


def runner_for_target(target: ComputeTarget) -> BenchmarkRunner:
    runner = RUNNERS_BY_VENDOR.get(target.vendor)
    if runner is None:
        raise ProfileError(
            f"no benchmark runner registered for vendor '{target.vendor}' — "
            f"supported: {', '.join(sorted(RUNNERS_BY_VENDOR))}"
        )
    return runner
