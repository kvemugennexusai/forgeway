"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, ChevronDown, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ProvenanceBadge } from "@/components/provenance-badge";
import { VendorBadge } from "@/components/vendor-badge";
import { importedTargetIds } from "@/lib/imported-storage";
import type { CandidateEvaluation, CandidateStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<CandidateStatus, string> = {
  recommended: "Recommended",
  feasible: "Feasible",
  rejected: "Rejected",
};

const STATUS_VARIANT: Record<CandidateStatus, "success" | "outline" | "destructive"> = {
  recommended: "success",
  feasible: "outline",
  rejected: "destructive",
};

function StatusBadge({ status }: { status: CandidateStatus }) {
  return (
    <Badge variant={STATUS_VARIANT[status]} className="text-[10px] uppercase tracking-wide">
      {STATUS_LABEL[status]}
    </Badge>
  );
}

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

function CandidateRow({ candidate, isImported }: { candidate: CandidateEvaluation; isImported: boolean }) {
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
              <div className="mt-0.5 flex items-center gap-1.5">
                <VendorBadge vendor={candidate.vendor} />
                {isImported ? (
                  <Badge variant="outline" className="uppercase">
                    Your imported compute
                  </Badge>
                ) : (
                  <Badge variant="outline" className="uppercase text-muted-foreground">
                    Reference compute
                  </Badge>
                )}
                {candidate.predicted ? (
                  <ProvenanceBadge provenance={candidate.predicted.provenance} />
                ) : null}
              </div>
            </div>
          </div>
        </TableCell>
        <TableCell className="py-1.5">
          <StatusBadge status={candidate.status} />
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

const STATUS_ORDER: Record<CandidateStatus, number> = { recommended: 0, feasible: 1, rejected: 2 };

export function CandidateComparisonTable({ candidates }: { candidates: CandidateEvaluation[] }) {
  const [importedIds, setImportedIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    setImportedIds(importedTargetIds());
  }, []);

  const sorted = [...candidates].sort((a, b) => {
    if (a.status !== b.status) return STATUS_ORDER[a.status] - STATUS_ORDER[b.status];
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
            <TableHead>Status</TableHead>
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
            <CandidateRow key={c.target_id} candidate={c} isImported={importedIds.has(c.target_id)} />
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
