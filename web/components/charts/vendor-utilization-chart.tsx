"use client";

import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { VendorBreakdown } from "@/lib/types";

const VENDOR_COLOR: Record<string, string> = {
  nvidia: "hsl(100 65% 45%)",
  amd: "hsl(0 72% 55%)",
  intel: "hsl(205 85% 55%)",
  aws: "hsl(32 90% 55%)",
};

const VENDOR_LABEL: Record<string, string> = {
  nvidia: "NVIDIA",
  amd: "AMD",
  intel: "Intel",
  aws: "AWS",
};

function ChartTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload as VendorBreakdown;
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 font-medium text-foreground">{VENDOR_LABEL[row.vendor] ?? row.vendor}</p>
      <p className="text-muted-foreground">
        {row.devices_allocated} / {row.devices_total} devices allocated
      </p>
      <p className="text-muted-foreground">{row.utilization_pct}% utilized</p>
    </div>
  );
}

export function VendorUtilizationChart({ data }: { data: VendorBreakdown[] }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" horizontal={false} />
        <XAxis
          type="number"
          domain={[0, 100]}
          tickFormatter={(v) => `${v}%`}
          stroke="hsl(var(--muted-foreground))"
          fontSize={11}
        />
        <YAxis
          type="category"
          dataKey="vendor"
          tickFormatter={(v) => VENDOR_LABEL[v] ?? v}
          stroke="hsl(var(--muted-foreground))"
          fontSize={12}
          width={64}
        />
        <Tooltip cursor={{ fill: "hsl(var(--muted) / 0.4)" }} content={<ChartTooltip />} />
        <Bar
          dataKey="utilization_pct"
          radius={[0, 4, 4, 0]}
          maxBarSize={22}
          isAnimationActive={false}
        >
          {data.map((row) => (
            <Cell key={row.vendor} fill={VENDOR_COLOR[row.vendor] ?? "hsl(var(--muted-foreground))"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
