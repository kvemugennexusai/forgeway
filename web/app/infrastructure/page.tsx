import { PageHeader } from "@/components/layout/page-header";
import { InfrastructureExplorer } from "@/components/infrastructure/infrastructure-explorer";
import { api } from "@/lib/api";

export default async function InfrastructurePage() {
  const targets = await api.listComputeTargets();

  return (
    <div className="flex flex-col">
      <PageHeader
        eyebrow="Compute estate"
        title="Infrastructure"
        description="Every compute target Forgeway currently evaluates against — capacity, pricing, and hard compatibility constraints."
      />
      <InfrastructureExplorer targets={targets} />
    </div>
  );
}
