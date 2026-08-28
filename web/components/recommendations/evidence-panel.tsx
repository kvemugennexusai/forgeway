import { ProvenanceBadge } from "@/components/provenance-badge";
import type { EvidenceItem } from "@/lib/types";

export function EvidencePanel({ evidence }: { evidence: EvidenceItem[] }) {
  if (evidence.length === 0) return null;

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-medium text-foreground">Evidence</h3>
        <p className="text-xs text-muted-foreground">modeled figures are never shown as measured</p>
      </div>
      <div className="divide-y divide-border/60 rounded-md border border-border/60">
        {evidence.map((item, i) => (
          <div key={`${item.label}-${i}`} className="flex items-center gap-3 px-3 py-2">
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs text-foreground">{item.label}</p>
              <p className="truncate text-[11px] text-muted-foreground">{item.source}</p>
            </div>
            <span className="shrink-0 font-mono text-xs font-medium text-foreground">
              {item.display_value}
            </span>
            {item.metric.range_low !== null && item.metric.range_high !== null ? (
              <span className="hidden shrink-0 font-mono text-[11px] text-muted-foreground sm:inline">
                ({item.metric.range_low.toLocaleString()}–{item.metric.range_high.toLocaleString()})
              </span>
            ) : null}
            <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
              {item.metric.confidence.toFixed(0)}%
            </span>
            <ProvenanceBadge provenance={item.metric.provenance} className="shrink-0" />
          </div>
        ))}
      </div>
    </div>
  );
}
