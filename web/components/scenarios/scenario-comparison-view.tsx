import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { StateSnapshotCard } from "@/components/scenarios/state-snapshot-card";
import { DemandSpikeTransition } from "@/components/scenarios/demand-spike-transition";
import { RecommendationHero } from "@/components/recommendations/recommendation-hero";
import { CurrentVsRecommended } from "@/components/recommendations/current-vs-recommended";
import { WhyThisTarget } from "@/components/recommendations/why-this-target";
import { SplitAllocationPanel } from "@/components/recommendations/split-allocation-panel";
import { CandidateComparisonTable } from "@/components/recommendations/candidate-comparison-table";
import { EvidencePanel } from "@/components/recommendations/evidence-panel";
import { TopologyView } from "@/components/topology/topology-view";
import { SCENARIO_ICON } from "@/lib/scenario-icons";
import type { ScenarioComparison } from "@/lib/types";

export function ScenarioComparisonView({
  comparison,
  onReset,
}: {
  comparison: ScenarioComparison;
  onReset: () => void;
}) {
  const Icon = SCENARIO_ICON[comparison.event.name];
  const changed =
    comparison.before.recommended_target_id !== comparison.after.recommended_target_id ||
    comparison.before.split_allocation.length > 0 ||
    comparison.after.split_allocation.length > 0;

  // The demand-spike scenario is the primary demo moment: when it actually
  // has a solo "before" placement and a projected breach to show, it gets
  // the elevated BEFORE -> EVENT -> AFTER treatment instead of the generic
  // snapshot row. Every other scenario — and a demand spike with nothing to
  // project — uses the standard comparison below.
  const isFlagshipSpike =
    comparison.event.name === "demand_spike" &&
    Boolean(comparison.after.unmitigated_projection) &&
    Boolean(comparison.before.recommended);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="rounded-md bg-primary/15 p-1.5">
            <Icon className="h-3.5 w-3.5 text-primary" />
          </div>
          <div>
            <p className="text-[11px] font-medium uppercase tracking-wide text-primary">Event</p>
            <p className="text-sm font-medium text-foreground">{comparison.event.label}</p>
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={onReset}>
          Reset
        </Button>
      </div>

      {isFlagshipSpike ? (
        <>
          <DemandSpikeTransition comparison={comparison} />
          <Alert variant={changed ? "warning" : "default"}>
            <AlertTitle>{changed ? "Why the recommendation changed" : "Why it didn't change"}</AlertTitle>
            <AlertDescription>{comparison.change_explanation}</AlertDescription>
          </Alert>
        </>
      ) : (
        <>
          <div className="grid grid-cols-1 items-stretch gap-3 sm:grid-cols-[1fr_auto_1fr]">
            <StateSnapshotCard label="Before" record={comparison.before} />
            <div className="hidden items-center justify-center sm:flex">
              <ArrowRight className="h-5 w-5 text-muted-foreground" />
            </div>
            <StateSnapshotCard label="After" record={comparison.after} />
          </div>

          <Alert variant={changed ? "warning" : "default"}>
            <AlertTitle>{changed ? "Why the recommendation changed" : "Why it didn't change"}</AlertTitle>
            <AlertDescription>{comparison.change_explanation}</AlertDescription>
          </Alert>

          <RecommendationHero record={comparison.after} />
        </>
      )}

      <div className="space-y-4">
        <CurrentVsRecommended record={comparison.after} />
        <WhyThisTarget record={comparison.after} />

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Topology</CardTitle>
            <CardDescription>Recomputed against this scenario&apos;s temporary overrides.</CardDescription>
          </CardHeader>
          <CardContent>
            <TopologyView record={comparison.after} />
          </CardContent>
        </Card>

        <SplitAllocationPanel record={comparison.after} />
        <CandidateComparisonTable candidates={comparison.after.candidates} />
        <EvidencePanel evidence={comparison.after.evidence} />

        <Link
          href={`/recommendations/${comparison.after.id}`}
          className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
        >
          View this recommendation as its own page <ArrowRight className="h-3 w-3" />
        </Link>
      </div>
    </div>
  );
}
