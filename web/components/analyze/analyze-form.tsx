"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, UploadCloud } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { api } from "@/lib/api";
import { getImportedEvidence, getImportedTargets } from "@/lib/imported-storage";
import type { WorkloadListItem } from "@/lib/types";
import { cn } from "@/lib/utils";

const CLASS_LABEL: Record<string, string> = {
  "realtime-inference": "Realtime inference",
  "batch-inference": "Batch inference",
  training: "Training",
};

const PIPELINE_STEPS = ["Feasibility", "Prediction", "Ranking", "Recommendation"];
const STEP_INTERVAL_MS = 260;

export function AnalyzeForm({ items }: { items: WorkloadListItem[] }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const preselect = searchParams.get("workload");

  const [selectedId, setSelectedId] = useState(preselect ?? items[0]?.workload.id);
  const [submitting, setSubmitting] = useState(false);
  const [activeStep, setActiveStep] = useState(-1);
  const [error, setError] = useState<string | null>(null);
  const [importedCount, setImportedCount] = useState({ targets: 0, evidence: 0 });

  useEffect(() => {
    setImportedCount({ targets: getImportedTargets().length, evidence: getImportedEvidence().length });
  }, []);

  const selected = useMemo(
    () => items.find((i) => i.workload.id === selectedId)?.workload,
    [items, selectedId]
  );

  async function runAnalysis() {
    if (!selected) return;
    setSubmitting(true);
    setError(null);
    setActiveStep(0);

    const stepTimer = setInterval(() => {
      setActiveStep((s) => (s < PIPELINE_STEPS.length - 1 ? s + 1 : s));
    }, STEP_INTERVAL_MS);

    try {
      const imported = { targets: getImportedTargets(), evidence: getImportedEvidence() };
      const [record] = await Promise.all([
        api.analyze(selected.id, imported),
        new Promise((resolve) => setTimeout(resolve, PIPELINE_STEPS.length * STEP_INTERVAL_MS)),
      ]);
      clearInterval(stepTimer);
      router.push(`/recommendations/${record.id}`);
    } catch (e) {
      clearInterval(stepTimer);
      setError(e instanceof Error ? e.message : "Analysis failed.");
      setSubmitting(false);
      setActiveStep(-1);
    }
  }

  return (
    <div className="grid grid-cols-1 gap-4 p-6 lg:grid-cols-5">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>Workload profile</CardTitle>
          <CardDescription>
            Select a workload to run through the decision engine. Custom workload definition is
            on the roadmap — this build analyzes profiles from the estate&apos;s workload
            library.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {items.map(({ workload }) => (
            <button
              key={workload.id}
              onClick={() => setSelectedId(workload.id)}
              className={cn(
                "w-full rounded-md border p-3 text-left transition-colors",
                selectedId === workload.id
                  ? "border-primary/50 bg-primary/5"
                  : "border-border hover:border-primary/30 hover:bg-accent"
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-foreground">{workload.name}</p>
                <Badge variant="outline">{CLASS_LABEL[workload.workload_class]}</Badge>
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {workload.model_family} · currently on {workload.current_placement.target_id}
              </p>
            </button>
          ))}
        </CardContent>
      </Card>

      <Card className="lg:col-span-3">
        <CardHeader>
          <CardTitle>{selected?.name ?? "Select a workload"}</CardTitle>
          <CardDescription>
            Service-level objective, enterprise policy, and current placement Forgeway will
            evaluate feasible targets against.
          </CardDescription>
        </CardHeader>
        {selected ? (
          <CardContent className="space-y-5">
            <div>
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Service-level objective
              </p>
              <dl className="grid grid-cols-3 gap-3">
                <div className="rounded-md border border-border bg-background/60 p-3">
                  <dt className="text-xs text-muted-foreground">P99 latency</dt>
                  <dd className="font-mono text-sm font-medium">{selected.slo.p99_latency_ms} ms</dd>
                </div>
                <div className="rounded-md border border-border bg-background/60 p-3">
                  <dt className="text-xs text-muted-foreground">Min throughput</dt>
                  <dd className="font-mono text-sm font-medium">
                    {selected.slo.min_throughput_tokens_per_s.toLocaleString()} tok/s
                  </dd>
                </div>
                <div className="rounded-md border border-border bg-background/60 p-3">
                  <dt className="text-xs text-muted-foreground">Availability</dt>
                  <dd className="font-mono text-sm font-medium">{selected.slo.availability_pct}%</dd>
                </div>
              </dl>
            </div>

            <div>
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Enterprise policy
              </p>
              <dl className="grid grid-cols-2 gap-3">
                <div className="rounded-md border border-border bg-background/60 p-3">
                  <dt className="text-xs text-muted-foreground">Allowed vendors</dt>
                  <dd className="mt-1 flex flex-wrap gap-1">
                    {selected.policy.allowed_vendors.map((v) => (
                      <Badge key={v} variant="outline" className="uppercase">
                        {v}
                      </Badge>
                    ))}
                  </dd>
                </div>
                <div className="rounded-md border border-border bg-background/60 p-3">
                  <dt className="text-xs text-muted-foreground">Budget ceiling</dt>
                  <dd className="font-mono text-sm font-medium">
                    ${selected.policy.budget_ceiling_per_hr.toFixed(2)}/hr
                  </dd>
                </div>
              </dl>
            </div>

            <div>
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Model
              </p>
              <dl className="grid grid-cols-3 gap-3 text-xs">
                <div>
                  <dt className="text-muted-foreground">Parameters</dt>
                  <dd className="font-mono">{selected.model_params_billion}B</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Precision</dt>
                  <dd className="font-mono">{selected.precision}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Memory footprint</dt>
                  <dd className="font-mono">
                    {selected.weights_footprint_gb + selected.kv_cache_overhead_gb} GB
                  </dd>
                </div>
              </dl>
            </div>

            <Separator />

            {importedCount.targets > 0 || importedCount.evidence > 0 ? (
              <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                <Badge variant="measured" className="uppercase">
                  Your measured compute
                </Badge>
                <span>
                  {importedCount.targets} imported target{importedCount.targets === 1 ? "" : "s"} and{" "}
                  {importedCount.evidence} evidence record{importedCount.evidence === 1 ? "" : "s"} from
                  this browser will be included in this analysis.
                </span>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                <span>No hardware imported yet — this analysis only evaluates</span>
                <Badge variant="outline" className="uppercase">
                  reference compute
                </Badge>
                <span>
                  . <Link href="/import" className="underline">
                    Import a benchmark result
                  </Link>{" "}
                  to add your own.
                </span>
              </div>
            )}

            {error ? <p className="text-sm text-destructive">{error}</p> : null}

            {submitting ? (
              <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
                {PIPELINE_STEPS.map((step, i) => (
                  <div key={step} className="flex items-center gap-2.5">
                    {i > 0 ? <span className="text-muted-foreground/25">→</span> : null}
                    <div
                      className={cn(
                        "flex items-center gap-1.5 text-xs",
                        i <= activeStep ? "animate-step-in text-foreground" : "text-muted-foreground/35"
                      )}
                    >
                      <span
                        className={cn(
                          "h-1.5 w-1.5 rounded-full",
                          i < activeStep && "bg-success",
                          i === activeStep && "animate-pulse bg-primary",
                          i > activeStep && "bg-muted"
                        )}
                      />
                      {step}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <Button onClick={runAnalysis} className="w-full sm:w-auto">
                Run analysis <ArrowRight className="h-3.5 w-3.5" />
              </Button>
            )}
          </CardContent>
        ) : null}
      </Card>
    </div>
  );
}
