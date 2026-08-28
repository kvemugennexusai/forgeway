"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { RecommendationHero } from "@/components/recommendations/recommendation-hero";
import { CurrentVsRecommended } from "@/components/recommendations/current-vs-recommended";
import { WhyThisTarget } from "@/components/recommendations/why-this-target";
import { SplitAllocationPanel } from "@/components/recommendations/split-allocation-panel";
import { CandidateComparisonTable } from "@/components/recommendations/candidate-comparison-table";
import { EvidencePanel } from "@/components/recommendations/evidence-panel";
import { TopologyView } from "@/components/topology/topology-view";
import { ScenarioComparisonView } from "@/components/scenarios/scenario-comparison-view";
import { SCENARIO_ICON } from "@/lib/scenario-icons";
import { api } from "@/lib/api";
import type { DecisionRecord, ScenarioCatalogEntry, ScenarioComparison, ScenarioType } from "@/lib/types";

export function RecommendationWorkspace({
  record,
  scenarios,
}: {
  record: DecisionRecord;
  scenarios: ScenarioCatalogEntry[];
}) {
  const [comparison, setComparison] = useState<ScenarioComparison | null>(null);
  const [pending, setPending] = useState<ScenarioType | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function apply(scenario: ScenarioType) {
    setPending(scenario);
    setError(null);
    try {
      const result = await api.applyScenario(record.workload_id, scenario);
      setComparison(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scenario simulation failed.");
    } finally {
      setPending(null);
    }
  }

  if (comparison) {
    return (
      <div className="p-6">
        <ScenarioComparisonView comparison={comparison} onReset={() => setComparison(null)} />
      </div>
    );
  }

  const active = record;

  return (
    <div className="space-y-4 p-6">
      <RecommendationHero record={active} />
      <CurrentVsRecommended record={active} />
      <WhyThisTarget record={active} />

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Topology</CardTitle>
          <CardDescription>
            Every evaluated target funnels from the workload; the recommended path is highlighted.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <TopologyView record={active} />
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="space-y-5 xl:col-span-2">
          <SplitAllocationPanel record={active} />
          <CandidateComparisonTable candidates={active.candidates} />
        </div>
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Scenario simulation</CardTitle>
              <CardDescription>
                Temporary changes to this workload or the estate, recomputed by the same engine.
                Nothing here mutates persistent state.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-1.5">
              {scenarios.map((s) => {
                const Icon = SCENARIO_ICON[s.name];
                return (
                  <button
                    key={s.name}
                    onClick={() => apply(s.name)}
                    disabled={pending !== null}
                    className="flex w-full items-center gap-2.5 rounded-md border border-border px-2.5 py-2 text-left transition-colors hover:border-primary/40 hover:bg-primary/5 disabled:pointer-events-none disabled:opacity-60"
                  >
                    <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium text-foreground">{s.label}</p>
                      <p className="truncate text-[11px] text-muted-foreground">{s.description}</p>
                    </div>
                    {pending === s.name ? (
                      <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary" />
                    ) : null}
                  </button>
                );
              })}
              {error ? <p className="text-xs text-destructive">{error}</p> : null}
            </CardContent>
          </Card>
          <EvidencePanel evidence={active.evidence} />
        </div>
      </div>
    </div>
  );
}
