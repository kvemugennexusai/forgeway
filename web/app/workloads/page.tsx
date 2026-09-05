import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ProvenanceBadge } from "@/components/provenance-badge";
import { api } from "@/lib/api";

const CLASS_LABEL: Record<string, string> = {
  "realtime-inference": "Realtime inference",
  "batch-inference": "Batch inference",
  training: "Training",
};

export default async function WorkloadsPage() {
  const items = await api.listWorkloads();

  return (
    <div className="flex flex-col">
      <PageHeader
        eyebrow="Compute estate"
        title="Workloads"
        description="Active workloads and their current placement. Each row's latency figure shows its own provenance (measured, published, or modeled) — not all of them are live telemetry."
      />
      <div className="p-6">
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Workload</TableHead>
                  <TableHead>Class</TableHead>
                  <TableHead>Current placement</TableHead>
                  <TableHead>P99 latency</TableHead>
                  <TableHead>SLO</TableHead>
                  <TableHead className="text-right">Cost / hr</TableHead>
                  <TableHead className="text-right">Decision</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map(({ workload, slo_status, latest_recommendation_id }) => (
                  <TableRow key={workload.id}>
                    <TableCell>
                      <div className="font-medium text-foreground">{workload.name}</div>
                      <div className="text-xs text-muted-foreground">{workload.model_family}</div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{CLASS_LABEL[workload.workload_class]}</Badge>
                    </TableCell>
                    <TableCell>
                      <div className="font-mono text-xs">{workload.current_placement.target_id}</div>
                      <div className="text-xs text-muted-foreground">
                        {workload.current_placement.replica_count}x replica
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-xs">
                          {workload.current_placement.measured_p99_latency_ms.toFixed(0)}ms
                        </span>
                        <ProvenanceBadge provenance={workload.current_placement.provenance} />
                      </div>
                      <div className="text-xs text-muted-foreground">
                        SLO {workload.slo.p99_latency_ms.toFixed(0)}ms
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={slo_status === "met" ? "success" : "destructive"}>
                        {slo_status === "met" ? "Met" : "Violated"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      ${workload.current_placement.cost_per_hr.toFixed(2)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Link
                        href={
                          latest_recommendation_id
                            ? `/recommendations/${latest_recommendation_id}`
                            : `/analyze?workload=${workload.id}`
                        }
                        className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                      >
                        {latest_recommendation_id ? "View recommendation" : "Analyze"}
                        <ArrowRight className="h-3 w-3" />
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
