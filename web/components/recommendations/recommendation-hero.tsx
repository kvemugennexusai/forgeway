import { CheckCircle2, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { ConfidenceGauge } from "@/components/ui/confidence-gauge";
import { ProvenanceBadge } from "@/components/provenance-badge";
import { VendorBadge } from "@/components/vendor-badge";
import type { DecisionRecord } from "@/lib/types";
import { extractSavingsPct } from "@/lib/parse-reasoning";
import { vendorColor, vendorWash } from "@/lib/vendor-colors";
import { cn } from "@/lib/utils";

function Stat({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "success";
}) {
  return (
    <div>
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p
        className={cn(
          "font-mono text-xl font-semibold tracking-tight sm:text-2xl",
          tone === "success" ? "text-success" : "text-foreground"
        )}
      >
        {value}
      </p>
    </div>
  );
}

export function RecommendationHero({ record }: { record: DecisionRecord }) {
  const solo = record.recommended_target_id && record.recommended;
  const split = record.split_allocation.length > 0;
  const hasOutcome = Boolean(solo || split);

  const soloCandidate = solo
    ? record.candidates.find((c) => c.target_id === record.recommended_target_id)
    : undefined;
  const primaryVendor = soloCandidate?.vendor ?? null;

  const cost = solo
    ? record.recommended!.cost_per_hr
    : record.split_allocation.reduce((sum, a) => sum + a.cost_per_hr, 0);

  const savingsPct = solo ? extractSavingsPct(record.reasoning) : null;

  return (
    <div
      key={record.id}
      className="animate-hero-in relative overflow-hidden rounded-xl border border-border/60"
      style={{ background: hasOutcome ? vendorWash(split ? null : primaryVendor) : undefined }}
    >
      <div className="relative p-6 sm:p-8">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
          <div className="min-w-0">
            <p className="text-[11px] font-medium uppercase tracking-widest text-muted-foreground">
              Recommendation
            </p>

            {solo ? (
              <div className="mt-1.5 flex flex-wrap items-center gap-2.5">
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ background: vendorColor(primaryVendor ?? "") }}
                />
                <h2 className="break-all font-mono text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
                  {record.recommended_target_id}
                </h2>
                <ProvenanceBadge provenance={record.recommended!.provenance} />
              </div>
            ) : split ? (
              <div className="mt-1.5">
                <h2 className="text-xl font-bold tracking-tight text-foreground sm:text-2xl">
                  Split placement
                </h2>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {record.split_allocation.map((a) => (
                    <Badge key={a.target_id} variant="outline" className="font-mono">
                      {a.target_label} {a.throughput_share_pct.toFixed(0)}%
                    </Badge>
                  ))}
                </div>
              </div>
            ) : (
              <h2 className="mt-1.5 text-xl font-bold tracking-tight text-destructive sm:text-2xl">
                No recommendation
              </h2>
            )}

            {soloCandidate ? (
              <div className="mt-1.5">
                <VendorBadge vendor={soloCandidate.vendor} />
              </div>
            ) : null}
          </div>

          <div className="flex shrink-0 items-center gap-3">
            <Badge variant={record.slo_met ? "success" : "destructive"} className="text-[11px]">
              {record.slo_met ? (
                <>
                  <CheckCircle2 className="h-3 w-3" /> SLO met
                </>
              ) : (
                <>
                  <XCircle className="h-3 w-3" /> SLO at risk
                </>
              )}
            </Badge>
            {hasOutcome ? <ConfidenceGauge value={record.confidence_pct} /> : null}
          </div>
        </div>

        {hasOutcome ? (
          <div className="mt-7 grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4">
            <Stat label={split ? "Combined cost" : "Cost"} value={`$${cost.toFixed(2)}/hr`} />
            {savingsPct !== null && savingsPct > 0 ? (
              <Stat label="Savings vs. current" value={`${savingsPct.toFixed(1)}%`} tone="success" />
            ) : (
              <Stat
                label="Architecture"
                value={split ? `${record.split_allocation.length} targets` : soloCandidate?.vendor.toUpperCase() ?? "—"}
              />
            )}
            <Stat
              label="Throughput"
              value={`${record.achieved_throughput_tokens_per_s.toLocaleString()} / ${record.effective_min_throughput_tokens_per_s.toLocaleString()} tok/s`}
            />
            {solo ? (
              <Stat label="P99 latency" value={`${record.recommended!.p99_latency_ms.toFixed(0)} ms`} />
            ) : (
              <Stat
                label="Shortfall"
                value={record.shortfall_tokens_per_s > 0 ? `${record.shortfall_tokens_per_s.toLocaleString()} tok/s` : "None"}
                tone={record.shortfall_tokens_per_s > 0 ? "default" : "success"}
              />
            )}
          </div>
        ) : null}

        <p className="mt-6 max-w-3xl text-sm leading-relaxed text-foreground/90">{record.reasoning}</p>

        <p className="mt-3 text-xs text-muted-foreground">
          Scenario: <span className="font-medium text-foreground/80">{record.scenario.label}</span>
          {record.derived_from_id ? (
            <>
              {" "}
              · derived from <span className="font-mono">{record.derived_from_id}</span>
            </>
          ) : null}
        </p>
      </div>
    </div>
  );
}
