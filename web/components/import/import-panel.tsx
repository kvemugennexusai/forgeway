"use client";

import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Trash2, UploadCloud } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { ProvenanceBadge } from "@/components/provenance-badge";
import { api } from "@/lib/api";
import {
  addImportedEvidence,
  addImportedTarget,
  clearImported,
  getImportedEvidence,
  getImportedTargets,
  removeImportedEvidence,
  removeImportedTarget,
} from "@/lib/imported-storage";
import type { ComputeTarget, PerformanceEvidence } from "@/lib/types";

type UploadState = { status: "idle" } | { status: "error"; message: string } | { status: "success"; message: string };

function describeError(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

async function readJsonFile(file: File): Promise<unknown> {
  const text = await file.text();
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new Error(`"${file.name}" is not valid JSON — ${describeError(e)}`);
  }
}

function UploadResult({ state }: { state: UploadState }) {
  if (state.status === "idle") return null;
  return (
    <Alert variant={state.status === "error" ? "destructive" : "success"} className="mt-3">
      {state.status === "error" ? (
        <AlertCircle className="h-4 w-4" />
      ) : (
        <CheckCircle2 className="h-4 w-4" />
      )}
      <AlertTitle>{state.status === "error" ? "Import failed" : "Imported"}</AlertTitle>
      <AlertDescription className="break-words font-mono text-xs">{state.message}</AlertDescription>
    </Alert>
  );
}

