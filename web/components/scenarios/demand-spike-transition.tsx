import { RecommendationHero } from "@/components/recommendations/recommendation-hero";
import type { ScenarioComparison } from "@/lib/types";
import { cn } from "@/lib/utils";

function P99Gauge({
  valueMs,
  thresholdMs,
  maxMs,
  breached,
}: {
  valueMs: number;
  thresholdMs: number;
  maxMs: number;
  breached: boolean;
}) {
  const valuePct = Math.min(100, (valueMs / maxMs) * 100);
  const thresholdPct = Math.min(100, (thresholdMs / maxMs) * 100);
  return (
    <div className="relative mt-6 h-2.5 w-full rounded-full bg-muted">
      <div
        className={cn(
          "h-full rounded-full transition-[width] duration-700 ease-out",
          breached ? "bg-destructive" : "bg-success"
        )}
        style={{ width: `${valuePct}%` }}
      />
      <div
        className="absolute top-0 h-full w-px bg-foreground/50"
        style={{ left: `${thresholdPct}%` }}
      />
      <span
        className="absolute -top-5 -translate-x-1/2 whitespace-nowrap text-[10px] text-muted-foreground"
        style={{ left: `${thresholdPct}%` }}
      >
        {thresholdMs.toFixed(0)}ms SLO
      </span>
    </div>
  );
}

export function DemandSpikeTransition({ comparison }: { comparison: ScenarioComparison }) {
  const before = comparison.before;
  const after = comparison.after;
  const unmitigated = after.unmitigated_projection;
  if (!unmitigated || !before.recommended) return null;

  const beforeP99 = before.recommended.p99_latency_ms;
  const maxMs = Math.max(unmitigated.predicted_p99_latency_ms, before.slo.p99_latency_ms) * 1.15;
  const multiplier = after.scenario.demand_multiplier ?? 1;

  return (
    <div className="space-y-4">
      <div className="animate-hero-in rounded-lg border border-success/30 bg-success/5 p-5">
        <p className="text-[11px] font-medium uppercase tracking-widest text-success">Before</p>
        <p className="mt-1.5 text-base text-foreground">
          <span className="font-mono font-semibold">{before.recommended_target_id}</span> satisfies the SLO.
        </p>
        <P99Gauge valueMs={beforeP99} thresholdMs={before.slo.p99_latency_ms} maxMs={maxMs} breached={false} />
        <p className="mt-2 font-mono text-xs text-muted-foreground">
          {beforeP99.toFixed(0)}ms P99 — comfortably under the {before.slo.p99_latency_ms.toFixed(0)}ms SLO
        </p>
      </div>

      <div
        className="animate-hero-in rounded-lg border border-destructive/40 bg-destructive/5 p-5"
        style={{ animationDelay: "150ms" }}
      >
        <p className="text-[11px] font-medium uppercase tracking-widest text-destructive">Event</p>
        <p className="mt-1.5 text-base text-foreground">
          Demand increases <span className="font-mono font-semibold">{multiplier}x</span> — projected P99
          exceeds the SLO.
        </p>
        <P99Gauge
          valueMs={unmitigated.predicted_p99_latency_ms}
          thresholdMs={after.slo.p99_latency_ms}
          maxMs={maxMs}
          breached
        />
        <p className="mt-2 font-mono text-xs text-destructive">
          ~{unmitigated.predicted_p99_latency_ms.toFixed(0)}ms projected P99 — {unmitigated.utilization_ratio.toFixed(1)}x
          over sized capacity, holding the prior placement fixed
        </p>
      </div>

      <div className="animate-hero-in" style={{ animationDelay: "300ms" }}>
        <p className="mb-2 text-[11px] font-medium uppercase tracking-widest text-primary">
          After — Forgeway recomputes
        </p>
        <RecommendationHero record={after} />
      </div>
    </div>
  );
}
