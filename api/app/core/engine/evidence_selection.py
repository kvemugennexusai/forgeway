"""Evidence selection: given multiple PerformanceEvidence candidates for
the same (workload, target) pair, picks the one app.core.engine.scoring
should score against.

The rule (docs/decision-engine.md): **comparability gates before
provenance preference.** A candidate that doesn't carry the metrics the
engine actually needs is not "more relevant" just because its provenance
outranks another's — MEASURED > PUBLISHED > MODELED
(app.core.schemas.PROVENANCE_RANK) only decides among candidates that are
already equally usable, i.e. that carry every metric key the caller asked
for. This is deliberately not a fuzzy similarity score across
`configuration` strings or anything else — "comparable" means "has the
numbers we need", nothing more speculative than that. See
docs/decision-engine.md for why a broader notion of comparability was
judged out of scope for this pass.

Among candidates that tie on provenance, higher confidence wins; among
ties on both, the most recently recorded evidence wins. Both are simple,
documented tie-breakers, not a statistical judgment.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from app.core.schemas import PROVENANCE_RANK, PerformanceEvidence

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def select_evidence(
    candidates: list[PerformanceEvidence],
    *,
    required_metrics: Iterable[str],
) -> Optional[PerformanceEvidence]:
    """Precondition: every candidate must already describe the same
    (workload_id, compute_target_id) pair — this function does not gather
    or match candidates to a target itself (see
    app.engine.evidence_gateway.gather_evidence_candidates). Raises
    ValueError rather than silently picking a "best" evidence that's
    actually about the wrong workload or target, if that precondition is
    violated.

    Returns None if no candidate carries every metric in `required_metrics`
    — the honest "no usable evidence" signal the caller (app.core.engine.
    scoring.score_candidate) treats as insufficient evidence, never
    invented or guessed.
    """
    if not candidates:
        return None

    pairs = {(c.workload_id, c.compute_target_id) for c in candidates}
    if len(pairs) > 1:
        raise ValueError(
            "select_evidence requires every candidate to describe the same "
            f"(workload_id, compute_target_id) pair; got {sorted(pairs)}"
        )

    required = set(required_metrics)
    usable = [c for c in candidates if required.issubset(c.metrics.keys())]
    if not usable:
        return None

    def sort_key(evidence: PerformanceEvidence) -> tuple:
        return (
            PROVENANCE_RANK[evidence.provenance],
            evidence.confidence,
            evidence.timestamp or _EPOCH,
        )

    return max(usable, key=sort_key)
