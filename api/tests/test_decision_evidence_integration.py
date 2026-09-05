"""Integration tests proving app.engine.decision.run_decision actually uses
the unified evidence path (docs/decision-engine.md) — not just that
app.core.engine.evidence_selection works in isolation (see
tests/test_evidence_selection.py).

FORGEWAY_BENCH_DIR is monkeypatched to a tmp_path in every test that saves
a benchmark run, so nothing here ever touches ~/.forgeway/benchmarks.
"""
from __future__ import annotations

from app.benchmark.evidence import build_performance_evidence
from app.benchmark.parser import ParsedLatencyResult
from app.benchmark.store import list_runs, save_run
from app.core.engine.evidence_selection import select_evidence
from app.core.schemas import LATENCY_METRIC_KEY, THROUGHPUT_METRIC_KEY, Metric
from app.core.schemas.v0_1 import PerformanceEvidence
from app.data.loader import get_workload, load_compute_targets
from app.engine.decision import run_decision
from app.engine.evidence_gateway import gather_evidence_candidates
from app.models import ScenarioParams, ScenarioType


def _normal_scenario() -> ScenarioParams:
    return ScenarioParams(type=ScenarioType.normal, label="Normal — baseline, no scenario applied")


def _real_measured_run(
    *, target_id: str, throughput: float, latency_ms: float, confidence: float = 97.0
) -> PerformanceEvidence:
    """A stand-in for what `forgeway bench` actually saves: real,
    MEASURED PerformanceEvidence using the canonical per-replica metric
    keys the engine reads (docs/decision-engine.md's known limitation —
    forgeway bench's own metric names differ and aren't yet bridged to
    these; this constructs what a bridged/matching run would look like)."""
    return PerformanceEvidence(
        compute_target_id=target_id,
        workload_id="wl-llama70b-rt",
        metrics={
            THROUGHPUT_METRIC_KEY: Metric(
                value=throughput, confidence=confidence, provenance="MEASURED", source="test measured run"
            ),
            LATENCY_METRIC_KEY: Metric(
                value=latency_ms, confidence=confidence, provenance="MEASURED", source="test measured run"
            ),
        },
        provenance="MEASURED",
        confidence=confidence,
        source="test measured run",
        benchmark_run_id="bench-test-integration",
    )


# --------------------------------------------------------------------------
# gather_evidence_candidates — the connection point itself
# --------------------------------------------------------------------------


def test_gather_evidence_candidates_includes_a_matching_saved_benchmark_run(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path))
    run = _real_measured_run(target_id="amd-mi300x", throughput=1500.0, latency_ms=300.0)
    save_run(run)

    from app.benchmark.store import list_runs

    candidates = gather_evidence_candidates("wl-llama70b-rt", "amd-mi300x", benchmark_runs=list_runs())

    assert any(c.benchmark_run_id == "bench-test-integration" for c in candidates)
    # the fixture-derived MODELED evidence for this exact pair is also present
    assert any(c.provenance == "MODELED" for c in candidates)


def test_gather_evidence_candidates_ignores_a_run_for_a_different_target(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path))
    run = _real_measured_run(target_id="nvidia-h100-dc", throughput=1500.0, latency_ms=300.0)
    save_run(run)

    from app.benchmark.store import list_runs

    candidates = gather_evidence_candidates("wl-llama70b-rt", "amd-mi300x", benchmark_runs=list_runs())

    assert not any(c.benchmark_run_id == "bench-test-integration" for c in candidates)


# --------------------------------------------------------------------------
# Missing evidence, handled safely
# --------------------------------------------------------------------------


def test_missing_evidence_is_handled_safely_end_to_end():
    """A target with zero evidence anywhere (no fixture row, no benchmark
    run) must be marked insufficient-evidence, not crash and not invent a
    number."""
    candidates = gather_evidence_candidates("wl-llama70b-rt", "no-such-target", benchmark_runs=[])
    assert candidates == []

    chosen = select_evidence(candidates, required_metrics=(LATENCY_METRIC_KEY, THROUGHPUT_METRIC_KEY))
    assert chosen is None


