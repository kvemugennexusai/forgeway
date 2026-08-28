import Link from "next/link";
import { ArrowRight, CheckCircle2, Sparkles, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfidenceGauge } from "@/components/ui/confidence-gauge";
import type { InsightCard } from "@/lib/types";
import { formatPct } from "@/lib/utils";

function targetVendorLabel(targetId: string): string {
  if (targetId.startsWith("nvidia")) return "NVIDIA";
  if (targetId.startsWith("amd")) return "AMD";
  if (targetId.startsWith("intel")) return "Intel";
  if (targetId.startsWith("aws")) return "AWS";
  return "";
}

function PlacementBlock({
  label,
  targetId,
  costPerHr,
  tone,
}: {
  label: string;
  targetId: string;
  costPerHr: number;
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
        {label}
      </p>
      <p className="font-mono text-lg font-semibold text-foreground sm:text-xl">{targetId}</p>
      <p className="text-xs text-muted-foreground">{targetVendorLabel(targetId)}</p>
      <p className="font-mono text-sm text-foreground">${costPerHr.toFixed(2)}/hr</p>
    </div>
  );
}

export function PlacementOpportunity({ insights }: { insights: InsightCard[] }) {
  const primary = insights[0];

  return (
    <Card className="lg:col-span-3">
      <CardHeader className="flex-row items-center justify-between">
        <div>
          <CardTitle className="flex items-center gap-1.5">
            <Sparkles className="h-3.5 w-3.5 text-primary" />
            Forgeway Insight
          </CardTitle>
          <CardDescription>Current placement vs. Forgeway recommendation.</CardDescription>
        </div>
        {primary ? (
          <Badge variant="success" className="text-[11px]">
            {formatPct(primary.savings_pct)} lower cost
          </Badge>
        ) : null}
      </CardHeader>
      <CardContent>
        {!primary ? (
          <p className="text-sm text-muted-foreground">
            No optimization opportunities flagged against current policy and evidence.
          </p>
        ) : (
          <div className="space-y-4">
            <p className="text-sm font-medium text-foreground">{primary.workload_name}</p>

            <div className="flex flex-col items-stretch gap-3 rounded-lg border border-border/60 bg-background/40 p-4 sm:flex-row sm:items-center">
              <PlacementBlock
                label="Current"
                targetId={primary.current_target_id}
                costPerHr={primary.current_cost_per_hr}
                tone="current"
              />
              <ArrowRight className="mx-auto h-5 w-5 shrink-0 rotate-90 text-muted-foreground sm:mx-0 sm:rotate-0" />
              <PlacementBlock
                label="Recommended"
                targetId={primary.recommended_target_id}
                costPerHr={primary.recommended_cost_per_hr}
                tone="recommended"
              />
              <div className="flex shrink-0 flex-row items-center justify-between gap-4 border-t border-border/60 pt-3 sm:flex-col sm:items-end sm:border-l sm:border-t-0 sm:pl-4 sm:pt-0">
                <Badge variant={primary.slo_met ? "success" : "destructive"} className="text-[11px]">
                  {primary.slo_met ? (
                    <>
                      <CheckCircle2 className="h-3 w-3" /> SLO maintained
                    </>
                  ) : (
                    <>
                      <XCircle className="h-3 w-3" /> SLO at risk
                    </>
                  )}
                </Badge>
                <ConfidenceGauge value={primary.confidence_pct} size={56} strokeWidth={5} />
              </div>
            </div>

            <p className="text-xs leading-relaxed text-muted-foreground">{primary.body}</p>

            <Link
              href={`/recommendations/${primary.recommendation_id}`}
              className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
            >
              View full recommendation <ArrowRight className="h-3 w-3" />
            </Link>

            {insights.length > 1 ? (
              <div className="space-y-1.5 border-t border-border/60 pt-3">
                {insights.slice(1).map((i) => (
                  <Link
                    key={i.recommendation_id}
                    href={`/recommendations/${i.recommendation_id}`}
                    className="flex items-center justify-between rounded-md px-2 py-1.5 text-xs transition-colors hover:bg-accent"
                  >
                    <span className="text-foreground">{i.workload_name}</span>
                    <span className="text-success">{formatPct(i.savings_pct)} lower cost</span>
                  </Link>
                ))}
              </div>
            ) : null}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