export function ImportPanel() {
  const [targets, setTargets] = useState<ComputeTarget[]>([]);
  const [evidence, setEvidence] = useState<PerformanceEvidence[]>([]);
  const [referenceIds, setReferenceIds] = useState<Set<string>>(new Set());
  const [targetState, setTargetState] = useState<UploadState>({ status: "idle" });
  const [evidenceState, setEvidenceState] = useState<UploadState>({ status: "idle" });
  const targetInputRef = useRef<HTMLInputElement>(null);
  const evidenceInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setTargets(getImportedTargets());
    setEvidence(getImportedEvidence());
    api
      .listComputeTargets()
      .then((list) => setReferenceIds(new Set(list.map((t) => t.id))))
      .catch(() => setReferenceIds(new Set()));
  }, []);

  const importedIds = new Set(targets.map((t) => t.id));

  async function handleTargetUpload(file: File) {
    setTargetState({ status: "idle" });
    try {
      const raw = await readJsonFile(file);
      const validated = await api.validateComputeTarget(raw);
      if (referenceIds.has(validated.id)) {
        throw new Error(
          `id '${validated.id}' conflicts with a reference target already in the fixture catalog — ` +
            `re-export with a different id (this is never silently merged).`
        );
      }
      addImportedTarget(validated);
      setTargets(getImportedTargets());
      setTargetState({ status: "success", message: `${validated.model} (${validated.id})` });
    } catch (e) {
      setTargetState({ status: "error", message: describeError(e) });
    } finally {
      if (targetInputRef.current) targetInputRef.current.value = "";
    }
  }

  async function handleEvidenceUpload(file: File) {
    setEvidenceState({ status: "idle" });
    try {
      const raw = await readJsonFile(file);
      const validated = await api.validatePerformanceEvidence(raw);
      addImportedEvidence(validated);
      setEvidence(getImportedEvidence());
      setEvidenceState({
        status: "success",
        message: `${validated.workload_id} on ${validated.compute_target_id} (${validated.provenance})`,
      });
    } catch (e) {
      setEvidenceState({ status: "error", message: describeError(e) });
    } finally {
      if (evidenceInputRef.current) evidenceInputRef.current.value = "";
    }
  }

  function removeTarget(id: string) {
    removeImportedTarget(id);
    setTargets(getImportedTargets());
  }

  function removeEvidenceItem(e: PerformanceEvidence) {
    removeImportedEvidence(e);
    setEvidence(getImportedEvidence());
  }

  function clearAll() {
    clearImported();
    setTargets([]);
    setEvidence([]);
    setTargetState({ status: "idle" });
    setEvidenceState({ status: "idle" });
  }

  return (
    <div className="space-y-5 p-6">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">1. Compute target</CardTitle>
            <CardDescription>
              The JSON <code className="rounded bg-muted px-1 py-0.5">forgeway discover --json</code> printed —
              hardware/runtime metadata for the machine you benchmarked.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <label className="flex cursor-pointer flex-col items-center gap-2 rounded-md border border-dashed border-border p-6 text-center transition-colors hover:border-primary/40 hover:bg-primary/5">
              <UploadCloud className="h-5 w-5 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">Click to choose a ComputeTarget .json file</span>
              <input
                ref={targetInputRef}
                type="file"
                accept="application/json,.json"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void handleTargetUpload(file);
                }}
              />
            </label>
            <UploadResult state={targetState} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">2. Performance evidence</CardTitle>
            <CardDescription>
              The JSON <code className="rounded bg-muted px-1 py-0.5">forgeway bench --json</code> printed —
              measured latency/throughput for one workload on that target.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <label className="flex cursor-pointer flex-col items-center gap-2 rounded-md border border-dashed border-border p-6 text-center transition-colors hover:border-primary/40 hover:bg-primary/5">
              <UploadCloud className="h-5 w-5 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">Click to choose a PerformanceEvidence .json file</span>
              <input
                ref={evidenceInputRef}
                type="file"
                accept="application/json,.json"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void handleEvidenceUpload(file);
                }}
              />
            </label>
            <UploadResult state={evidenceState} />
          </CardContent>
        </Card>
      </div>

      <Alert>
        <AlertTitle className="text-xs uppercase tracking-wide">Local only, additive only</AlertTitle>
        <AlertDescription>
          Both files are validated against Forgeway&apos;s real schema and stored only in this browser
          (never uploaded to a server-side store, never persisted across devices). Importing never edits
          or replaces anything in the reference fixture catalog — an id collision is rejected, not merged.
        </AlertDescription>
      </Alert>

      <Separator />

      <div>
        <div className="mb-2 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-medium text-foreground">Your measured compute</h3>
            <Badge variant="measured" className="uppercase">
              Your measured compute
            </Badge>
          </div>
          {targets.length > 0 || evidence.length > 0 ? (
            <Button variant="ghost" size="sm" onClick={clearAll} className="text-muted-foreground">
              <Trash2 className="h-3.5 w-3.5" /> Clear all imported data
            </Button>
          ) : null}
        </div>

        {targets.length === 0 && evidence.length === 0 ? (
          <p className="rounded-md border border-dashed border-border p-4 text-xs text-muted-foreground">
            Nothing imported yet in this browser. Upload the two files above to add your own hardware to
            the workload analyzer, distinct from the reference compute below.
          </p>
        ) : (
          <div className="space-y-3">
            {targets.map((t) => (
              <div
                key={t.id}
                className="flex items-start justify-between gap-3 rounded-md border border-provenance-measured/30 bg-provenance-measured/5 p-3"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-sm font-medium text-foreground">{t.model}</p>
                    <Badge variant="outline" className="uppercase">
                      {t.vendor}
                    </Badge>
                  </div>
                  <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">{t.id}</p>
                  <dl className="mt-2 grid grid-cols-3 gap-2 text-[11px] text-muted-foreground sm:grid-cols-4">
                    <div>
                      <dt>Memory/device</dt>
                      <dd className="font-mono text-foreground">{t.memory_gb_per_device} GB</dd>
                    </div>
                    <div>
                      <dt>Devices</dt>
                      <dd className="font-mono text-foreground">{t.accelerator_count}</dd>
                    </div>
                    <div>
                      <dt>Architecture</dt>
                      <dd className="font-mono text-foreground">{t.architecture}</dd>
                    </div>
                    <div>
                      <dt>Location</dt>
                      <dd className="font-mono text-foreground">{t.location}</dd>
                    </div>
                  </dl>
                </div>
                <Button variant="ghost" size="icon" onClick={() => removeTarget(t.id)} title="Remove">
                  <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                </Button>
              </div>
            ))}

            {evidence.map((e) => {
              const key = e.benchmark_run_id ?? `${e.compute_target_id}::${e.workload_id}`;
              const usable = importedIds.has(e.compute_target_id) || referenceIds.has(e.compute_target_id);
              return (
                <div key={key} className="rounded-md border border-border bg-background/60 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-mono text-xs font-medium text-foreground">{e.workload_id}</p>
                        <span className="text-muted-foreground">on</span>
                        <p className="font-mono text-xs text-foreground">{e.compute_target_id}</p>
                        <ProvenanceBadge provenance={e.provenance} />
                      </div>
                      {e.configuration ? (
                        <p className="mt-1 text-[11px] text-muted-foreground">{e.configuration}</p>
                      ) : null}
                      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
                        {Object.entries(e.metrics).map(([name, m]) => (
                          <span key={name} className="font-mono text-muted-foreground">
                            {name}: <span className="text-foreground">{m.value}</span>
                          </span>
                        ))}
                      </div>
                      <p className="mt-2 text-[11px] text-muted-foreground">
                        Source: {e.source || "—"}
                        {e.benchmark_run_id ? ` · run ${e.benchmark_run_id}` : ""}
                      </p>
                      {!usable ? (
                        <p className="mt-1.5 flex items-center gap-1 text-[11px] text-warning">
                          <AlertCircle className="h-3 w-3" /> No matching target imported yet — this
                          evidence won&apos;t be used in analysis until you also import the ComputeTarget
                          for &apos;{e.compute_target_id}&apos;.
                        </p>
                      ) : null}
                    </div>
                    <Button variant="ghost" size="icon" onClick={() => removeEvidenceItem(e)} title="Remove">
                      <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
