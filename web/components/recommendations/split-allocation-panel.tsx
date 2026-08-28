import type { DecisionRecord } from "@/lib/types";
import { vendorColor } from "@/lib/vendor-colors";

export function SplitAllocationPanel({ record }: { record: DecisionRecord }) {
  if (record.split_allocation.length === 0) return null;

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-medium text-foreground">Split placement detail</h3>
        <p className="text-xs text-muted-foreground">
          filled to each target&apos;s free capacity, cheapest-capable first
        </p>
      </div>

      <div className="flex h-2 w-full overflow-hidden rounded-full bg-muted">
        {record.split_allocation.map((a) => {
          const candidate = record.candidates.find((c) => c.target_id === a.target_id);
          return (
            <div
              key={a.target_id}
              style={{
                width: `${a.throughput_share_pct}%`,
                background: candidate ? vendorColor(candidate.vendor) : undefined,
              }}
              title={`${a.target_label}: ${a.throughput_share_pct.toFixed(0)}%`}
            />
          );
        })}
        {record.shortfall_tokens_per_s > 0 ? (
          <div
            className="bg-destructive/40"
            style={{
              width: `${(100 * record.shortfall_tokens_per_s) / record.effective_min_throughput_tokens_per_s}%`,
            }}
            title="Unmet demand"
          />
        ) : null}
      </div>

      <div className="mt-3 divide-y divide-border/60 rounded-md border border-border/60">
        {record.split_allocation.map((a) => {
          const candidate = record.candidates.find((c) => c.target_id === a.target_id);
          return (
            <div key={a.target_id} className="flex items-center gap-3 px-3 py-2 text-xs">
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ background: candidate ? vendorColor(candidate.vendor) : undefined }}
              />
              <span className="min-w-0 flex-1 truncate font-mono font-medium text-foreground">
                {a.target_label}
              </span>
              <span className="shrink-0 font-mono text-muted-foreground">{a.replica_count}x</span>
              <span className="shrink-0 font-mono tabular-nums text-muted-foreground">
                {a.throughput_tokens_per_s.toLocaleString()} tok/s
              </span>
              <span className="shrink-0 font-mono tabular-nums text-muted-foreground">
                {a.p99_latency_ms.toFixed(0)}ms
              </span>
              <span className="w-16 shrink-0 text-right font-mono tabular-nums text-foreground">
                ${a.cost_per_hr.toFixed(2)}/hr
              </span>
              <span className="w-10 shrink-0 text-right font-mono tabular-nums text-primary">
                {a.throughput_share_pct.toFixed(0)}%
              </span>
            </div>
          );
        })}
      </div>

      {record.shortfall_tokens_per_s > 0 ? (
        <p className="mt-2 text-xs text-destructive">
          {record.shortfall_tokens_per_s.toLocaleString()} tok/s unmet demand
        </p>
      ) : null}
    </div>
  );
}
