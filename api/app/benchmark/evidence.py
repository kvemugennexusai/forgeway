"""Combines a ParsedLatencyResult + GPU samples + a ComputeTarget into a
PerformanceEvidence record (app.core.schemas.v0_1) — a pure function, no
subprocess or filesystem access, so it's testable with nothing but plain
Python objects.

Every metric included here is either a direct measurement (latency,
percentiles, GPU telemetry) or a plain arithmetic derivation from a
measurement plus known, requested parameters (throughput = tokens /
measured latency) — never a guess or a model. A metric this benchmark
path can't produce (see docs/benchmarking.md, notably TTFT) is simply
absent from the returned `metrics` dict, per Forgeway's "never fabricate a
metric" rule.

Canonical key aliasing (docs/decision-engine.md, docs/importing-results.md):
app.core.engine.evidence_selection.select_evidence requires the exact keys
LATENCY_METRIC_KEY / THROUGHPUT_METRIC_KEY to consider evidence usable for
scoring. This function adds those as aliases of this run's own
p99_latency_ms / output_token_throughput_tokens_per_s metrics *when a real
P99 percentile was captured* — never aliased from end_to_end_latency_ms
(an average across --iterations runs), since presenting an average as a
P99 would misrepresent what was actually measured. With the default
--iterations (3), "P99" is itself a thin statistic; docs/benchmarking.md
recommends more iterations for anything beyond a demo.

`workload_id` vs `model` (docs/importing-results.md): the engine matches
evidence to a workload by an exact `workload_id` string
(app.engine.evidence_gateway.gather_evidence_candidates) — a HuggingFace
model string like `meta-llama/Llama-3.1-8B-Instruct` will never equal an
existing Forgeway workload's id (e.g. `wl-llama70b-rt`), so a caller that
wants this evidence to actually be considered for a real workload must
pass that workload's id explicitly via `workload_id`. Passing it is only
honest when the benchmarked model actually corresponds to that workload
(same family/parameter count) — tagging an unrelated model's numbers with
someone else's workload id would misrepresent what was measured, exactly
like the P99 aliasing rule above. Omitting `workload_id` preserves the
original behavior (workload_id defaults to `model`), which is never
selectable against a real workload but is always safe: it can't
accidentally collide with — or override — a workload's own evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.benchmark.gpu_sampler import GpuSample
from app.benchmark.parser import ParsedLatencyResult
from app.core.schemas import LATENCY_METRIC_KEY, THROUGHPUT_METRIC_KEY, ComputeTarget, Metric
from app.core.schemas.v0_1 import PerformanceEvidence

#: Confidence conventions for this benchmark path — not a computed
#: statistical interval, just "how much to trust this number" on the same
#: 0-100 scale every other Metric in Forgeway uses. Direct vLLM-reported
#: latency numbers get the highest confidence; GPU telemetry sampled by a
#: separate, best-effort poller (not vLLM itself) gets slightly less.
_LATENCY_CONFIDENCE = 95.0
_MEMORY_CONFIDENCE = 90.0
_POWER_CONFIDENCE = 85.0


def build_performance_evidence(
    *,
    compute_target: ComputeTarget,
    model: str,
    input_tokens: int,
    output_tokens: int,
    concurrency: int,
    parsed: ParsedLatencyResult,
    gpu_samples: list[GpuSample],
    run_id: str,
    workload_id: Optional[str] = None,
) -> PerformanceEvidence:
    metrics: dict[str, Metric] = {}
    source = f"vllm bench latency, model={model}"

    metrics["end_to_end_latency_ms"] = Metric(
        value=round(parsed.avg_latency_s * 1000, 2),
        confidence=_LATENCY_CONFIDENCE,
        provenance="MEASURED",
        source=source,
    )
    # Derived, not fabricated: computed directly from the measured average
    # latency and the token/concurrency counts this run was configured
    # with — the same arithmetic any latency benchmark uses to report
    # throughput from a stopwatch time and a known request count.
    metrics["output_token_throughput_tokens_per_s"] = Metric(
        value=round((output_tokens * concurrency) / parsed.avg_latency_s, 2),
        confidence=_LATENCY_CONFIDENCE,
        provenance="MEASURED",
        source="derived: (output_tokens * concurrency) / measured avg latency",
    )
    metrics["request_throughput_requests_per_s"] = Metric(
        value=round(concurrency / parsed.avg_latency_s, 4),
        confidence=_LATENCY_CONFIDENCE,
        provenance="MEASURED",
        source="derived: concurrency / measured avg latency",
    )

    for pct_label, pct_value_s in parsed.percentiles_s.items():
        metrics[f"p{pct_label}_latency_ms"] = Metric(
            value=round(pct_value_s * 1000, 2),
            confidence=_LATENCY_CONFIDENCE,
            provenance="MEASURED",
            source=source,
        )

    # Canonical aliases the engine's evidence selection looks for — see the
    # module docstring. Throughput is always derivable; latency only when a
    # real P99 was captured (never aliased from the plain average).
    metrics[THROUGHPUT_METRIC_KEY] = metrics["output_token_throughput_tokens_per_s"]
    if "p99_latency_ms" in metrics:
        metrics[LATENCY_METRIC_KEY] = metrics["p99_latency_ms"]

    memory_samples = [s.memory_used_mb for s in gpu_samples if s.memory_used_mb is not None]
    if memory_samples:
        metrics["peak_gpu_memory_used_mb"] = Metric(
            value=round(max(memory_samples), 1),
            confidence=_MEMORY_CONFIDENCE,
            provenance="MEASURED",
            source=f"nvidia-smi, sampled during the run (n={len(memory_samples)})",
        )

    power_samples = [s.power_draw_w for s in gpu_samples if s.power_draw_w is not None]
    if power_samples:
        metrics["avg_gpu_power_draw_w"] = Metric(
            value=round(sum(power_samples) / len(power_samples), 1),
            confidence=_POWER_CONFIDENCE,
            provenance="MEASURED",
            source=f"nvidia-smi, averaged over samples during the run (n={len(power_samples)})",
        )

    confidence = min(m.confidence for m in metrics.values())

    return PerformanceEvidence(
        compute_target_id=compute_target.id,
        workload_id=workload_id if workload_id is not None else model,
        configuration=(
            f"vllm bench latency: input_len={input_tokens}, output_len={output_tokens}, "
            f"batch_size={concurrency}"
        ),
        metrics=metrics,
        provenance="MEASURED",
        confidence=confidence,
        source="vllm bench latency (offline, single-node, no server)",
        timestamp=datetime.now(timezone.utc),
        benchmark_run_id=run_id,
    )
