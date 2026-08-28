import { ArrowRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { VendorBadge } from "@/components/vendor-badge";
import type { DecisionRecord } from "@/lib/types";
import { vendorColor } from "@/lib/vendor-colors";

function Block({
  eyebrow,
  targetId,
  vendor,
  costPerHr,
  p99Ms,
  tone,
}: {
  eyebrow: string;
  targetId: string;
  vendor?: string;
  costPerHr: number;
  p99Ms?: number;
  tone: "current" | "recommended";
}) {
  return (
    <div className="flex-1 space-y-1.5">
      <p
        className={
          "text-[11px] font-medium uppercase tracking-wide " +
          (tone === "recommended" ? "text-primary" : "text-muted-foreground")
        }
      >
        {eyebrow}
      </p>
      <div className="flex items-center gap-2">
        {vendor ? (
          <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: vendorColor(vendor) }} />
        ) : null}
        <p className="font-mono text-base font-semibold text-foreground sm:text-lg">{targetId}</p>
      </div>
      {vendor ? <VendorBadge vendor={vendor} /> : null}
      <div className="flex gap-4 font-mono text-xs text-muted-foreground">
        <span>${costPerHr.toFixed(2)}/hr</span>
        {p99Ms !== undefined ? <span>{p99Ms.toFixed(0)}ms P99</span> : null}
      </div>
    </div>
  );
}

export function CurrentVsRecommended({ record }: { record: DecisionRecord }) {
  const current = record.current_placement;
  const currentCandidate = record.candidates.find((c) => c.target_id === current.target_id);

  const solo = record.recommended_target_id && record.recommended;
  const split = record.split_allocation.length > 0;

  const savingsPct =
    solo && current.cost_per_hr > 0
      ? (100 * (current.cost_per_hr - record.recommended!.cost_per_hr)) / current.cost_per_hr
      : split && current.cost_per_hr > 0
      ? (100 *
          (current.cost_per_hr -
            record.split_allocation.reduce((sum, a) => sum + a.cost_per_hr, 0))) /
        current.cost_per_hr
      : null;

  return (
    <div className="rounded-lg border border-border/60 bg-card/40 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium text-foreground">Current vs. recommended</h3>
        {savingsPct !== null ? (
          <Badge variant={savingsPct > 0 ? "success" : "outline"} className="text-[11px]">
            {savingsPct > 0 ? `${savingsPct.toFixed(1)}% lower cost` : `${Math.abs(savingsPct).toFixed(1)}% higher cost`}
          </Badge>
        ) : null}
      </div>
      <div className="flex flex-col items-stretch gap-4 sm:flex-row sm:items-center">
        <Block
          eyebrow="Current placement"
          targetId={current.target_id}
          vendor={currentCandidate?.vendor}
          costPerHr={current.cost_per_hr}
          p99Ms={current.measured_p99_latency_ms}
          tone="current"
        />
        <ArrowRight className="mx-auto h-5 w-5 shrink-0 rotate-90 text-muted-foreground sm:mx-0 sm:rotate-0" />
        {solo ? (
          <Block
            eyebrow="Recommended"
            targetId={record.recommended_target_id!}
            vendor={record.candidates.find((c) => c.target_id === record.recommended_target_id)?.vendor}
            costPerHr={record.recommended!.cost_per_hr}
            p99Ms={record.recommended!.p99_latency_ms}
            tone="recommended"
          />
        ) : split ? (
          <div className="flex-1 space-y-1.5">
            <p className="text-[11px] font-medium uppercase tracking-wide text-primary">
              Recommended (split)
            </p>
            <div className="flex flex-wrap gap-1.5">
              {record.split_allocation.map((a) => (
                <Badge key={a.target_id} variant="outline" className="font-mono">
                  {a.target_label} {a.throughput_share_pct.toFixed(0)}%
                </Badge>
              ))}
            </div>
            <p className="font-mono text-xs text-muted-foreground">
              ${record.split_allocation.reduce((sum, a) => sum + a.cost_per_hr, 0).toFixed(2)}/hr combined
            </p>
          </div>
        ) : (
          <div className="flex-1">
            <p className="text-[11px] font-medium uppercase tracking-wide text-destructive">
              No recommendation
            </p>
            <p className="text-xs text-muted-foreground">
              No candidate clears the SLO and confidence requirement under current conditions.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
