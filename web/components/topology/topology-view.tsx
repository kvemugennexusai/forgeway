"use client";

import type { CandidateEvaluation, DecisionRecord } from "@/lib/types";
import { vendorColor, vendorFill } from "@/lib/vendor-colors";
import { cn } from "@/lib/utils";

const ROW_H = 40;
const ROW_GAP = 10;
const COL_WORKLOAD_X = 16;
const COL_WORKLOAD_W = 176;
const COL_TARGET_X = 300;
const COL_TARGET_W = 220;
const COL_OUTCOME_X = 660;
const COL_OUTCOME_W = 190;

function targetsTooltip(c: CandidateEvaluation): string {
  if (!c.feasible) return c.rejection_reason ?? "Infeasible";
  if (c.why_not_chosen) return c.why_not_chosen;
  if (c.rank) return `Rank #${c.rank} · weighted score ${c.weighted_score?.toFixed(2) ?? "—"}`;
  return "Feasible";
}

export function TopologyView({ record }: { record: DecisionRecord }) {
  const candidates = record.candidates;
  const recommendedIds = new Set(
    record.recommended_target_id
      ? [record.recommended_target_id]
      : record.split_allocation.map((a) => a.target_id)
  );
  const shareById = new Map(record.split_allocation.map((a) => [a.target_id, a.throughput_share_pct]));

  const targetsHeight = candidates.length * ROW_H + (candidates.length - 1) * ROW_GAP;
  const height = Math.max(300, targetsHeight + 56);
  const width = 900;

  const targetsStartY = height / 2 - targetsHeight / 2;
  const targetY = (i: number) => targetsStartY + i * (ROW_H + ROW_GAP);

  const outcomeNodes =
    recommendedIds.size > 0
      ? candidates.filter((c) => recommendedIds.has(c.target_id))
      : [];
  const outcomeCount = Math.max(outcomeNodes.length, 1);
  const outcomeHeight = outcomeCount * ROW_H + (outcomeCount - 1) * ROW_GAP;
  const outcomeStartY = height / 2 - outcomeHeight / 2;
  const outcomeY = (i: number) => outcomeStartY + i * (ROW_H + ROW_GAP);

  const workloadY = height / 2 - ROW_H / 2 - 6;
  const workloadCenterY = workloadY + (ROW_H + 12) / 2;

  return (
    <div className="overflow-x-auto scrollbar-thin">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        style={{ minWidth: 720 }}
        role="img"
        aria-label="Workload to compute target topology, recommended path highlighted"
      >
        {/* workload -> every evaluated target */}
        {candidates.map((c, i) => {
          const y1 = workloadCenterY;
          const x1 = COL_WORKLOAD_X + COL_WORKLOAD_W;
          const y2 = targetY(i) + ROW_H / 2;
          const x2 = COL_TARGET_X;
          const midX = (x1 + x2) / 2;
          return (
            <path
              key={`edge-in-${c.target_id}`}
              d={`M ${x1},${y1} C ${midX},${y1} ${midX},${y2} ${x2},${y2}`}
              fill="none"
              stroke="hsl(var(--border))"
              strokeWidth={1.5}
              strokeOpacity={c.feasible ? 0.55 : 0.25}
              strokeDasharray={c.feasible ? undefined : "3 4"}
            />
          );
        })}

        {/* recommended target(s) -> outcome */}
        {outcomeNodes.map((c, i) => {
          const x1 = COL_TARGET_X + COL_TARGET_W;
          const y1 = targetY(candidates.findIndex((x) => x.target_id === c.target_id)) + ROW_H / 2;
          const x2 = COL_OUTCOME_X;
          const y2 = outcomeY(i) + ROW_H / 2;
          const midX = (x1 + x2) / 2;
          const share = shareById.get(c.target_id);
          return (
            <g key={`edge-out-${c.target_id}`}>
              <path
                d={`M ${x1},${y1} C ${midX},${y1} ${midX},${y2} ${x2},${y2}`}
                fill="none"
                stroke={vendorColor(c.vendor)}
                strokeWidth={share ? 1.5 + (share / 100) * 3 : 3}
                className="animate-flow"
              />
              {share !== undefined ? (
                <text
                  x={(x1 + x2) / 2}
                  y={(y1 + y2) / 2 - 8}
                  textAnchor="middle"
                  className="fill-muted-foreground font-mono"
                  fontSize={11}
                >
                  {share.toFixed(0)}%
                </text>
              ) : null}
            </g>
          );
        })}

        {/* workload node */}
        <g>
          <rect
            x={COL_WORKLOAD_X}
            y={workloadY}
            width={COL_WORKLOAD_W}
            height={ROW_H + 12}
            rx={8}
            fill="hsl(var(--card))"
            stroke="hsl(var(--border))"
            strokeWidth={1.5}
          />
          <text
            x={COL_WORKLOAD_X + 12}
            y={workloadY + 18}
            className="fill-muted-foreground"
            fontSize={9.5}
            style={{ letterSpacing: "0.06em" }}
          >
            WORKLOAD
          </text>
          <foreignObject x={COL_WORKLOAD_X + 10} y={workloadY + 22} width={COL_WORKLOAD_W - 20} height={30}>
            <div className="truncate text-xs font-medium text-foreground">{record.workload_name}</div>
          </foreignObject>
        </g>

        {/* target nodes */}
        {candidates.map((c, i) => {
          const y = targetY(i);
          const isRecommended = recommendedIds.has(c.target_id);
          return (
            <g key={`node-${c.target_id}`} opacity={c.feasible ? 1 : 0.45}>
              <title>{`${c.target_label} — ${targetsTooltip(c)}`}</title>
              <rect
                x={COL_TARGET_X}
                y={y}
                width={COL_TARGET_W}
                height={ROW_H}
                rx={7}
                fill={isRecommended ? vendorFill(c.vendor, 0.14) : "hsl(var(--card))"}
                stroke={isRecommended ? vendorColor(c.vendor) : "hsl(var(--border))"}
                strokeWidth={isRecommended ? 2 : 1.25}
                strokeDasharray={c.feasible ? undefined : "3 4"}
              />
              <circle cx={COL_TARGET_X + 14} cy={y + ROW_H / 2} r={3.5} fill={vendorColor(c.vendor)} />
              <foreignObject x={COL_TARGET_X + 24} y={y + 6} width={COL_TARGET_W - 60} height={ROW_H - 12}>
                <div className="flex h-full flex-col justify-center overflow-hidden">
                  <span className="truncate font-mono text-[11px] font-medium leading-tight text-foreground">
                    {c.target_label}
                  </span>
                  <span className="truncate text-[10px] leading-tight text-muted-foreground">
                    {c.feasible ? (c.rank ? `rank #${c.rank}` : "feasible") : "infeasible"}
                  </span>
                </div>
              </foreignObject>
              {c.feasible ? (
                <circle cx={COL_TARGET_X + COL_TARGET_W - 14} cy={y + ROW_H / 2} r={3} fill="hsl(var(--success))" />
              ) : (
                <circle
                  cx={COL_TARGET_X + COL_TARGET_W - 14}
                  cy={y + ROW_H / 2}
                  r={3}
                  fill="hsl(var(--destructive))"
                />
              )}
            </g>
          );
        })}

        {/* outcome node(s) */}
        {outcomeNodes.length > 0 ? (
          outcomeNodes.map((c, i) => (
            <g key={`outcome-${c.target_id}`}>
              <rect
                x={COL_OUTCOME_X}
                y={outcomeY(i)}
                width={COL_OUTCOME_W}
                height={ROW_H}
                rx={7}
                fill={vendorFill(c.vendor, 0.18)}
                stroke={vendorColor(c.vendor)}
                strokeWidth={2}
              />
              <foreignObject x={COL_OUTCOME_X + 12} y={outcomeY(i) + 5} width={COL_OUTCOME_W - 24} height={ROW_H - 10}>
                <div className="flex h-full flex-col justify-center overflow-hidden">
                  <span className="truncate font-mono text-[11px] font-semibold leading-tight text-foreground">
                    {c.target_label}
                  </span>
                  <span className="truncate text-[10px] leading-tight text-muted-foreground">
                    {outcomeNodes.length > 1 ? "split target" : "recommended"}
                  </span>
                </div>
              </foreignObject>
            </g>
          ))
        ) : (
          <g>
            <rect
              x={COL_OUTCOME_X}
              y={height / 2 - ROW_H / 2}
              width={COL_OUTCOME_W}
              height={ROW_H}
              rx={7}
              fill="hsl(var(--destructive) / 0.1)"
              stroke="hsl(var(--destructive))"
              strokeWidth={1.5}
              strokeDasharray="3 4"
            />
            <text
              x={COL_OUTCOME_X + COL_OUTCOME_W / 2}
              y={height / 2 + 4}
              textAnchor="middle"
              className="fill-destructive font-medium"
              fontSize={11}
            >
              Withheld
            </text>
          </g>
        )}

        {/* column labels */}
        <text x={COL_TARGET_X} y={targetsStartY - 14} className="fill-muted-foreground" fontSize={9.5} style={{ letterSpacing: "0.06em" }}>
          EVALUATED TARGETS
        </text>
        <text x={COL_OUTCOME_X} y={Math.min(outcomeStartY, height / 2 - ROW_H / 2) - 14} className="fill-muted-foreground" fontSize={9.5} style={{ letterSpacing: "0.06em" }}>
          OUTCOME
        </text>
      </svg>

      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border/60 px-1 pt-2 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-success" /> feasible
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-destructive" /> infeasible
        </span>
        <span className="flex items-center gap-1.5">
          <span className={cn("h-0.5 w-4 rounded-full bg-primary")} /> recommended path
        </span>
        <span className="ml-auto text-muted-foreground/70">hover a target for its evaluation</span>
      </div>
    </div>
  );
}
