"use client";

import { useState } from "react";

import { ProvenanceBadge } from "@/components/provenance-badge";
import { VendorBadge } from "@/components/vendor-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ComputeTarget } from "@/lib/types";
import { cn, formatPct } from "@/lib/utils";

const TIER_LABEL: Record<ComputeTarget["tier"], string> = {
  datacenter: "Datacenter",
  edge: "Edge",
  lab: "Lab",
};

export function InfrastructureExplorer({ targets }: { targets: ComputeTarget[] }) {
  const [selectedId, setSelectedId] = useState(targets[0]?.id);
  const selected = targets.find((t) => t.id === selectedId) ?? targets[0];

  return (
    <div className="grid grid-cols-1 gap-4 p-6 xl:grid-cols-5">
      <Card className="xl:col-span-3">
        <CardHeader>
          <CardTitle>Compute target inventory</CardTitle>
          <CardDescription>
            {targets.length} targets across cloud, edge and lab tiers. Select a row for
            compatibility and pricing detail.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Target</TableHead>
                <TableHead>Tier</TableHead>
                <TableHead>Capacity</TableHead>
                <TableHead>Utilization</TableHead>
                <TableHead className="text-right">Price / hr</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {targets.map((t) => (
                <TableRow
                  key={t.id}
                  onClick={() => setSelectedId(t.id)}
                  className={cn(
                    "cursor-pointer",
                    selected?.id === t.id && "bg-primary/5 hover:bg-primary/10"
                  )}
                >
                  <TableCell>
                    <div className="font-medium text-foreground">{t.model}</div>
                    <VendorBadge vendor={t.vendor} className="mt-0.5" />
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{TIER_LABEL[t.tier]}</Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {t.capacity_units_allocated} / {t.capacity_units_total}
                  </TableCell>
                  <TableCell className="w-40">
                    <div className="flex items-center gap-2">
                      <Progress value={t.utilization_pct} className="w-24" />
                      <span className="font-mono text-xs text-muted-foreground">
                        {formatPct(t.utilization_pct)}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    ${t.price_per_hr_per_unit.value.toFixed(2)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {selected ? (
        <Card className="xl:col-span-2">
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>{selected.model}</CardTitle>
              <Badge variant={selected.status === "healthy" ? "success" : "warning"}>
                {selected.status}
              </Badge>
            </div>
            <CardDescription>{selected.location}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            <dl className="grid grid-cols-2 gap-y-2">
              <dt className="text-muted-foreground">Architecture</dt>
              <dd className="text-right font-mono text-xs">{selected.architecture}</dd>
              <dt className="text-muted-foreground">Memory / device</dt>
              <dd className="text-right font-mono text-xs">{selected.memory_gb_per_device} GB</dd>
              <dt className="text-muted-foreground">Interconnect</dt>
              <dd className="text-right font-mono text-xs">{selected.interconnect}</dd>
              <dt className="text-muted-foreground">Free capacity</dt>
              <dd className="text-right font-mono text-xs">
                {selected.free_capacity_units} unit(s)
              </dd>
            </dl>

            <Separator />

            <div>
              <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Supported precisions
              </p>
              <div className="flex flex-wrap gap-1.5">
                {selected.supported_precisions.map((p) => (
                  <Badge key={p} variant="outline" className="font-mono">
                    {p}
                  </Badge>
                ))}
              </div>
            </div>

            <div className="flex items-center justify-between rounded-md border border-border bg-background/60 p-3">
              <div>
                <p className="text-xs text-muted-foreground">On-demand price</p>
                <p className="font-mono text-sm font-medium">
                  ${selected.price_per_hr_per_unit.value.toFixed(2)}/hr per unit
                </p>
              </div>
              <ProvenanceBadge provenance={selected.price_per_hr_per_unit.provenance} />
            </div>
            <p className="text-xs text-muted-foreground">{selected.price_per_hr_per_unit.source}</p>

            {selected.unsupported_workload_classes.length > 0 ? (
              <div>
                <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Workload class limitations
                </p>
                <ul className="space-y-1.5">
                  {selected.unsupported_workload_classes.map((u) => (
                    <li key={u.workload_class} className="rounded-md border border-warning/25 bg-warning/5 p-2 text-xs">
                      <span className="font-mono text-warning">{u.workload_class}</span>
                      <p className="mt-0.5 text-muted-foreground">{u.reason}</p>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {selected.notes ? (
              <p className="text-xs leading-relaxed text-muted-foreground">{selected.notes}</p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
