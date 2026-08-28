"""Executive estate summary: aggregate fleet stats plus the Forgeway Insight
cards. Insights are read from already-computed Recommendations in the store
— the dashboard never re-implements scoring, it just reads engine output."""
from __future__ import annotations

from app.data.loader import load_compute_targets, load_workloads
from app.models import EstateSummary, InsightCard, VendorBreakdown
from app.state import DecisionStore


def compute_estate_summary(store: DecisionStore) -> EstateSummary:
    targets = load_compute_targets()
    workloads = load_workloads()

    devices_total = sum(t.capacity_units_total for t in targets)
    devices_allocated = sum(t.capacity_units_allocated for t in targets)
    overall_utilization = round(100 * devices_allocated / devices_total, 1) if devices_total else 0.0

    vendor_map: dict[str, list[int]] = {}
    for t in targets:
        vendor_map.setdefault(t.vendor, [0, 0])
        vendor_map[t.vendor][0] += t.capacity_units_total
        vendor_map[t.vendor][1] += t.capacity_units_allocated
    vendor_breakdown = [
        VendorBreakdown(
            vendor=v,
            devices_total=total,
            devices_allocated=allocated,
            utilization_pct=round(100 * allocated / total, 1) if total else 0.0,
        )
        for v, (total, allocated) in sorted(vendor_map.items())
    ]

    estimated_spend = sum(w.current_placement.cost_per_hr for w in workloads)
    compliant = sum(
        1 for w in workloads if w.current_placement.measured_p99_latency_ms <= w.slo.p99_latency_ms
    )
    slo_compliance = round(100 * compliant / len(workloads), 1) if workloads else 0.0

    insights: list[InsightCard] = []
    for w in workloads:
        if not w.reanalyze:
            continue
        # The canonical baseline, never whatever a user most recently
        # computed via /analyze or a scenario — the dashboard's opportunity
        # must not depend on what else has been clicked around in the app.
        record = store.get_canonical(w.id)
        if record is None or record.recommended_target_id is None:
            continue
        if record.recommended_target_id == w.current_placement.target_id:
            continue
        current_cost = w.current_placement.cost_per_hr
        rec_cost = record.recommended.cost_per_hr if record.recommended else current_cost
        if current_cost <= 0:
            continue
        savings_pct = round(100 * (current_cost - rec_cost) / current_cost, 1)
        insights.append(
            InsightCard(
                workload_id=w.id,
                workload_name=w.name,
                title=f"{record.recommended_target_id} outperforms the current placement",
                body=record.reasoning,
                recommendation_id=record.id,
                current_target_id=w.current_placement.target_id,
                current_cost_per_hr=current_cost,
                recommended_target_id=record.recommended_target_id,
                recommended_cost_per_hr=rec_cost,
                savings_pct=savings_pct,
                slo_met=record.slo_met,
                confidence_pct=record.confidence_pct,
            )
        )

    return EstateSummary(
        devices_total=devices_total,
        devices_allocated=devices_allocated,
        overall_utilization_pct=overall_utilization,
        active_workloads=len(workloads),
        estimated_spend_per_hr=round(estimated_spend, 2),
        slo_compliance_pct=slo_compliance,
        vendor_breakdown=vendor_breakdown,
        insights=insights,
    )
