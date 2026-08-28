import { CheckCircle2, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { DecisionRecord } from "@/lib/types";
import { cn } from "@/lib/utils";

function confidenceTone(pct: number): "success" | "warning" | "destructive" {
  if (pct >= 85) return "success";
  if (pct >= 65) return "warning";
  return "destructive";
}

export function StateSnapshotCard({
  label,
  record,
  className,
}: {
  label: "Before" | "After";
  record: DecisionRecord;
  className?: string;
}) {
  const cost = record.recommended
    ? record.recommended.cost_per_hr
    : record.split_allocation.reduce((sum, a) => sum + a.cost_per_hr, 0);
  const hasOutcome = Boolean(record.recommended_target_id) || record.split_allocation.length > 0;

  return (
    <Card className={cn("border-dashed", className)}>
      <CardHeader className="flex-row items-center justify-between pb-2">
        <CardTitle className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
        </CardTitle>
        <Badge variant={record.slo_met ? "success" : "destructive"}>
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
      </CardHeader>
      <CardContent className="space-y-2">
        {record.recommended_target_id ? (
          <p className="font-mono text-base font-semibold text-foreground">
            {record.recommended_target_id}
          </p>
        ) : record.split_allocation.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {record.split_allocation.map((a) => (
              <Badge key={a.target_id} variant="outline" className="font-mono">
                {a.target_label} {a.throughput_share_pct.toFixed(0)}%
              </Badge>
            ))}
          </div>
        ) : (
          <p className="text-sm font-medium text-destructive">No recommendation</p>
        )}

        {hasOutcome ? (
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
            <dt className="text-muted-foreground">Cost</dt>
            <dd className="text-right font-mono">${cost.toFixed(2)}/hr</dd>
            <dt className="text-muted-foreground">Confidence</dt>
            <dd className="text-right font-mono">
              <span
                className={cn(
                  confidenceTone(record.confidence_pct) === "success" && "text-success",
                  confidenceTone(record.confidence_pct) === "warning" && "text-warning",
                  confidenceTone(record.confidence_pct) === "destructive" && "text-destructive"
                )}
              >
                {record.confidence_pct}%
              </span>
            </dd>
            <dt className="text-muted-foreground">Throughput</dt>
            <dd className="text-right font-mono">
              {record.achieved_throughput_tokens_per_s.toLocaleString()} /{" "}
              {record.effective_min_throughput_tokens_per_s.toLocaleString()} tok/s
            </dd>
          </dl>
        ) : (
          <p className="text-xs text-muted-foreground">{record.reasoning}</p>
        )}
      </CardContent>
    </Card>
  );
}
