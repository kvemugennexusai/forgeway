import Link from "next/link";
import { ArrowRight, Cpu, DollarSign, Gauge, Layers, ShieldCheck } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { KpiCard } from "@/components/dashboard/kpi-card";
import { PlacementOpportunity } from "@/components/dashboard/placement-opportunity";
import { VendorUtilizationChart } from "@/components/charts/vendor-utilization-chart";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatPct } from "@/lib/utils";

export default async function DashboardPage() {
  const [estate, targets] = await Promise.all([api.estateSummary(), api.listComputeTargets()]);

  return (
    <div className="flex flex-col">
      <PageHeader
        eyebrow="Compute estate"
        title="Estate overview"
        description="Heterogeneous accelerator fleet across cloud, edge, and on-prem lab capacity — utilization, spend, and SLO posture at a glance."
        actions={
          <Button asChild size="sm">
            <Link href="/analyze">
              Analyze a workload <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </Button>
        }
      />

      <div className="grid grid-cols-1 gap-4 p-6 sm:grid-cols-2 xl:grid-cols-5">
        <KpiCard
          label="Devices allocated"
          value={`${estate.devices_allocated} / ${estate.devices_total}`}
          sub={`${formatPct(estate.overall_utilization_pct)} fleet utilization`}
          icon={Cpu}
        />
        <KpiCard
          label="Active workloads"
          value={String(estate.active_workloads)}
          sub="Across realtime, batch and edge classes"
          icon={Layers}
        />
        <KpiCard
          label="Estimated spend"
          value={`$${estate.estimated_spend_per_hr.toFixed(2)}/hr`}
          sub="Current placements, on-demand rates"
          icon={DollarSign}
        />
        <KpiCard
          label="SLO compliance"
          value={formatPct(estate.slo_compliance_pct)}
          sub="Of active workloads meeting P99 target"
          icon={ShieldCheck}
          tone={estate.slo_compliance_pct >= 99 ? "success" : "warning"}
        />
        <KpiCard
          label="Compute targets"
          value={String(targets.length)}
          sub="NVIDIA, AMD, Intel, AWS, edge, lab"
          icon={Gauge}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 px-6 pb-6 lg:grid-cols-5">
        <PlacementOpportunity insights={estate.insights} />

        <Card className="lg:col-span-2">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Utilization by vendor</CardTitle>
            <CardDescription>Allocated capacity as a share of total capacity units.</CardDescription>
          </CardHeader>
          <CardContent>
            <VendorUtilizationChart data={estate.vendor_breakdown} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
