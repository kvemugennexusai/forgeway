import { notFound } from "next/navigation";

import { PageHeader } from "@/components/layout/page-header";
import { RecommendationWorkspace } from "@/components/recommendations/recommendation-workspace";
import { api } from "@/lib/api";

export default async function RecommendationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let record;
  try {
    record = await api.getRecommendation(id);
  } catch {
    notFound();
  }

  const scenarios = await api.listScenarios();

  return (
    <div className="flex flex-col">
      <PageHeader
        eyebrow="Recommendation"
        title={record.workload_name}
        description={`Decision record ${record.id} — ${record.scenario.label}`}
      />
      <RecommendationWorkspace record={record} scenarios={scenarios} />
    </div>
  );
}
