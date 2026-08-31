import { PageHeader } from "@/components/layout/page-header";
import { ImportPanel } from "@/components/import/import-panel";

export default function ImportPage() {
  return (
    <div className="flex flex-col">
      <PageHeader
        eyebrow="Bring your own hardware"
        title="Import benchmark result"
        description="Upload a real ComputeTarget + PerformanceEvidence pair from `forgeway discover` and `forgeway bench` — validated against Forgeway's schema, kept only in this browser, and available to the workload analyzer without touching the reference fixture catalog."
      />
      <ImportPanel />
    </div>
  );
}
