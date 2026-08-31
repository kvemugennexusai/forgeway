"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Server, ScanSearch, ListChecks, Boxes, UploadCloud } from "lucide-react";

import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "Estate overview", icon: LayoutDashboard },
  { href: "/infrastructure", label: "Infrastructure", icon: Server },
  { href: "/analyze", label: "Analyze workload", icon: ScanSearch },
  { href: "/workloads", label: "Workloads", icon: ListChecks },
  { href: "/import", label: "Import result", icon: UploadCloud },
];

export function SidebarNav() {
  const pathname = usePathname();

  return (
    <aside className="hidden w-60 shrink-0 border-r border-border bg-card/40 lg:flex lg:flex-col">
      <div className="flex h-14 items-center gap-2 border-b border-border px-5">
        <Boxes className="h-4 w-4 text-primary" />
        <span className="text-sm font-semibold tracking-tight">Forgeway</span>
      </div>

      <nav className="flex-1 space-y-0.5 px-3 py-4">
        {NAV_ITEMS.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors",
                active
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground"
              )}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-border p-4">
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          Fixture-driven demo. No live infrastructure is connected — every figure below carries
          its provenance.
        </p>
      </div>
    </aside>
  );
}