def test_recommendation_still_works_when_benchmark_store_is_empty(tmp_path, monkeypatch):
    """The unified path must not require any real benchmark runs to exist —
    an empty (or missing) ~/.forgeway/benchmarks is the common case."""
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path / "does-not-exist"))
    workload = get_workload("wl-llama70b-rt")
    assert workload is not None

    record = run_decision(
        workload,
        record_id="rec-test-empty-store",
        scenario=_normal_scenario(),
        effective_min_throughput=workload.slo.min_throughput_tokens_per_s,
    )

    assert record.recommended_target_id == "amd-mi300x"  # unchanged from the known baseline


# --------------------------------------------------------------------------
# Policy confidence threshold affects eligibility, with real evidence
# --------------------------------------------------------------------------


def test_confidence_threshold_blocks_the_only_fixture_evidence_at_baseline(tmp_path, monkeypatch):
    """Baseline, no extra evidence: at a 95% confidence bar, neither H100
    (92%) nor MI300X's MODELED evidence (78%) qualifies — matches
    tests/test_scenarios.py's known strict-confidence-policy behavior."""
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path))
    workload = get_workload("wl-llama70b-rt")
    assert workload is not None

    record = run_decision(
        workload,
        record_id="rec-test-strict-baseline",
        scenario=_normal_scenario(),
        effective_min_throughput=workload.slo.min_throughput_tokens_per_s,
        min_confidence_pct=95.0,
    )

    assert record.recommended_target_id is None
    assert not record.split_allocation


# --------------------------------------------------------------------------
# The flagship behavior: recommendation changes when stronger evidence
# becomes available.
# --------------------------------------------------------------------------


def test_recommendation_changes_when_stronger_measured_evidence_is_introduced(tmp_path, monkeypatch):
    """Same workload, same 85% confidence policy, same fixtures — the only
    thing that changes between the two run_decision() calls is that a real
    MEASURED benchmark run for amd-mi300x becomes available in between.

    At 85%: H100's MEASURED evidence (confidence 97, capped to 92 overall
    by its own pricing confidence) already qualifies; MI300X's only prior
    evidence (MODELED, confidence 78) does not, so H100 is recommended
    solo. Once a real, high-confidence MEASURED run for MI300X is
    introduced — replacing the old MODELED evidence via select_evidence's
    MEASURED > MODELED preference — MI300X's overall confidence rises to
    90 (still capped by its own pricing confidence, but now above the 85%
    bar), so it also qualifies. With both qualifying, MI300X wins on
    weighted score exactly as it already does in the workload's own
    default-confidence baseline (tests/test_engine.py::
    test_baseline_recommends_mi300x_over_h100) — so the recommendation
    switches from H100 to MI300X.
    """
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path))
    workload = get_workload("wl-llama70b-rt")
    assert workload is not None

    before = run_decision(
        workload,
        record_id="rec-test-before-stronger-evidence",
        scenario=_normal_scenario(),
        effective_min_throughput=workload.slo.min_throughput_tokens_per_s,
        min_confidence_pct=85.0,
    )
    assert before.recommended_target_id == "nvidia-h100-dc"

    # A real `forgeway bench` run for this exact workload/target becomes
    # available — same throughput/latency as the old MODELED estimate, so
    # confidence is the only variable that changed.
    save_run(_real_measured_run(target_id="amd-mi300x", throughput=1400.0, latency_ms=310.0, confidence=97.0))

    after = run_decision(
        workload,
        record_id="rec-test-after-stronger-evidence",
        scenario=_normal_scenario(),
        effective_min_throughput=workload.slo.min_throughput_tokens_per_s,
        min_confidence_pct=85.0,
    )

    assert after.recommended_target_id == "amd-mi300x"

    # The evidence actually used is traceable back to the new benchmark run.
    winning_candidate = next(c for c in after.candidates if c.target_id == "amd-mi300x")
    assert winning_candidate.raw_prediction is not None
    assert winning_candidate.raw_prediction.throughput_tokens_per_s.evidence_reference == "bench-test-integration"
    assert winning_candidate.raw_prediction.throughput_tokens_per_s.provenance == "MEASURED"


