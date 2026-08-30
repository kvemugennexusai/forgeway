"""Tests for app.core.engine.evidence_selection.select_evidence — pure,
no fixtures or filesystem involved: plain PerformanceEvidence objects in,
a choice (or None) out.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.engine.evidence_selection import select_evidence
from app.core.schemas import LATENCY_METRIC_KEY, THROUGHPUT_METRIC_KEY, Metric
from app.core.schemas.v0_1 import PerformanceEvidence

REQUIRED = (LATENCY_METRIC_KEY, THROUGHPUT_METRIC_KEY)


def _metric(value: float, provenance: str, confidence: float = 90.0) -> Metric:
    return Metric(value=value, confidence=confidence, provenance=provenance, source="test")


def _evidence(
    provenance: str,
    *,
    confidence: float = 90.0,
    with_throughput: bool = True,
    with_latency: bool = True,
    timestamp: datetime | None = None,
    workload_id: str = "wl-test",
    compute_target_id: str = "t-a",
) -> PerformanceEvidence:
    metrics = {}
    if with_latency:
        metrics[LATENCY_METRIC_KEY] = _metric(300.0, provenance, confidence)
    if with_throughput:
        metrics[THROUGHPUT_METRIC_KEY] = _metric(1000.0, provenance, confidence)
    return PerformanceEvidence(
        compute_target_id=compute_target_id,
        workload_id=workload_id,
        metrics=metrics,
        provenance=provenance,
        confidence=confidence,
        source="test",
        timestamp=timestamp,
    )


# --------------------------------------------------------------------------
# Provenance preference among comparable (equally usable) candidates
# --------------------------------------------------------------------------


def test_prefers_measured_over_published_over_modeled_among_comparable_candidates():
    measured = _evidence("MEASURED")
    published = _evidence("PUBLISHED")
    modeled = _evidence("MODELED")

    chosen = select_evidence([modeled, published, measured], required_metrics=REQUIRED)

    assert chosen is measured
    assert chosen.provenance == "MEASURED"


def test_published_beats_modeled_when_no_measured_available():
    published = _evidence("PUBLISHED")
    modeled = _evidence("MODELED")

    chosen = select_evidence([modeled, published], required_metrics=REQUIRED)

    assert chosen is published


def test_modeled_evidence_is_never_mislabeled_as_measured():
    """The only candidate is MODELED — select_evidence must return it as
    MODELED, never upgrade its provenance just because it was chosen."""
    modeled = _evidence("MODELED", confidence=65.0)

    chosen = select_evidence([modeled], required_metrics=REQUIRED)

    assert chosen is modeled
    assert chosen.provenance == "MODELED"
    assert chosen.confidence == 65.0


# --------------------------------------------------------------------------
# Comparability gates before provenance preference
# --------------------------------------------------------------------------


def test_missing_required_metric_makes_a_candidate_unusable():
    incomplete_measured = _evidence("MEASURED", with_throughput=False)

    chosen = select_evidence([incomplete_measured], required_metrics=REQUIRED)

    assert chosen is None


def test_prefers_complete_modeled_over_incomplete_measured():
    """The core "don't blindly overwrite more relevant evidence with less
    comparable evidence" rule: a MEASURED record that's missing a metric
    the engine needs is not usable, so a complete MODELED record — lower
    provenance, but the one that can actually answer the question — wins."""
    incomplete_measured = _evidence("MEASURED", with_throughput=False)
    complete_modeled = _evidence("MODELED")

    chosen = select_evidence([incomplete_measured, complete_modeled], required_metrics=REQUIRED)

    assert chosen is complete_modeled
    assert chosen.provenance == "MODELED"


def test_returns_none_when_no_candidate_has_required_metrics():
    only_latency = _evidence("MEASURED", with_throughput=False)
    only_throughput = _evidence("PUBLISHED", with_latency=False)

    chosen = select_evidence([only_latency, only_throughput], required_metrics=REQUIRED)

    assert chosen is None


def test_empty_candidate_list_returns_none():
    assert select_evidence([], required_metrics=REQUIRED) is None


# --------------------------------------------------------------------------
# Precondition guard
# --------------------------------------------------------------------------


def test_raises_when_candidates_describe_different_workload_target_pairs():
    a = _evidence("MEASURED", compute_target_id="t-a")
    b = _evidence("MEASURED", compute_target_id="t-b")

    with pytest.raises(ValueError, match="same"):
        select_evidence([a, b], required_metrics=REQUIRED)


# --------------------------------------------------------------------------
# Tie-breakers
# --------------------------------------------------------------------------


def test_confidence_tiebreak_within_same_provenance_tier():
    weaker = _evidence("MEASURED", confidence=80.0)
    stronger = _evidence("MEASURED", confidence=99.0)

    chosen = select_evidence([weaker, stronger], required_metrics=REQUIRED)

    assert chosen is stronger


def test_recency_tiebreak_when_provenance_and_confidence_tie():
    now = datetime.now(timezone.utc)
    older = _evidence("MEASURED", confidence=95.0, timestamp=now - timedelta(days=30))
    newer = _evidence("MEASURED", confidence=95.0, timestamp=now)

    chosen = select_evidence([older, newer], required_metrics=REQUIRED)

    assert chosen is newer
