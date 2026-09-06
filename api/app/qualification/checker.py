"""Staged qualification checking: runtime present -> device reachable ->
config supported -> smoke test passed, run in that order, stopping at the
first failure — a later stage presupposes every earlier one, and an
installed plugin or registered entry point only proves runtime_present,
nothing about the stages after it.

Deliberate invariant this whole module enforces: nothing here ever
produces state="unsupported". Per the qualification-state model
(app.core.schemas.v0_1.qualification), "unsupported" means "a documented
constraint applies" — that requires a real, citable source a human
supplies (`forgeway qualify-import`), not an inference Forgeway draws from
one failed automated run, which could be transient, environment-specific,
or a version-specific bug rather than a fundamental incompatibility.
Every automated stage failure here downgrades to "unknown" instead: honest
about not knowing, never overclaiming a vendor-behavior fact the pipeline
didn't actually verify.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from app.benchmark.cross_vendor import dtype_for_precision
from app.benchmark.errors import BenchmarkError
from app.benchmark.evidence import build_performance_evidence
from app.benchmark.parser import parse_vllm_latency_output
from app.benchmark.store import save_run
from app.benchmark.vllm_runner import is_vllm_available, run_vllm_bench_latency
from app.core.schemas import ComputeTarget
from app.core.schemas.v0_1 import PerformanceEvidence
from app.core.schemas.v0_1.qualification import (
    QualificationRecord,
    QualificationStageResult,
    QualificationSubject,
)
from app.discovery.adapter import DiscoveryAdapter, discover_all
from app.discovery.nvidia import NvidiaDiscoveryAdapter
from app.discovery.rocm import RocmDiscoveryAdapter

#: Deliberately tiny — this is a smoke test ("did it run at all"), not a
#: benchmark. `forgeway bench-profile` is the real, statistically
#: meaningful path (docs/benchmarking.md).
_SMOKE_TEST_INPUT_TOKENS = 32
_SMOKE_TEST_OUTPUT_TOKENS = 8


class RuntimeChecker(ABC):
    """One runtime's way of answering the four staged qualification
    questions for a given subject and an already-discovered target.
    Mirrors app.discovery.adapter.DiscoveryAdapter's minimal, no-registry
    convention — one class per runtime, nothing shared but the interface.
    Target resolution/discovery is the caller's job (see
    app.cli.main.resolve_bench_target); a checker only ever verifies."""

    runtime: str

    @abstractmethod
    def runtime_present(self) -> QualificationStageResult:
        """Is this runtime actually usable at all on this machine — never
        just "is a plugin/entry point registered for it" (that proves
        nothing about the stages below)."""

    @abstractmethod
    def device_reachable(
        self, subject: QualificationSubject, target: ComputeTarget
    ) -> QualificationStageResult: ...

    @abstractmethod
    def config_supported(
        self, subject: QualificationSubject, target: ComputeTarget
    ) -> QualificationStageResult:
        """Best-effort structural checks only (e.g. does the requested
        tensor-parallel degree fit the discovered device count) — passing
        this stage does not guarantee runtime acceptance. Only the smoke
        test below genuinely proves that."""

    @abstractmethod
    def smoke_test(
        self, subject: QualificationSubject, target: ComputeTarget
    ) -> tuple[QualificationStageResult, Optional[PerformanceEvidence]]:
        """Runs a minimal real invocation. Returns the stage result and,
        only on success, the real PerformanceEvidence it produced (already
        saved via app.benchmark.store.save_run, so it's inspectable via
        `forgeway runs` like any other real benchmark)."""


class VllmRuntimeChecker(RuntimeChecker):
    runtime = "vllm"

    def __init__(self, adapters: Optional[list[DiscoveryAdapter]] = None):
        #: Defaults to the same two real adapters app.cli.main.ADAPTERS
        #: uses — injectable so tests never touch subprocess/nvidia-smi.
        self._adapters: list[DiscoveryAdapter] = (
            adapters if adapters is not None else [NvidiaDiscoveryAdapter(), RocmDiscoveryAdapter()]
        )

    def runtime_present(self) -> QualificationStageResult:
        present = is_vllm_available()
        return QualificationStageResult(
            stage="runtime_present",
            passed=present,
            detail="vllm is on PATH" if present else "vllm is not installed or not on PATH",
        )

    def device_reachable(self, subject: QualificationSubject, target: ComputeTarget) -> QualificationStageResult:
        result = discover_all(self._adapters)
        reachable = any(t.vendor == target.vendor for t in result.targets)
        detail = (
            f"a {target.vendor} device is reachable through local discovery"
            if reachable
            else f"no {target.vendor} device was reachable through local discovery"
            + (f" (errors: {'; '.join(f'{e.adapter}: {e.message}' for e in result.errors)})" if result.errors else "")
        )
        return QualificationStageResult(stage="device_reachable", passed=reachable, detail=detail)

    def config_supported(self, subject: QualificationSubject, target: ComputeTarget) -> QualificationStageResult:
        problems: list[str] = []
        tensor_parallel_degree = subject.deployment_config.get("tensor_parallel_degree", 1)
        if isinstance(tensor_parallel_degree, int) and tensor_parallel_degree > target.accelerator_count:
            problems.append(
                f"requested tensor_parallel_degree={tensor_parallel_degree} exceeds "
                f"{target.accelerator_count} device(s) reachable on {target.model}"
            )

        dtype = dtype_for_precision(subject.precision)
        if problems:
            detail = "; ".join(problems)
        elif dtype is not None:
            detail = (
                f"precision '{subject.precision}' maps to vLLM --dtype '{dtype}'; requested tensor "
                "parallelism fits the discovered device count (structural check only — passing this "
                "does not guarantee runtime acceptance; only the smoke test genuinely proves that)"
            )
        else:
            detail = (
                f"precision '{subject.precision}' has no known --dtype mapping — vLLM's own default "
                "would apply if run, not independently verified by this stage"
            )
        return QualificationStageResult(stage="config_supported", passed=not problems, detail=detail)

    def smoke_test(
        self, subject: QualificationSubject, target: ComputeTarget
    ) -> tuple[QualificationStageResult, Optional[PerformanceEvidence]]:
        run_id = f"qual-smoke-{uuid.uuid4().hex[:12]}"
        try:
            raw = run_vllm_bench_latency(
                model=subject.model,
                input_tokens=_SMOKE_TEST_INPUT_TOKENS,
                output_tokens=_SMOKE_TEST_OUTPUT_TOKENS,
                concurrency=1,
                iterations=1,
                warmup_iterations=0,
                gpu_vendor=target.vendor,
                dtype=dtype_for_precision(subject.precision),
                tensor_parallel_size=subject.deployment_config.get("tensor_parallel_degree"),
                quantization=subject.deployment_config.get("quantization"),
                max_model_len=subject.deployment_config.get("max_model_len"),
            )
            parsed = parse_vllm_latency_output(raw.raw_json)
        except BenchmarkError as e:
            return QualificationStageResult(stage="smoke_test_passed", passed=False, detail=str(e)), None

        evidence = build_performance_evidence(
            compute_target=target,
            model=subject.model,
            input_tokens=_SMOKE_TEST_INPUT_TOKENS,
            output_tokens=_SMOKE_TEST_OUTPUT_TOKENS,
            concurrency=1,
            parsed=parsed,
            gpu_samples=raw.gpu_samples,
            run_id=run_id,
        )
        save_run(evidence)
        return (
            QualificationStageResult(
                stage="smoke_test_passed", passed=True, detail=f"smoke test run {run_id} completed"
            ),
            evidence,
        )


def run_qualification_pipeline(
    checker: RuntimeChecker,
    subject: QualificationSubject,
    target: ComputeTarget,
    *,
    source: str,
    environment: str,
    review_date: Optional[date] = None,
) -> QualificationRecord:
    """Runs every stage in order, stopping at the first failure, and
    derives a QualificationRecord from how far it got. Never returns
    state="unsupported" — see module docstring. When `subject.slo` is set
    and the smoke test completes, its own single-iteration metrics are
    compared against that SLO's thresholds for a `measured_pass`/
    `measured_fail` outcome — a real evaluation, but an honest, best-effort
    one (a single-iteration smoke test has no statistically valid P99 of
    its own; see the resulting record's `notes`)."""
    stages: list[QualificationStageResult] = []

    def stopped(stage_name: str) -> QualificationRecord:
        return QualificationRecord.for_subject(
            subject,
            state="unknown",
            stages=list(stages),
            source=source,
            environment=environment,
            review_date=review_date,
            notes=f"staged checking stopped at '{stage_name}' — see stages for the exact reason.",
        )

    result = checker.runtime_present()
    stages.append(result)
    if not result.passed:
        return stopped("runtime_present")

    result = checker.device_reachable(subject, target)
    stages.append(result)
    if not result.passed:
        return stopped("device_reachable")

    result = checker.config_supported(subject, target)
    stages.append(result)
    if not result.passed:
        return stopped("config_supported")

    result, evidence = checker.smoke_test(subject, target)
    stages.append(result)
    if not result.passed:
        return stopped("smoke_test_passed")
    assert evidence is not None  # RuntimeChecker's own contract: passed => evidence is set

    if subject.slo is None:
        return QualificationRecord.for_subject(
            subject, state="smoke_tested", stages=stages, source=source, environment=environment,
            review_date=review_date,
        )

    latency_ms = evidence.metrics["end_to_end_latency_ms"].value
    throughput = evidence.metrics["output_token_throughput_tokens_per_s"].value
    meets_slo = latency_ms <= subject.slo.p99_latency_ms and throughput >= subject.slo.min_throughput_tokens_per_s
    return QualificationRecord.for_subject(
        subject,
        state="measured_pass" if meets_slo else "measured_fail",
        stages=stages,
        source=source,
        environment=environment,
        evidence_reference=evidence.benchmark_run_id,
        review_date=review_date,
        notes=(
            "Single-iteration smoke test: the observed end-to-end latency is compared to the "
            "workload's P99 threshold as a best-effort proxy, not a statistically valid P99 estimate. "
            "See `forgeway bench-profile` for a real, multi-iteration benchmark."
        ),
    )