# --------------------------------------------------------------------------
# The one remaining, deliberate gap (docs/decision-engine.md /
# docs/benchmarking.md): a real `forgeway bench` run tagged with a genuinely
# matching --workload-id (docs/importing-results.md) is a real, comparable
# candidate — but only when a real P99 percentile was actually captured.
# Without one, it's still gathered as a candidate but honestly excluded from
# selection, never patched with a misrepresented average-as-P99 figure.
# --------------------------------------------------------------------------


def test_a_real_forgeway_bench_run_without_percentiles_is_not_selected(tmp_path, monkeypatch):
    """Uses the real app.benchmark.evidence.build_performance_evidence() —
    the exact function `forgeway bench` calls — not a hand-built stand-in.
    Without a captured P99 percentile, its output becomes a *candidate*
    (gather_evidence_candidates finds it, since workload_id/
    compute_target_id match), but select_evidence must not choose it: the
    canonical LATENCY_METRIC_KEY is never aliased from end_to_end_latency_ms
    (an average, not a P99) — see app/benchmark/evidence.py's module
    docstring. Throughput *is* aliased unconditionally (a plain arithmetic
    derivation, not a statistic that could be misrepresented), so it alone
    isn't enough to clear the comparability gate.
    """
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path))
    target = next(t for t in load_compute_targets() if t.id == "amd-mi300x")

    real_bench_output = build_performance_evidence(
        compute_target=target,
        model="meta-llama/Llama-3.1-70B-Instruct",  # a model that genuinely matches this workload
        workload_id="wl-llama70b-rt",  # so tagging it with the real workload id is honest, not fabricated
        input_tokens=512,
        output_tokens=128,
        concurrency=1,
        parsed=ParsedLatencyResult(avg_latency_s=0.1, percentiles_s={}),  # no percentiles captured
        gpu_samples=[],
        run_id="bench-real-shape-no-percentiles",
    )
    assert LATENCY_METRIC_KEY not in real_bench_output.metrics  # confirms this is really today's shape
    assert THROUGHPUT_METRIC_KEY in real_bench_output.metrics  # throughput alone is unconditional
    save_run(real_bench_output)

    candidates = gather_evidence_candidates("wl-llama70b-rt", "amd-mi300x", benchmark_runs=list_runs())
    assert any(c.benchmark_run_id == "bench-real-shape-no-percentiles" for c in candidates)  # it IS a candidate

    chosen = select_evidence(candidates, required_metrics=(LATENCY_METRIC_KEY, THROUGHPUT_METRIC_KEY))
    assert chosen is None or chosen.benchmark_run_id != "bench-real-shape-no-percentiles"


def test_a_real_forgeway_bench_run_with_percentiles_is_now_selected(tmp_path, monkeypatch):
    """The gap the test above documents is specifically about missing
    percentile data — when `vllm bench latency`'s output (percentiles are
    computed and reported unconditionally by real, current vLLM versions —
    live-verified 2026-09-04, see app.benchmark.vllm_runner's module
    constants) actually reports a P99, a real forgeway bench run is
    selectable by the engine like any other MEASURED evidence."""
    monkeypatch.setenv("FORGEWAY_BENCH_DIR", str(tmp_path))
    target = next(t for t in load_compute_targets() if t.id == "amd-mi300x")

    real_bench_output = build_performance_evidence(
        compute_target=target,
        model="meta-llama/Llama-3.1-70B-Instruct",
        workload_id="wl-llama70b-rt",
        input_tokens=512,
        output_tokens=128,
        concurrency=1,
        parsed=ParsedLatencyResult(avg_latency_s=0.1, percentiles_s={"50": 0.09, "99": 0.12}),
        gpu_samples=[],
        run_id="bench-real-shape-with-percentiles",
    )
    assert LATENCY_METRIC_KEY in real_bench_output.metrics
    save_run(real_bench_output)

    candidates = gather_evidence_candidates("wl-llama70b-rt", "amd-mi300x", benchmark_runs=list_runs())
    chosen = select_evidence(candidates, required_metrics=(LATENCY_METRIC_KEY, THROUGHPUT_METRIC_KEY))

    assert chosen is not None
    assert chosen.benchmark_run_id == "bench-real-shape-with-percentiles"
    assert chosen.provenance == "MEASURED"
