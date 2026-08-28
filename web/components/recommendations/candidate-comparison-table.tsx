"use client";

import { useState } from "react";
import { CheckCircle2, ChevronDown, XCircle } from "lucide-react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { VendorBadge } from "@/components/vendor-badge";
import type { CandidateEvaluation } from "@/lib/types";
import { cn } from "@/lib/utils";

function ScoreBar({ value }: { value: number | null }) {
  if (value === null) return <span className="text-muted-foreground">—</span>;
  return (
    <div className="flex items-center gap-1.5">
      <div className="h-1.5 w-12 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary" style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
      <span className="font-mono text-[11px] tabular-nums text-muted-foreground">{value.toFixed(2)}</span>
    </div>
  );
}

function CandidateRow({ candidate }: { candidate: CandidateEvaluation }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <TableRow className="cursor-pointer" onClick={() => setOpen((v) => !v)}>
        <TableCell className="py-1.5">
          <div className="flex items-center gap-2">
            <ChevronDown
              className={cn("h-3 w-3 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")}
            />
            <div className="min-w-0">
              <div className="truncate font-mono text-xs font-medium text-foreground">
                {candidate.target_label}
              </div>
              <VendorBadge vendor={candidate.vendor} className="mt-0.5" />
            </div>
          </div>
        </TableCell>
        <TableCell className="py-1.5">
          {candidate.feasible ? (
            <CheckCircle2 className="h-3.5 w-3.5 text-success" />
          ) : (
            <XCircle className="h-3.5 w-3.5 text-destructive" />
          )}
        </TableCell>
        <TableCell className="py-1.5 font-mono text-xs tabular-nums">
          {candidate.predicted ? `${candidate.predicted.p99_latency_ms.toFixed(0)}ms` : "—"}
        </TableCell>
        <TableCell className="py-1.5 font-mono text-xs tabular-nums">
          {candidate.predicted ? `$${candidate.predicted.cost_per_hr.toFixed(2)}/hr` : "—"}
        </TableCell>
        <TableCell className="py-1.5 font-mono text-xs tabular-nums">
          {candidate.confidence_pct !== null ? `${candidate.confidence_pct.toFixed(0)}%` : "—"}
        </TableCell>
        <TableCell className="py-1.5">
          <ScoreBar value={candidate.weighted_score} />
        </TableCell>
        <TableCell className="py-1.5 font-mono text-xs tabular-nums text-muted-foreground">
          {candidate.rank ? `#${candidate.rank}` : "—"}
        </TableCell>
        <TableCell className="max-w-[260px] py-1.5 text-xs text-muted-foreground">
          <span className="line-clamp-1">{candidate.rejection_reason ?? candidate.why_not_chosen ?? "—"}</span>
        </TableCell>
      </TableRow>
      {open ? (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={8} className="bg-background/40 p-0">
            <ul className="grid grid-cols-1 gap-1 p-3 sm:grid-cols-2">
              {candidate.checks.map((check) => (
                <li key={check.name} className="flex items-start gap-1.5 rounded-md p-1.5 text-[11px]">
                  {check.passed ? (
                    <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-success" />
                  ) : (
                    <XCircle className="mt-0.5 h-3 w-3 shrink-0 text-destructive" />
                  )}
                  <div>
                    <span className="font-medium text-foreground">{check.name}</span>
                    <span className="text-muted-foreground"> — {check.detail}</span>
                  </div>
                </li>
              ))}
            </ul>
          </TableCell>
        </TableRow>
      ) : null}
    </>
  );
}

export function CandidateComparisonTable({ candidates }: { candidates: CandidateEvaluation[] }) {
  const sorted = [...candidates].sort((a, b) => {
    if (a.feasible !== b.feasible) return a.feasible ? -1 : 1;
    if (a.rank && b.rank) return a.rank - b.rank;
    if (a.score !== null && b.score !== null) return a.score - b.score;
    return 0;
  });

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-medium text-foreground">Candidate comparison</h3>
        <p className="text-xs text-muted-foreground">expand a row for the full compatibility checklist</p>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Target</TableHead>
            <TableHead>OK</TableHead>
            <TableHead>P99</TableHead>
            <TableHead>Cost</TableHead>
            <TableHead>Conf.</TableHead>
            <TableHead>Score</TableHead>
            <TableHead>Rank</TableHead>
            <TableHead>Why not chosen</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((c) => (
            <CandidateRow key={c.target_id} candidate={c} />
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
