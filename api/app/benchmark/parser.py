"""Parses `vllm bench latency --output-json`'s output into a structured,
partial-tolerant result.

Knows nothing about subprocesses, vLLM's CLI invocation, or GPU sampling —
it only turns an already-loaded JSON dict into a ParsedLatencyResult. This
separation is deliberate: result parsing should be testable with nothing
but static JSON fixtures, no mocking of subprocess or the filesystem.

Never fabricates a metric: an unrecognized or missing field is left
unset (the caller treats that as "unavailable", not zero or guessed).
Only a genuinely unusable result — no average latency at all, the one
number this benchmark exists to produce — is a hard failure.

IMPORTANT: the exact key names below reflect vLLM's documented
`vllm bench latency --output-json` shape as of the vLLM versions this was
written against; they have NOT been verified against a live vLLM
installation in this repository's development environment (no CUDA GPU
available here — see docs/benchmarking.md's reproducibility caveats). If
a future vLLM version renames these keys, this parser will raise
BenchmarkError (for the required avg-latency key) or simply omit affected
optional metrics — it will not silently report fabricated numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.benchmark.errors import BenchmarkError

_AVG_LATENCY_KEYS = ("avg_latency", "average_latency", "avg_latency_s")
_PERCENTILES_KEYS = ("percentiles",)


@dataclass
class ParsedLatencyResult:
    avg_latency_s: float
    percentiles_s: dict[str, float] = field(default_factory=dict)


def parse_vllm_latency_output(raw: dict) -> ParsedLatencyResult:
    avg_latency_s = None
    for key in _AVG_LATENCY_KEYS:
        value = raw.get(key)
        if isinstance(value, (int, float)):
            avg_latency_s = float(value)
            break
    if avg_latency_s is None:
        raise BenchmarkError(
            "could not find an average-latency value in vllm bench latency's output "
            f"(looked for: {', '.join(_AVG_LATENCY_KEYS)}). The benchmark may have produced "
            "an unexpected output format for this vLLM version — check the saved raw output "
            "file for this run (see docs/benchmarking.md)."
        )

    percentiles_s: dict[str, float] = {}
    for key in _PERCENTILES_KEYS:
        value = raw.get(key)
        if isinstance(value, dict):
            for pct_label, pct_value in value.items():
                if isinstance(pct_value, (int, float)):
                    percentiles_s[str(pct_label)] = float(pct_value)
            break

    return ParsedLatencyResult(avg_latency_s=avg_latency_s, percentiles_s=percentiles_s)
