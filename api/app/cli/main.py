"""The `forgeway` CLI: `forgeway discover`, `forgeway bench`, `forgeway runs`,
`forgeway analyze`.

Installed as a console script via api/pyproject.toml
(`pip install -e api/`, or `python -m app.cli.main <command>` without
installing). See docs/discovery.md, docs/benchmarking.md,
docs/decision-engine.md, and README.md's end-to-end CLI flow section.
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
from app.cli.yaml_io import AnalyzeError, load_policy_yaml, load_workload_yaml
from app.core.schemas import ComputeTarget, Workload
from app.core.schemas.v0_1 import PerformanceEvidence, PlacementDecision
from app.data.loader import load_compute_targets
from app.discovery.adapter import DiscoveryAdapter, DiscoveryError
from app.discovery.nvidia import NvidiaDiscoveryAdapter
from app.discovery.rocm import RocmDiscoveryAdapter
from app.engine.decision import run_decision
from app.models import Recommendation, ScenarioParams, ScenarioType

#: Adapters to try, in order. Adding a vendor is adding one line here plus
#: one new adapter class — see app/discovery/adapter.py.
ADAPTERS: list[DiscoveryAdapter] = [NvidiaDiscoveryAdapter(), RocmDiscoveryAdapter()]


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


def format_bench_human(evidence: PerformanceEvidence, saved_path: Path, model: str) -> str:
    lines = [
        "Forgeway benchmark: vllm bench latency",
        "",
        f"  Model            {model}",
        f"  Workload id      {evidence.workload_id}"
        + ("" if evidence.workload_id != model else "  (defaulted to --model; pass --workload-id to tag it as a real Forgeway workload)"),
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
    header = f"{'RUN ID':<20} {'TIMESTAMP':<26} {'WORKLOAD ID':<38} {'TARGET':<28} {'LATENCY (ms)':>12}"
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
            gpu_vendor=target.vendor,
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
        workload_id=args.workload_id,
    )
    saved_path = save_run(evidence, raw_output=raw.raw_json)

    if args.json:
        print(evidence.model_dump_json(indent=2))
    else:
        print(format_bench_human(evidence, saved_path, model=args.model))
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    runs = list_runs()
    if not runs:
        print(f"No benchmark runs found in {results_dir()}")
        return 0
    print(format_runs_table(runs))
    return 0


def _confidence_label(confidence: Optional[float]) -> str:
    """A simple, fixed-threshold convention for human-readable output —
    not a statistically derived bucketing. NONE when no recommendation
    was made at all (nothing to have confidence in)."""
    if confidence is None:
        return "NONE"
    if confidence >= 90:
        return "HIGH"
    if confidence >= 70:
        return "MEDIUM"
    return "LOW"


def format_analyze_human(
    workload: Workload,
    record: Recommendation,
    decision: PlacementDecision,
    targets_by_id: dict[str, ComputeTarget],
    discovery_note: Optional[str],
) -> str:
    """Built from two views of the same run_decision() output: `record`
    (Recommendation) for the narrative reasoning and full evidence
    PlacementDecision deliberately doesn't carry, and `decision`
    (PlacementDecision) for confidence and rejection reasons — reusing
    PlacementDecision.from_candidates()'s own reason-selection logic
    (RejectedTarget.reasons) rather than re-deriving it here a second
    time. `targets_by_id` only supplies display labels for targets
    PlacementDecision refers to by id."""

    def label(target_id: str) -> str:
        target = targets_by_id.get(target_id)
        return target.model if target is not None else target_id

    lines = ["FORGEWAY PLACEMENT DECISION", "", "Workload:", f"  {workload.name}", ""]

    lines += ["Recommended:"]
    if decision.recommended_target_id:
        lines.append(f"  {label(decision.recommended_target_id)}")
    else:
        lines.append("  None — no candidate cleared every requirement.")
    lines.append("")

    lines += ["Confidence:", f"  {_confidence_label(decision.confidence)}", ""]
    lines += ["Why:", f"  {record.reasoning}", ""]

    current = workload.current_placement
    lines += [
        "Current placement:",
        f"  {label(current.target_id)} — ${current.cost_per_hr:.2f}/hr",
        "",
    ]

    improvement = decision.improvement_vs_current_placement
    if improvement is not None and improvement.cost_savings_pct is not None:
        pct = improvement.cost_savings_pct
        # Ranking picks the best weighted blend of cost/performance/headroom,
        # not lowest cost alone — a recommendation costing *more* than the
        # current placement (better performance/headroom instead) is a real,
        # reachable outcome, not just a savings case.
        if pct > 0:
            direction = f"{pct:.1f}% lower cost"
        elif pct < 0:
            direction = f"{abs(pct):.1f}% higher cost"
        else:
            direction = "the same cost"
        lines += [
            "Estimated improvement:",
            f"  {direction} vs. current placement "
            f"(${improvement.current_cost_per_hr:.2f}/hr → ${improvement.recommended_cost_per_hr:.2f}/hr)",
            "",
        ]

    lines += ["SLO status:", f"  {'MET' if record.slo_met else 'VIOLATED'}", ""]

    lines.append("Evaluated:")
    rejected_reasons = {r.target_id: r.reasons for r in decision.rejected_targets}
    row_labels = {target_id: label(target_id) for target_id in decision.evaluated_targets}
    # Computed from the actual labels being printed, not a fixed width —
    # several real target names in this demo's own fixtures (e.g. "Jetson
    # AGX Thor 128GB", "RTX 6000 Ada (lab bench, 2x)") already exceed any
    # small fixed column width, which ran the status word straight into
    # the label with no separating space at all.
    column_width = max((len(l) for l in row_labels.values()), default=0) + 2
    for target_id in decision.evaluated_targets:
        row_label = row_labels[target_id]
        if target_id == decision.recommended_target_id:
            lines.append(f"  {row_label:<{column_width}}RECOMMENDED")
        elif target_id in rejected_reasons:
            reason = "; ".join(rejected_reasons[target_id]) or "not selected"
            lines.append(f"  {row_label:<{column_width}}REJECTED — {reason}")
        elif target_id in decision.feasible_targets:
            lines.append(f"  {row_label:<{column_width}}FEASIBLE")
        else:
            lines.append(f"  {row_label:<{column_width}}—")
    lines.append("")

    if record.evidence:
        lines.append("Critical evidence:")
        for e in record.evidence:
            lines.append(f"  {e.label:<32} {e.display_value:<20} {e.metric.provenance}")
        lines.append("")

    if discovery_note:
        lines.append(discovery_note)
        lines.append("")

    lines.append("Run `forgeway analyze ... --json` for the full PlacementDecision record.")
    return "\n".join(lines)


def cmd_analyze(args: argparse.Namespace) -> int:
    try:
        workload = load_workload_yaml(Path(args.workload_path))
        if args.policy:
            policy = load_policy_yaml(Path(args.policy))
            workload = workload.model_copy(update={"policy": policy})
    except AnalyzeError as e:
        print(f"forgeway analyze: {e}", file=sys.stderr)
        return 1

    # Step 2: fixture/reference data, and/or discovered local hardware.
    targets = list(load_compute_targets())
    targets_by_id = {t.id: t for t in targets}
    discovery_note = None
    if not args.skip_discovery:
        try:
            discovered = run_discovery()
        except DiscoveryError:
            discovery_note = "(No local hardware discovered — evaluated against the fixture catalog only.)"
        else:
            if discovered.id in targets_by_id:
                discovery_note = (
                    f"(Local hardware discovered: {discovered.model} — already present in the "
                    f"fixture catalog as '{discovered.id}'; using the fixture entry.)"
                )
            else:
                targets.append(discovered)
                targets_by_id[discovered.id] = discovered
                discovery_note = f"(Included locally discovered target: {discovered.model} [{discovered.id}].)"

    # Steps 3-5: the same core engine the web app calls — app.engine.decision
    # .run_decision() — gathers relevant PerformanceEvidence and returns a
    # Recommendation; PlacementDecision.from_candidates() reframes its
    # candidates as the vendor-neutral record this command returns.
    record = run_decision(
        workload,
        record_id=f"analyze-{uuid.uuid4().hex[:12]}",
        scenario=ScenarioParams(type=ScenarioType.normal, label="Normal — baseline, no scenario applied"),
        effective_min_throughput=workload.slo.min_throughput_tokens_per_s,
        targets=targets,
    )
    decision = PlacementDecision.from_candidates(workload, record.candidates)

    if args.json:
        print(decision.model_dump_json(indent=2))
    else:
        print(format_analyze_human(workload, record, decision, targets_by_id, discovery_note))
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
        "--workload-id",
        default=None,
        help=(
            "Tag the saved evidence with an existing Forgeway workload id (e.g. wl-llama70b-rt) "
            "so the placement engine can select it for that workload — see docs/importing-results.md. "
            "Only honest when --model actually corresponds to that workload (same model family/parameter "
            "count); this demo's default --model (Llama 3.1 8B) does not correspond to any of the five "
            "demo workloads, so do not tag it as one of them. Defaults to --model's value, which is never "
            "selectable against a real workload but also never collides with one."
        ),
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

    analyze_parser = subparsers.add_parser(
        "analyze", help="Run the placement decision engine against a YAML-defined workload."
    )
    analyze_parser.add_argument(
        "workload_path", help="Path to an AIWorkload YAML file (see examples/workload.yaml)."
    )
    analyze_parser.add_argument(
        "--policy",
        default=None,
        help="Path to an EnterprisePolicy YAML file overriding the workload's own policy for this run "
        "(see examples/policy.yaml).",
    )
    analyze_parser.add_argument(
        "--skip-discovery",
        action="store_true",
        help="Don't attempt local hardware discovery; evaluate against the fixture catalog only.",
    )
    analyze_parser.add_argument(
        "--json", action="store_true", help="Emit the full PlacementDecision JSON record instead of text."
    )
    analyze_parser.set_defaults(func=cmd_analyze)

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
