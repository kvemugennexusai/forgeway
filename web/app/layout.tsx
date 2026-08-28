import type { Metadata } from "next";

import { SidebarNav } from "@/components/layout/sidebar-nav";

import "./globals.css";

export const metadata: Metadata = {
  title: "Forgeway — Compute Decision Layer",
  description:
    "Forgeway is the decision layer for heterogeneous AI infrastructure: feasibility, prediction, ranking and explanation for every workload placement.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="flex min-h-screen bg-background font-sans antialiased">
        <SidebarNav />
        <div className="flex min-w-0 flex-1 flex-col">
          <main className="flex-1 overflow-x-hidden">{children}</main>
        </div>
      </body>
    </html>
  );
}
