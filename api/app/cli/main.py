"""The `forgeway` CLI: `forgeway discover`, `forgeway bench`, `forgeway runs`.

Installed as a console script via api/pyproject.toml
(`pip install -e api/`, or `python -m app.cli.main <command>` without
installing). See docs/discovery.md and docs/benchmarking.md.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path
from typing import Optional

from app.benchmark.errors import BenchmarkError
from app.benchmark.evidence import build_performance_evidence
from app.benchmark.parser import parse_vllm_latency_output
from app.benchmark.store import list_runs, results_dir, save_run
from app.benchmark.vllm_runner import (
    DEFAULT_ITERATIONS,
    DEFAULT_TIMEOUT_S,
    DEFAULT_WARMUP_ITERATIONS,
    run_vllm_bench_latency,
)
from app.core.schemas import ComputeTarget
from app.core.schemas.v0_1 import PerformanceEvidence
from app.discovery.adapter import DiscoveryAdapter, DiscoveryError
from app.discovery.nvidia import NvidiaDiscoveryAdapter

#: Adapters to try, in order. Adding a vendor is adding one line here plus
#: one new adapter class — see app/discovery/adapter.py.
ADAPTERS: list[DiscoveryAdapter] = [NvidiaDiscoveryAdapter()]


def run_discovery(adapters: Optional[list[DiscoveryAdapter]] = None) -> ComputeTarget:
    """Tries each adapter's is_available() in order and returns the first
    one's discover() result. Raises DiscoveryError, with a message safe to
    print directly to a user, if none of this machine's tooling is
    supported yet. Defaults to the module-level ADAPTERS list, resolved at
    call time (not at import time) so tests can reassign
    app.cli.main.ADAPTERS and have this function pick up the change."""
    if adapters is None:
        adapters = ADAPTERS
    for adapter in adapters:
        if adapter.is_available():
            return adapter.discover()
    names = ", ".join(a.name for a in adapters) or "(none configured)"
    raise DiscoveryError(
        "No supported accelerator was detected on this machine. "
        f"Checked: {names}. See docs/discovery.md for what's supported."
    )


def format_human(target: ComputeTarget) -> str:
    lines = [
        "Forgeway discovery: local compute target",
        "",
        f"  Vendor / model   {target.vendor} — {target.model}",
        f"  Devices          {target.accelerator_count}",
        f"  Memory / device  {target.memory_gb_per_device:.1f} GB",
        f"  Architecture     {target.architecture}",
        f"  Tier / location  {target.tier} — {target.location}",
        f"  Status           {target.status}",
    ]
    if target.observed_gpu_utilization_pct is not None:
        lines.append(
            f"  Utilization      {target.observed_gpu_utilization_pct:.0f}% GPU, "
            f"{target.observed_memory_utilization_pct:.0f}% memory (observed)"
        )
    if target.discovered_at is not None:
        lines.append(f"  Discovered at    {target.discovered_at.isoformat()}")
    lines.append("")
    lines.append(f"  {target.notes}")
    lines.append("")
    lines.append("Run `forgeway discover --json` for the full ComputeTarget record.")
    return "\n".join(lines)


def cmd_discover(args: argparse.Namespace) -> int:
    try:
        target = run_discovery()
    except DiscoveryError as e:
        print(f"forgeway discover: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(target.model_dump_json(indent=2))
    else:
        print(format_human(target))
    return 0


_BENCH_METRIC_LABELS: list[tuple[str, str, str]] = [
    ("end_to_end_latency_ms", "End-to-end latency", "ms"),
    ("p50_latency_ms", "P50 latency", "ms"),
    ("p99_latency_ms", "P99 latency", "ms"),
    ("output_token_throughput_tokens_per_s", "Output token throughput", "tok/s"),
    ("request_throughput_requests_per_s", "Request throughput", "req/s"),
    ("peak_gpu_memory_used_mb", "Peak GPU memory used", "MB"),
    ("avg_gpu_power_draw_w", "Avg GPU power draw", "W"),
]


def format_bench_human(evidence: PerformanceEvidence, saved_path: Path) -> str:
    lines = [
        "Forgeway benchmark: vllm bench latency",
        "",
        f"  Model            {evidence.workload_id}",
        f"  Target           {evidence.compute_target_id}",
        f"  Configuration    {evidence.configuration}",
        f"  Run id           {evidence.benchmark_run_id}",
        "",
    ]
    for key, label, unit in _BENCH_METRIC_LABELS:
        metric = evidence.metrics.get(key)
        if metric is not None:
            lines.append(f"  {label:<24} {metric.value:.2f} {unit}")
    lines.append("")
    lines.append(
        "  TTFT: not measured by this benchmark path — vllm bench latency measures\n"
        "  full-completion latency, not streaming. See docs/benchmarking.md."
    )
    lines.append("")
    lines.append(f"Saved to {saved_path}")
    lines.append("Run `forgeway bench ... --json` for the full PerformanceEvidence record.")
    return "\n".join(lines)


def format_runs_table(runs: list[PerformanceEvidence]) -> str:
    header = f"{'RUN ID':<20} {'TIMESTAMP':<26} {'MODEL':<38} {'TARGET':<28} {'LATENCY (ms)':>12}"
    lines = [header, "-" * len(header)]
    for r in runs:
        latency = r.metrics.get("end_to_end_latency_ms")
        latency_str = f"{latency.value:.1f}" if latency is not None else "n/a"
        timestamp_str = r.timestamp.isoformat() if r.timestamp is not None else "unknown"
        lines.append(
            f"{(r.benchmark_run_id or '?'):<20} {timestamp_str:<26} {r.workload_id:<38} "
            f"{r.compute_target_id:<28} {latency_str:>12}"
        )
    return "\n".join(lines)


def cmd_bench(args: argparse.Namespace) -> int:
    try:
        target = run_discovery()
    except DiscoveryError as e:
        print(f"forgeway bench: {e}", file=sys.stderr)
        return 1

    run_id = f"bench-{uuid.uuid4().hex[:12]}"
    try:
        raw = run_vllm_bench_latency(
            model=args.model,
            input_tokens=args.input_tokens,
            output_tokens=args.output_tokens,
            concurrency=args.concurrency,
            iterations=args.iterations,
            warmup_iterations=args.warmup_iterations,
            timeout_s=args.timeout_s,
            device_index=args.device_index,
        )
        parsed = parse_vllm_latency_output(raw.raw_json)
    except BenchmarkError as e:
        print(f"forgeway bench: {e}", file=sys.stderr)
        return 1

    evidence = build_performance_evidence(
        compute_target=target,
        model=args.model,
        input_tokens=args.input_tokens,
        output_tokens=args.output_tokens,
        concurrency=args.concurrency,
        parsed=parsed,
        gpu_samples=raw.gpu_samples,
        run_id=run_id,
    )
    saved_path = save_run(evidence, raw_output=raw.raw_json)

    if args.json:
        print(evidence.model_dump_json(indent=2))
    else:
        print(format_bench_human(evidence, saved_path))
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    runs = list_runs()
    if not runs:
        print(f"No benchmark runs found in {results_dir()}")
        return 0
    print(format_runs_table(runs))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forgeway", description="Forgeway workload intelligence CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover_parser = subparsers.add_parser(
        "discover", help="Detect local compute hardware and describe it as a ComputeTarget."
    )
    discover_parser.add_argument(
        "--json", action="store_true", help="Emit a Forgeway ComputeTarget JSON object instead of text."
    )
    discover_parser.set_defaults(func=cmd_discover)

    bench_parser = subparsers.add_parser(
        "bench", help="Run the vllm bench latency benchmark against the local NVIDIA GPU."
    )
    bench_parser.add_argument(
        "--model", default="meta-llama/Llama-3.1-8B-Instruct", help="Model to benchmark (default: %(default)s)."
    )
    bench_parser.add_argument(
        "--input-tokens", type=int, default=512, help="Input sequence length (default: %(default)s)."
    )
    bench_parser.add_argument(
        "--output-tokens", type=int, default=128, help="Tokens to generate per request (default: %(default)s)."
    )
    bench_parser.add_argument(
        "--concurrency", type=int, default=1, help="Batch size / concurrent requests (default: %(default)s)."
    )
    bench_parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
        help="Timed iterations to average over (default: %(default)s).",
    )
    bench_parser.add_argument(
        "--warmup-iterations",
        type=int,
        default=DEFAULT_WARMUP_ITERATIONS,
        help="Warmup iterations, discarded from results (default: %(default)s).",
    )
    bench_parser.add_argument(
        "--timeout-s",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help="Give up if the benchmark hasn't finished within this many seconds (default: %(default)s).",
    )
    bench_parser.add_argument(
        "--device-index", type=int, default=0, help="GPU index to target and sample telemetry from (default: %(default)s)."
    )
    bench_parser.add_argument(
        "--json", action="store_true", help="Emit the full PerformanceEvidence JSON record instead of text."
    )
    bench_parser.set_defaults(func=cmd_bench)

    runs_parser = subparsers.add_parser("runs", help="List locally stored benchmark runs.")
    runs_parser.set_defaults(func=cmd_runs)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as e:  # last-resort safety net — never show a raw traceback
        print(f"forgeway: unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
