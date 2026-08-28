"use client";

import { useState } from "react";
import { ChevronDown, Sigma } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CandidateEvaluation, DecisionRecord } from "@/lib/types";
import { cn } from "@/lib/utils";

function FactorBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-20 shrink-0 text-[11px] text-muted-foreground">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary" style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
      <span className="w-9 shrink-0 text-right font-mono text-[11px] text-muted-foreground">
        {value.toFixed(2)}
      </span>
    </div>
  );
}

function WeakestLink({ candidate }: { candidate: CandidateEvaluation }) {
  const pred = candidate.raw_prediction;
  if (!pred) return null;
  const factors = [
    { label: "latency", metric: pred.latency_p99_ms },
    { label: "throughput", metric: pred.throughput_tokens_per_s },
    { label: "cost", metric: pred.cost_per_hr },
  ];
  const weakest = factors.reduce((a, b) => (b.metric.confidence < a.metric.confidence ? b : a));
  return (
    <p className="text-xs leading-relaxed text-muted-foreground">
      Confidence is the weakest-link minimum across latency, throughput and cost evidence — here
      that&apos;s the <span className="font-medium text-foreground">{weakest.label}</span> figure at{" "}
      <span className="font-mono text-foreground">{weakest.metric.confidence.toFixed(0)}%</span> (
      {weakest.metric.provenance.toLowerCase()}), which is why the overall confidence is{" "}
      <span className="font-mono text-foreground">{(candidate.confidence_pct ?? 0).toFixed(0)}%</span>{" "}
      and not higher.
    </p>
  );
}

function CandidateFactors({ candidate, weights }: { candidate: CandidateEvaluation; weights: DecisionRecord["objective_weights"] }) {
  const totalWeight = weights.cost + weights.performance + weights.headroom || 1;
  return (
    <div className="space-y-3 rounded-md border border-border/60 p-3">
      <p className="font-mono text-xs font-medium text-foreground">{candidate.target_label}</p>

      <div>
        <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Objective weights applied
        </p>
        <FactorBar label="cost" value={weights.cost / totalWeight} />
        <FactorBar label="performance" value={weights.performance / totalWeight} />
        <FactorBar label="headroom" value={weights.headroom / totalWeight} />
      </div>

      {candidate.normalized_scores ? (
        <div>
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Normalized scores (1.0 = best in class)
          </p>
          <FactorBar label="cost" value={candidate.normalized_scores.cost} />
          <FactorBar label="performance" value={candidate.normalized_scores.performance} />
          <FactorBar label="headroom" value={candidate.normalized_scores.headroom} />
        </div>
      ) : null}

      {candidate.weighted_score !== null ? (
        <p className="flex items-center gap-1.5 text-xs text-foreground">
          <Sigma className="h-3 w-3 text-primary" />
          Weighted score:{" "}
          <span className="font-mono font-medium">{candidate.weighted_score.toFixed(3)}</span>
        </p>
      ) : null}

      <WeakestLink candidate={candidate} />
    </div>
  );
}

export function WhyThisTarget({ record }: { record: DecisionRecord }) {
  const [open, setOpen] = useState(false);

  const recommendedIds = record.recommended_target_id
    ? [record.recommended_target_id]
    : record.split_allocation.map((a) => a.target_id);
  const recommendedCandidates = record.candidates.filter((c) => recommendedIds.includes(c.target_id));
  const runnerUp = record.candidates
    .filter((c) => c.status === "feasible" && c.weighted_score !== null)
    .sort((a, b) => (b.weighted_score ?? 0) - (a.weighted_score ?? 0))[0];

  return (
    <Card>
      <CardHeader className="pb-2">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex w-full items-center justify-between gap-2 text-left"
        >
          <CardTitle className="text-sm">Why this target?</CardTitle>
          <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", open && "rotate-180")} />
        </button>
      </CardHeader>
      {open ? (
        <CardContent className="space-y-3">
          <p className="text-xs leading-relaxed text-muted-foreground">
            A deterministic breakdown of the decision factors — no model is asked to place this
            workload; the score below is the entire decision.
          </p>
          {recommendedCandidates.length > 0 ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {recommendedCandidates.map((c) => (
                <CandidateFactors key={c.target_id} candidate={c} weights={record.objective_weights} />
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">{record.reasoning}</p>
          )}
          {runnerUp && recommendedCandidates.length === 1 && runnerUp.target_id !== recommendedCandidates[0]?.target_id ? (
            <p className="text-xs text-muted-foreground">
              Runner-up: <span className="font-mono text-foreground">{runnerUp.target_label}</span> at
              weighted score{" "}
              <span className="font-mono text-foreground">{(runnerUp.weighted_score ?? 0).toFixed(3)}</span> —
              a{" "}
              <span className="font-mono text-foreground">
                {recommendedCandidates[0]?.weighted_score
                  ? (
                      ((recommendedCandidates[0].weighted_score - (runnerUp.weighted_score ?? 0)) /
                        (runnerUp.weighted_score || 1)) *
                      100
                    ).toFixed(0)
                  : "—"}
                %
              </span>{" "}
              margin under the current objective weights.
            </p>
          ) : null}
        </CardContent>
      ) : null}
    </Card>
  );
}
