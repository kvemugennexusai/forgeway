import { Suspense } from "react";

import { PageHeader } from "@/components/layout/page-header";
import { AnalyzeForm } from "@/components/analyze/analyze-form";
import { api } from "@/lib/api";

export default async function AnalyzePage() {
  const items = await api.listWorkloads();

  return (
    <div className="flex flex-col">
      <PageHeader
        eyebrow="Decision engine"
        title="Analyze workload"
        description="Run a workload through feasibility, prediction, ranking and explanation against every compute target in the estate."
      />
      <Suspense>
        <AnalyzeForm items={items} />
      </Suspense>
    </div>
  );
}
